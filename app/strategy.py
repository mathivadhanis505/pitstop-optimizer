from typing import Dict, Any, List, Optional
from sqlalchemy import text

REASON = {
    "pit": "more pit-stop time (pit-lane loss plus lost track position)",
    "wear": "heavier tyre wear over its stints",
    "pace": "slower compound pace",
}
GAIN = {"pit": "pit time", "pace": "compound pace", "wear": "tyre wear"}


def pit_laps_from(stint_laps):
    out, total = [], 0
    for n in stint_laps[:-1]:
        total += n
        out.append(total)
    return out


def shape(r):
    return {
        "stops": r["stops"],
        "compounds": r["compounds"].split(" > "),
        "stint_laps": r["stint_laps"],
        "pit_laps": pit_laps_from(r["stint_laps"]),
        "total_s": round(r["total_s"], 2),
        "delta_s": None if r["delta_s"] is None else round(r["delta_s"], 2),
        "cost": {
            "pit": round(r["pit_cost_s"], 2),
            "pace": round(r["pace_cost_s"], 2),
            "wear": round(r["wear_cost_s"], 2),
        },
    }


def why_best(best, driver_profile=None):
    stops = best["stops"]
    compounds = best["compounds"].split(" > ")
    pit_laps = pit_laps_from(best["stint_laps"])
    pit_loss = best["pit_cost_s"]
    wear_cost = best["wear_cost_s"]
    total = best["total_s"]
    
    pit_str = f"Lap {', '.join(str(p) for p in pit_laps)}" if pit_laps else "Non-stop"
    comp_arrow = " &rarr; ".join(compounds)
    stint_plan = ", ".join(f"{c} ({l}L)" for c, l in zip(compounds, best["stint_laps"]))

    driver_name = driver_profile.get("driver_name") if driver_profile else None
    title = f"Optimal {stops}-Stop for {driver_name} ({comp_arrow})" if driver_name else f"Optimal {stops}-Stop ({comp_arrow})"

    return (
        f"<b>{title}:</b> Quickest total time ({total:.1f}s net). "
        f"Stints: {stint_plan}. Pit window: <b>{pit_str}</b> before tyre cliff."
    )


def why_not(best, alt):
    diff = {k: alt[f"{k}_cost_s"] - best[f"{k}_cost_s"] for k in ("pit", "pace", "wear")}
    delta = alt["delta_s"]
    alt_stops = alt["stops"]
    best_stops = best["stops"]
    alt_comp = " &rarr; ".join(alt["compounds"].split(" > "))
    
    if alt_stops < best_stops:
        reason = f"<b>+{delta:.1f}s slower:</b> Saves pit lane time (-{abs(diff['pit']):.1f}s) but loses {diff['wear']:.1f}s to heavy tyre wear."
    elif alt_stops > best_stops:
        reason = f"<b>+{delta:.1f}s slower:</b> Extra pit stop (+{diff['pit']:.1f}s) costs more time than fresh tyres gain."
    else:
        reason = f"<b>+{delta:.1f}s slower:</b> {alt_comp} suffers higher pace & wear loss (+{diff.get('pace', 0) + diff.get('wear', 0):.1f}s)."
        
    return reason, {k: round(v, 2) for k, v in diff.items()}


def why_rejected(r):
    compound = r.get("limiting_compound") or "tyre"
    overrun = round(r.get("overrun_laps", 0))
    return f"<b>Disqualified:</b> {compound} exceeds safe life by {overrun} laps (puncture/blistering risk)."


