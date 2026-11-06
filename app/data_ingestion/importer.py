import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Ensure project root is in sys.path
_file_path = Path(__file__).resolve()
_project_dir = _file_path.parent.parent.parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

from sqlalchemy import text
from app.database import engine
from .fastf1_client import FastF1Client
from .cleaner import DataCleaner

logger = logging.getLogger("f1_ingestion.importer")


class DatabaseImporter:
    """
    Idempotent database importer that ingests cleaned F1 session, lap,
    stint, and pit stop data into PostgreSQL with full transaction safety.
    """

    def __init__(self):
        self.client = FastF1Client()

    def import_round(self, season: int, round_no: int) -> Dict[str, Any]:
        """
        Imports a single race round for a given season.
        Returns a summary report.
        """
        logger.info(f"Starting ingestion for {season} Round {round_no}...")
        
        # 1. Fetch raw data
        raw_data = self.client.get_race_session(season, round_no)
        raw_results = raw_data.get("results") or []
        raw_laps = raw_data.get("laps") or []
        raw_stints = raw_data.get("stints") or []
        raw_pits = raw_data.get("pit_stops") or []

        if not raw_results and not raw_laps:
            raise ValueError(f"No race data available for {season} Round {round_no} in FastF1/OpenF1 cache/API")

        # 2. Build complete driver mapping from all available feeds
        driver_map: Dict[int, str] = {}
        driver_info: Dict[str, Dict[str, Any]] = {}

        # First pass from results
        for d in raw_results:
            num = d.get("driver_number")
            acronym = d.get("name_acronym")
            full_name = d.get("full_name") or d.get("broadcast_name")
            team_name = d.get("team_name")
            code, clean_name = DataCleaner.resolve_driver(num, acronym, full_name)
            if num:
                driver_map[int(num)] = code
            driver_info[code] = {
                "code": code,
                "name": clean_name,
                "team": team_name or "Independent",
                "grid": d.get("grid_position") or 10,
                "pos": d.get("position")
            }

        # Second pass from laps, stints, and pits to catch any missing drivers
        all_driver_nums = set()
        for item in raw_laps + raw_stints + raw_pits:
            num = item.get("driver_number")
            if num is not None:
                all_driver_nums.add(int(num))

        for num in all_driver_nums:
            if num not in driver_map:
                code, clean_name = DataCleaner.resolve_driver(num)
                driver_map[num] = code
                if code not in driver_info:
                    driver_info[code] = {
                        "code": code,
                        "name": clean_name,
                        "team": "Independent",
                        "grid": 10,
                        "pos": None
                    }

        # 3. Clean records
        cleaned_stints = DataCleaner.clean_stint_rows(raw_stints, driver_map)
        cleaned_pits = DataCleaner.clean_pit_rows(raw_pits, driver_map)
        cleaned_laps = DataCleaner.clean_lap_rows(raw_laps, driver_map)

        # 4. Perform database transaction
        job_id = None
        try:
            with engine.begin() as init_conn:
                job_id = init_conn.execute(text("""
                    INSERT INTO ingestion_jobs (season, round_no, session_type, status)
                    VALUES (:s, :r, 'R', 'running') RETURNING job_id
                """), {"s": season, "r": round_no}).scalar()

            with engine.begin() as conn:
                # Resolve or ensure race exists
                race = conn.execute(text("""
                    SELECT race_id, track_id FROM races WHERE season = :s AND round_no = :r
                """), {"s": season, "r": round_no}).first()

                if not race:
                    track_id = round_no if round_no <= 24 else ((round_no - 1) % 24) + 1
                    race_id = conn.execute(text("""
                        INSERT INTO races (season, round_no, track_id, race_date, status)
                        VALUES (:s, :r, :t, :d, 'completed')
                        ON CONFLICT (season, round_no) DO UPDATE SET status = 'completed'
                        RETURNING race_id
                    """), {
                        "s": season,
                        "r": round_no,
                        "t": track_id,
                        "d": f"{season}-05-01"
                    }).scalar()
                else:
                    race_id = race[0]

                # Map compound IDs
                compounds_lookup = dict(conn.execute(text("SELECT name, compound_id FROM compounds")).fetchall())

                # Upsert drivers and teams
                driver_id_map: Dict[str, int] = {}
                for code, dm in driver_info.items():
                    team_name = dm["team"] or "Independent"
                    
                    team_id = conn.execute(text("""
                        INSERT INTO teams (name) VALUES (:t)
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                        RETURNING team_id
                    """), {"t": team_name}).scalar()

                    d_id = conn.execute(text("""
                        INSERT INTO drivers (code, full_name, team_id)
                        VALUES (:c, :n, :t)
                        ON CONFLICT (code) DO UPDATE SET team_id = EXCLUDED.team_id
                        RETURNING driver_id
                    """), {"c": code, "n": dm["name"], "t": team_id}).scalar()
                    driver_id_map[code] = d_id

                # Upsert Results
                results_count = 0
                for code, dm in driver_info.items():
                    d_id = driver_id_map.get(code)
                    if not d_id:
                        continue
                    grid = dm.get("grid") or 1
                    fin = dm.get("pos")
                    if fin is not None:
                        fin = int(fin)
                        if fin < 1 or fin > 24:
                            fin = None

                    conn.execute(text("""
                        INSERT INTO results (race_id, driver_id, grid_pos, finish_pos)
                        VALUES (:r, :d, :g, :f)
                        ON CONFLICT (race_id, driver_id) DO UPDATE 
                        SET grid_pos = COALESCE(EXCLUDED.grid_pos, results.grid_pos),
                            finish_pos = COALESCE(EXCLUDED.finish_pos, results.finish_pos)
                    """), {"r": race_id, "d": d_id, "g": grid, "f": fin})
                    results_count += 1

                # Insert Stints
                stints_count = 0
                stints_by_driver: Dict[str, List[Dict[str, Any]]] = {}
                if cleaned_stints:
                    conn.execute(text("DELETE FROM stints WHERE race_id = :r"), {"r": race_id})
                    for st in cleaned_stints:
                        code = st["driver_code"]
                        d_id = driver_id_map.get(code)
                        cid = compounds_lookup.get(st["compound"], compounds_lookup.get("MEDIUM", 2))
                        if d_id and cid:
                            conn.execute(text("""
                                INSERT INTO stints (race_id, driver_id, stint_no, compound_id, start_lap, end_lap)
                                VALUES (:r, :d, :s, :c, :sl, :el)
                                ON CONFLICT (race_id, driver_id, stint_no) DO UPDATE
                                SET compound_id = EXCLUDED.compound_id,
                                    start_lap = EXCLUDED.start_lap,
                                    end_lap = EXCLUDED.end_lap
                            """), {
                                "r": race_id, "d": d_id, "s": st["stint_no"],
                                "c": cid, "sl": st["start_lap"], "el": st["end_lap"]
                            })
                            stints_count += 1
                            stints_by_driver.setdefault(code, []).append(st)

                # Insert Pit Stops (with fitted tyre lookup from subsequent stint)
                pits_count = 0
                if cleaned_pits:
                    conn.execute(text("DELETE FROM pit_stops WHERE race_id = :r"), {"r": race_id})
                    for p in cleaned_pits:
                        code = p["driver_code"]
                        d_id = driver_id_map.get(code)
                        if not d_id:
                            continue
                        
                        # Identify tyre fitted: look for stint starting right after this pit lap
                        tyre_fitted_id = None
                        if code in stints_by_driver:
                            for st in stints_by_driver[code]:
                                if st["start_lap"] == p["lap_no"] + 1 or st["stint_no"] == p["stop_no"] + 1:
                                    tyre_fitted_id = compounds_lookup.get(st["compound"])
                                    break

                        conn.execute(text("""
                            INSERT INTO pit_stops (race_id, driver_id, stop_no, lap_no, pit_duration_s, stationary_time_s, tyre_fitted_id)
                            VALUES (:r, :d, :sn, :ln, :dur, :stat, :tyre)
                            ON CONFLICT (race_id, driver_id, stop_no) DO UPDATE
                            SET lap_no = EXCLUDED.lap_no,
                                pit_duration_s = EXCLUDED.pit_duration_s,
                                stationary_time_s = EXCLUDED.stationary_time_s,
                                tyre_fitted_id = EXCLUDED.tyre_fitted_id
                        """), {
                            "r": race_id, "d": d_id, "sn": p["stop_no"],
                            "ln": p["lap_no"], "dur": p["pit_duration_s"],
                            "stat": p["stationary_time_s"],
                            "tyre": tyre_fitted_id
                        })
                        pits_count += 1

                # Batch insert laps into partitioned lap_telemetry
                laps_to_insert = []
                for lap in cleaned_laps:
                    code = lap["driver_code"]
                    d_id = driver_id_map.get(code)
                    if not d_id:
                        continue
                    lap_no = lap["lap_no"]
                    
                    # Determine compound and tyre age from stints
                    tyre_age = 1
                    compound_name = "MEDIUM"
                    if code in stints_by_driver:
                        for st in stints_by_driver[code]:
                            if st["start_lap"] <= lap_no <= st["end_lap"]:
                                tyre_age = lap_no - st["start_lap"] + 1
                                compound_name = st["compound"]
                                break
                    cid = compounds_lookup.get(compound_name, compounds_lookup.get("MEDIUM", 2))

                    laps_to_insert.append({
                        "r": race_id, "d": d_id, "l": lap_no,
                        "lt": lap["lap_time_s"],
                        "s1": lap["sector1_s"], "s2": lap["sector2_s"], "s3": lap["sector3_s"],
                        "age": tyre_age, "pit": lap["is_pit_lap"], "c": cid
                    })

                laps_count = 0
                if laps_to_insert:
                    # Clean previous laps for idempotent re-run
                    conn.execute(text("DELETE FROM lap_telemetry WHERE race_id = :r"), {"r": race_id})
                    
                    insert_sql = text("""
                        INSERT INTO lap_telemetry (
                            race_id, driver_id, lap_no, lap_time_s,
                            sector1_s, sector2_s, sector3_s, tyre_age_laps,
                            is_pit_lap, compound_id
                        ) VALUES (
                            :r, :d, :l, :lt, :s1, :s2, :s3, :age, :pit, :c
                        ) ON CONFLICT (race_id, driver_id, lap_no) DO UPDATE
                        SET lap_time_s = EXCLUDED.lap_time_s,
                            sector1_s = EXCLUDED.sector1_s,
                            sector2_s = EXCLUDED.sector2_s,
                            sector3_s = EXCLUDED.sector3_s,
                            tyre_age_laps = EXCLUDED.tyre_age_laps,
                            is_pit_lap = EXCLUDED.is_pit_lap,
                            compound_id = EXCLUDED.compound_id
                    """)
                    
                    # Execute in chunks of 500 for high efficiency
                    chunk_size = 500
                    for i in range(0, len(laps_to_insert), chunk_size):
                        conn.execute(insert_sql, laps_to_insert[i:i + chunk_size])
                    laps_count = len(laps_to_insert)

                # Validation check: do not report completed if 0 laps
                if laps_count == 0 and len(cleaned_laps) > 0:
                    raise ValueError(f"Failed to resolve any drivers for {len(cleaned_laps)} laps")

                # Refresh Materialized View
                try:
                    conn.execute(text("REFRESH MATERIALIZED VIEW mv_driver_championship;"))
                except Exception as mv_err:
                    logger.warning(f"Materialized view refresh skipped: {mv_err}")

                # Update job log on success
                conn.execute(text("""
                    UPDATE ingestion_jobs
                    SET status = 'completed',
                        laps_imported = :l,
                        stints_imported = :st,
                        stops_imported = :sp,
                        finished_at = clock_timestamp()
                    WHERE job_id = :jid
                """), {
                    "l": laps_count, "st": stints_count,
                    "sp": pits_count, "jid": job_id
                })

                return {
                    "status": "completed",
                    "season": season,
                    "round_no": round_no,
                    "race_id": race_id,
                    "results_imported": results_count,
                    "laps_imported": laps_count,
                    "stints_imported": stints_count,
                    "stops_imported": pits_count,
                    "drivers_count": len(driver_info)
                }

        except Exception as e:
            logger.error(f"Ingestion failed for {season} R{round_no}: {e}")
            if job_id:
                try:
                    with engine.begin() as err_conn:
                        err_conn.execute(text("""
                            UPDATE ingestion_jobs
                            SET status = 'failed',
                                error_message = :err,
                                finished_at = clock_timestamp()
                            WHERE job_id = :jid
                        """), {"err": str(e)[:500], "jid": job_id})
                except Exception:
                    pass
            raise e

    def import_season(self, season: int, max_rounds: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Imports all available rounds for a season.
        """
        schedule = self.client.get_schedule(season)
        if not schedule:
            raise ValueError(f"No schedule found for season {season}")

        results = []
        rounds_to_import = schedule[:max_rounds] if max_rounds else schedule
        for event in rounds_to_import:
            rnd = event["round_no"]
            try:
                res = self.import_round(season, rnd)
                results.append(res)
            except Exception as e:
                logger.error(f"Error importing {season} Round {rnd}: {e}")
                results.append({
                    "status": "failed",
                    "season": season,
                    "round_no": rnd,
                    "error": str(e)
                })
        return results