def build_response(rows, empirical_context=None, driver_profile=None):
    ok = [r for r in rows if r["feasible"]]
    bad = sorted((r for r in rows if not r["feasible"]), key=lambda r: r["overrun_laps"])

    rejected = [{**shape(r), "why_not": why_rejected(r)} for r in bad[:3]]
    if not ok:
        return {
            "best": None,
            "alternatives": [],
            "rejected": rejected,
            "message": "No viable strategy found for these conditions.",
            "empirical_context": empirical_context,
            "driver_profile": driver_profile
        }

    best = ok[0]
    alternatives = []
    for r in ok[1:4]:
        text, breakdown = why_not(best, r)
        alternatives.append({**shape(r), "why_not": text, "vs_best": breakdown})

    response = {
        "best": {**shape(best), "why": why_best(best, driver_profile)},
        "alternatives": alternatives,
        "rejected": rejected,
    }
    if empirical_context:
        response["empirical_context"] = empirical_context
    if driver_profile:
        response["driver_profile"] = driver_profile

    return response


def get_driver_metrics(conn, track_id: int, driver_code: str) -> Optional[Dict[str, Any]]:
    code = driver_code.strip().upper()
    driver = conn.execute(text("""
        SELECT d.driver_id, d.code, d.full_name, d.team_id, t.name AS team_name
        FROM drivers d
        LEFT JOIN teams t ON t.team_id = d.team_id
        WHERE d.code = :code
    """), {"code": code}).mappings().first()
    
    if not driver:
        return None

    # Empirical laps for this driver at this track
    laps_row = conn.execute(text("""
        SELECT COUNT(lt.lap_no) AS lap_count,
               AVG(lt.lap_time_s) AS mean_lap_time_s,
               MIN(lt.lap_time_s) AS best_lap_time_s
        FROM lap_telemetry lt
        JOIN races r ON r.race_id = lt.race_id
        WHERE r.track_id = :t AND lt.driver_id = :d AND lt.is_pit_lap = FALSE
    """), {"t": track_id, "d": driver["driver_id"]}).mappings().first()

    # Track field baseline average
    field_row = conn.execute(text("""
        SELECT AVG(lt.lap_time_s) AS field_avg_lap_time_s
        FROM lap_telemetry lt
        JOIN races r ON r.race_id = lt.race_id
        WHERE r.track_id = :t AND lt.is_pit_lap = FALSE
    """), {"t": track_id}).mappings().first()

    has_empirical = (
        laps_row is not None and
        laps_row["lap_count"] is not None and
        laps_row["lap_count"] >= 5 and
        field_row is not None and
        field_row["field_avg_lap_time_s"] is not None
    )

    if has_empirical:
        driver_mean = float(laps_row["mean_lap_time_s"])
        field_mean = float(field_row["field_avg_lap_time_s"])
        best_time = float(laps_row["best_lap_time_s"])
        pace_delta_s = round(driver_mean - field_mean, 3)
        confidence = "Empirical Telemetry (High Confidence)"
        sample_laps = int(laps_row["lap_count"])
    else:
        # Calibrated baseline pace offset based on known driver/car competitiveness
        calibrated_pace_map = {
            "VER": -0.22, "NOR": -0.19, "LEC": -0.18, "HAM": -0.14,
            "RUS": -0.12, "PIA": -0.11, "SAI": -0.09, "ANT": -0.10,
            "ALO": -0.07, "GAS": 0.05, "OCO": 0.06, "ALB": 0.08,
            "TSU": 0.10, "HUL": 0.11, "BOT": 0.18, "ZHO": 0.22
        }
        pace_delta_s = calibrated_pace_map.get(code, 0.0)
        driver_mean = None
        best_time = None
        confidence = "Calibrated Simulation (Baseline Confidence)"
        sample_laps = 0

    # Team Pit Stop Stationary Performance
    team_stat = 3.50
    team_stat_count = 0
    if driver["team_id"]:
        pit_stat_row = conn.execute(text("""
            SELECT ROUND(AVG(ps.stationary_time_s)::numeric, 2) AS avg_stat,
                   COUNT(*) AS pit_count
            FROM pit_stops ps
            JOIN drivers d ON d.driver_id = ps.driver_id
            WHERE d.team_id = :team_id
        """), {"team_id": driver["team_id"]}).mappings().first()
        if pit_stat_row and pit_stat_row["avg_stat"] is not None:
            team_stat = float(pit_stat_row["avg_stat"])
            team_stat_count = int(pit_stat_row["pit_count"])

    team_pit_delta_s = round(team_stat - 3.50, 2)

    # Teammate Lookup & Pace Head-to-Head
    teammate_code = None
    teammate_name = None
    teammate_comparison = "No teammate on record"
    if driver["team_id"]:
        tm_row = conn.execute(text("""
            SELECT d.driver_id, d.code, d.full_name
            FROM drivers d
            WHERE d.team_id = :team_id AND d.driver_id != :driver_id
            ORDER BY d.code LIMIT 1
        """), {"team_id": driver["team_id"], "driver_id": driver["driver_id"]}).mappings().first()
        if tm_row:
            teammate_code = tm_row["code"]
            teammate_name = tm_row["full_name"]
            if has_empirical:
                tm_laps = conn.execute(text("""
                    SELECT AVG(lt.lap_time_s) AS mean_lap_time_s
                    FROM lap_telemetry lt
                    JOIN races r ON r.race_id = lt.race_id
                    WHERE r.track_id = :t AND lt.driver_id = :d AND lt.is_pit_lap = FALSE
                """), {"t": track_id, "d": tm_row["driver_id"]}).mappings().first()
                if tm_laps and tm_laps["mean_lap_time_s"]:
                    diff = round(driver_mean - float(tm_laps["mean_lap_time_s"]), 2)
                    sign = "+" if diff > 0 else ""
                    comp_text = "slower" if diff > 0 else "faster"
                    teammate_comparison = f"{sign}{diff}s/lap ({abs(diff)}s {comp_text} than {tm_row['code']})"
                else:
                    teammate_comparison = f"Estimated teammate pace parity vs {tm_row['code']}"
            else:
                teammate_comparison = f"Theoretical teammate parity vs {tm_row['code']}"

    return {
        "driver_code": driver["code"],
        "driver_name": driver["full_name"],
        "team_name": driver["team_name"] or "Independent",
        "has_empirical_telemetry": has_empirical,
        "confidence": confidence,
        "sample_laps": sample_laps,
        "mean_lap_time_s": round(driver_mean, 3) if driver_mean else None,
        "best_lap_time_s": round(best_time, 3) if best_time else None,
        "pace_delta_s_per_lap": pace_delta_s,
        "team_stationary_s": team_stat,
        "team_pit_sample_size": team_stat_count,
        "team_pit_delta_s": team_pit_delta_s,
        "teammate_code": teammate_code,
        "teammate_name": teammate_name,
        "teammate_comparison": teammate_comparison
    }


def optimize_driver_strategy(
    conn,
    track_id: int,
    raw_strategies: List[Dict[str, Any]],
    driver_code: Optional[str] = None,
    driver_profile: Optional[Dict[str, Any]] = None,
    starting_compound: Optional[str] = None,
    max_stops: Optional[int] = None,
    safety_car: Optional[str] = "NONE"
) -> List[Dict[str, Any]]:
    if not raw_strategies:
        return []

    track_meta = conn.execute(text("""
        SELECT laps, pit_loss_s FROM tracks WHERE track_id = :t
    """), {"t": track_id}).mappings().first()

    total_laps = track_meta["laps"] if track_meta else 57
    base_pit_loss = float(track_meta["pit_loss_s"]) if track_meta else 22.0

    pace_delta_s = driver_profile.get("pace_delta_s_per_lap", 0.0) if driver_profile else 0.0
    pit_delta_per_stop = driver_profile.get("team_pit_delta_s", 0.0) if driver_profile else 0.0

    sc_mode = (safety_car or "NONE").upper()

    candidate_rows = []
    for r in raw_strategies:
        row = dict(r)
        comp_parts = [c.strip() for c in row["compounds"].split(">")]

        # 1. Starting compound filter
        if starting_compound and starting_compound.upper() not in ("ANY", "ALL", ""):
            if not comp_parts or comp_parts[0].upper() != starting_compound.upper():
                continue

        # 2. Max stops filter
        if max_stops is not None and max_stops > 0:
            if row["stops"] > max_stops:
                continue

        # 3. Driver pace & Team pit stop variance
        driver_pace_adj = pace_delta_s * total_laps if driver_code else 0.0
        team_pit_adj = pit_delta_per_stop * row["stops"] if driver_code else 0.0

        # 4. Safety Car / VSC discount
        sc_discount_s = 0.0
        if sc_mode == "SC":
            sc_discount_s = row["stops"] * (base_pit_loss * 0.42)
        elif sc_mode == "VSC":
            sc_discount_s = row["stops"] * (base_pit_loss * 0.30)

        row["total_s"] = round(row["total_s"] + driver_pace_adj + team_pit_adj - sc_discount_s, 2)
        row["pit_cost_s"] = max(0.0, round(row["pit_cost_s"] + team_pit_adj - sc_discount_s, 2))
        row["pace_cost_s"] = max(0.0, round(row["pace_cost_s"] + driver_pace_adj, 2))
        candidate_rows.append(row)

    feasible = [r for r in candidate_rows if r["feasible"]]
    infeasible = [r for r in candidate_rows if not r["feasible"]]

    feasible.sort(key=lambda x: x["total_s"])
    if feasible:
        best_t = feasible[0]["total_s"]
        for i, r in enumerate(feasible):
            r["rnk"] = i + 1
            r["delta_s"] = round(r["total_s"] - best_t, 2)

    return feasible + infeasible


def get_empirical_metrics(conn, track_id: int) -> Dict[str, Any]:
    """
    Retrieves measured historical pit stop durations, compound degradation pace,
    and actual race-winning strategies for a given track from the database.
    Falls back gracefully if data has not yet been ingested.
    """
    # 1. Historical Pit Stop Loss
    pit_stats = conn.execute(text("""
        SELECT COUNT(*) AS sample_size,
               ROUND(AVG(ps.pit_duration_s)::numeric, 2) AS avg_duration_s,
               ROUND(MIN(ps.pit_duration_s)::numeric, 2) AS min_duration_s,
               ROUND(MAX(ps.pit_duration_s)::numeric, 2) AS max_duration_s,
               ROUND(AVG(ps.stationary_time_s)::numeric, 2) AS avg_stationary_s
        FROM pit_stops ps
        JOIN races r ON r.race_id = ps.race_id
        WHERE r.track_id = :t;
    """), {"t": track_id}).mappings().first()

    has_pits = pit_stats and pit_stats["sample_size"] and pit_stats["sample_size"] > 0

    # 2. Historical Compound Pace & Degradation
    compound_stats = conn.execute(text("""
        SELECT c.name AS compound,
               COUNT(lt.lap_no) AS lap_count,
               ROUND(AVG(lt.lap_time_s)::numeric, 2) AS mean_lap_time_s,
               ROUND(MIN(lt.lap_time_s)::numeric, 2) AS best_lap_time_s,
               ROUND(AVG(lt.tyre_age_laps)::numeric, 1) AS mean_tyre_age
        FROM lap_telemetry lt
        JOIN races r ON r.race_id = lt.race_id
        JOIN compounds c ON c.compound_id = lt.compound_id
        WHERE r.track_id = :t AND lt.is_pit_lap = FALSE
        GROUP BY c.name
        ORDER BY mean_lap_time_s ASC;
    """), {"t": track_id}).mappings().all()

    has_laps = len(compound_stats) > 0

    # 3. Real Race Winner Strategy Precedent
    winner_strat = conn.execute(text("""
        SELECT r.season, r.round_no, d.code AS winner, tm.name AS team,
               string_agg(c.name || ' (' || (s.end_lap - s.start_lap + 1) || ' laps)', ' -> ' ORDER BY s.stint_no) AS strategy_used
        FROM results res
        JOIN races r ON r.race_id = res.race_id
        JOIN drivers d ON d.driver_id = res.driver_id
        LEFT JOIN teams tm ON tm.team_id = d.team_id
        JOIN stints s ON s.race_id = r.race_id AND s.driver_id = d.driver_id
        JOIN compounds c ON c.compound_id = s.compound_id
        WHERE r.track_id = :t AND res.finish_pos = 1
        GROUP BY r.race_id, r.season, r.round_no, d.code, tm.name
        ORDER BY r.season DESC LIMIT 1;
    """), {"t": track_id}).mappings().first()

    # Track baseline for comparison
    track_meta = conn.execute(text("""
        SELECT pit_loss_s, deg_factor FROM tracks WHERE track_id = :t
    """), {"t": track_id}).mappings().first()

    theoretical_pit_loss = float(track_meta["pit_loss_s"]) if track_meta else 22.0

    if has_pits or has_laps:
        empirical_pit = float(pit_stats["avg_duration_s"]) if (has_pits and pit_stats["avg_duration_s"]) else theoretical_pit_loss
        sc_pit_loss = round(empirical_pit * 0.58, 1)

        return {
            "has_empirical_data": True,
            "data_source": "Historical F1 Telemetry & OpenF1 Data Pipeline",
            "pit_loss": {
                "theoretical_model_s": theoretical_pit_loss,
                "measured_empirical_s": empirical_pit,
                "sample_pit_stops": pit_stats["sample_size"] if has_pits else 0,
                "avg_stationary_s": float(pit_stats["avg_stationary_s"]) if has_pits and pit_stats["avg_stationary_s"] else 2.5,
                "delta_s": round(empirical_pit - theoretical_pit_loss, 2),
                "accuracy_assessment": "High confidence (empirical telemetry match)"
            },
            "compounds_telemetry": [dict(c) for c in compound_stats],
            "safety_car_scenario": {
                "sc_pit_loss_s": sc_pit_loss,
                "sc_time_saved_s": round(empirical_pit - sc_pit_loss, 1),
                "strategic_impact": (
                    f"A Safety Car or Virtual Safety Car reduces pit-lane delta by ~{round(empirical_pit - sc_pit_loss, 1)}s. "
                    f"If a Safety Car occurs during your planned pit window, a 2-stop strategy effectively neutralizes its time loss disadvantage."
                )
            },
            "historical_race_precedent": {
                "season": winner_strat["season"],
                "round_no": winner_strat["round_no"],
                "winner": f"{winner_strat['winner']} ({winner_strat['team']})",
                "strategy": winner_strat["strategy_used"]
            } if winner_strat else None,
            "disclaimer": "Empirical metrics reflect historical session telemetry. Actual race pace varies with ambient temperature, track rubbering, and SC disruptions."
        }
    else:
        return {
            "has_empirical_data": False,
            "data_source": "Simulated Theoretical Model (Calibrated F1 Baselines)",
            "pit_loss": {
                "theoretical_model_s": theoretical_pit_loss,
                "measured_empirical_s": None,
                "sample_pit_stops": 0,
                "accuracy_assessment": "Simulated estimate (no ingested telemetry for this track yet)"
            },
            "compounds_telemetry": [],
            "safety_car_scenario": {
                "sc_pit_loss_s": round(theoretical_pit_loss * 0.58, 1),
                "sc_time_saved_s": round(theoretical_pit_loss * 0.42, 1),
                "strategic_impact": "Under a Safety Car, a 'cheap pit stop' saves ~42% of pit loss time, favoring multi-stop aggressiveness."
            },
            "historical_race_precedent": None,
            "disclaimer": "Simulated estimates are calculated from standard circuit physics profiles. Import race data via the Data Ingestion tab to unlock empirical telemetry comparisons."
        }
