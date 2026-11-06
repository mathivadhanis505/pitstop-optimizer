import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import engine
from .strategy import build_response, get_empirical_metrics, get_driver_metrics, optimize_driver_strategy
from .data_ingestion.importer import DatabaseImporter

app = FastAPI(
    title="Pitstop Optimizer",
    description="F1 Pit Stop Strategy Engine & DBMS Project",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def rows(conn, sql, params=None):
    return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]


def check_track(conn, track_id: int):
    found = conn.execute(text("SELECT 1 FROM tracks WHERE track_id = :id"), {"id": track_id}).first()
    if not found:
        raise HTTPException(404, "Track not found")


def get_weather_id(conn, name: str):
    wid = conn.execute(
        text("SELECT weather_id FROM weather_conditions WHERE name = :n"),
        {"n": name.upper()}
    ).scalar()
    if wid is None:
        raise HTTPException(400, "Unknown weather. Use DRY, DAMP or WET")
    return wid


# -----------------------------------------------------------------------------
# CORE DOMAIN & STRATEGY ENDPOINTS
# -----------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/health")
def health_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "degraded", "database": "offline", "error": str(e)}


@app.get("/tracks")
def list_tracks():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT t.track_id, t.slug, t.name, c.name AS country, t.laps,
                   t.pit_loss_s, t.deg_factor, t.overtake_penalty_s
            FROM tracks t JOIN countries c ON c.country_id = t.country_id
            WHERE NOT EXISTS (SELECT 1 FROM races r
                              WHERE r.track_id = t.track_id AND r.status = 'cancelled')
            ORDER BY t.track_id""")


@app.get("/tracks/{track_id}")
def track_detail(track_id: int):
    with engine.connect() as conn:
        data = rows(conn, """
            SELECT t.track_id, t.slug, t.name, c.name AS country, t.laps,
                   t.pit_loss_s, t.deg_factor, t.overtake_penalty_s
            FROM tracks t JOIN countries c ON c.country_id = t.country_id
            WHERE t.track_id = :id""", {"id": track_id})
    if not data:
        raise HTTPException(404, "Track not found")
    return data[0]


@app.get("/weather")
def list_weather():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT w.weather_id, w.name, w.description, w.min_stops,
                   json_agg(json_build_object('name', c.name, 'colour', c.colour_hex)
                            ORDER BY c.hardness_rank) AS compounds
            FROM weather_conditions w
            JOIN compound_weather cw ON cw.weather_id = w.weather_id
            JOIN compounds c         ON c.compound_id = cw.compound_id
            GROUP BY w.weather_id, w.name, w.description, w.min_stops
            ORDER BY w.weather_id""")


@app.get("/calendar")
def calendar():
    with engine.connect() as conn:
        return rows(conn, "SELECT * FROM v_calendar")


@app.get("/drivers")
def get_drivers():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT d.driver_id, d.code, d.full_name, COALESCE(tm.name, 'Independent') AS team
            FROM drivers d
            LEFT JOIN teams tm ON tm.team_id = d.team_id
            WHERE d.code != 'RES'
            ORDER BY d.code
        """)


@app.get("/strategy/{track_id}")
def get_strategy(
    track_id: int,
    weather: str = "DRY",
    driver_code: Optional[str] = None,
    season: Optional[int] = None,
    starting_compound: Optional[str] = None,
    max_stops: Optional[int] = None,
    safety_car: Optional[str] = "NONE"
):
    with engine.connect() as conn:
        check_track(conn, track_id)
        wid = get_weather_id(conn, weather)
        raw_data = rows(conn, "SELECT * FROM plan_strategies(:t, :w)", {"t": track_id, "w": wid})
        
        try:
            empirical_ctx = get_empirical_metrics(conn, track_id)
        except Exception:
            empirical_ctx = None

        driver_profile = None
        if driver_code:
            try:
                driver_profile = get_driver_metrics(conn, track_id, driver_code)
            except Exception:
                driver_profile = None

        optimized_data = optimize_driver_strategy(
            conn=conn,
            track_id=track_id,
            raw_strategies=raw_data,
            driver_code=driver_code,
            driver_profile=driver_profile,
            starting_compound=starting_compound,
            max_stops=max_stops,
            safety_car=safety_car
        )

    return build_response(optimized_data, empirical_context=empirical_ctx, driver_profile=driver_profile)


@app.post("/strategy/{track_id}/save")
def save_best(track_id: int, weather: str = "DRY"):
    with engine.begin() as conn:
        check_track(conn, track_id)
        wid = get_weather_id(conn, weather)
        data = rows(conn, """
            SELECT * FROM plan_strategies(:t, :w)
            WHERE feasible ORDER BY rnk LIMIT 1""", {"t": track_id, "w": wid})
        if not data:
            raise HTTPException(409, "No viable strategy for these conditions")
        best = data[0]
        plan_id = conn.execute(text("""
            INSERT INTO strategy_plans (track_id, weather_id, stops)
            VALUES (:t, :w, :s) RETURNING plan_id"""),
            {"t": track_id, "w": wid, "s": best["stops"]}).scalar()

        names = best["compounds"].split(" > ")
        for n, (comp, laps) in enumerate(zip(names, best["stint_laps"]), start=1):
            conn.execute(text("""
                INSERT INTO plan_stints (plan_id, stint_no, compound_id, stint_laps)
                VALUES (:p, :n, (SELECT compound_id FROM compounds WHERE name = :c), :l)"""),
                {"p": plan_id, "n": n, "c": comp, "l": laps})

    return {"saved_plan_id": plan_id}


@app.get("/plans")
def saved_plans():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT p.plan_id, t.name AS track, w.name AS weather, p.stops, p.delta_s,
                   string_agg(c.name, ' > ' ORDER BY ps.stint_no) AS compounds,
                   p.created_at
            FROM strategy_plans p
            JOIN tracks t              ON t.track_id = p.track_id
            JOIN weather_conditions w  ON w.weather_id = p.weather_id
            JOIN plan_stints ps        ON ps.plan_id = p.plan_id
            JOIN compounds c           ON c.compound_id = ps.compound_id
            GROUP BY p.plan_id, t.name, w.name, p.stops, p.delta_s, p.created_at
            ORDER BY p.plan_id DESC""")


# -----------------------------------------------------------------------------
# ACADEMIC DBMS SHOWCASE ENDPOINTS
# -----------------------------------------------------------------------------

ACADEMIC_QUERIES = [
    {
        "id": 1,
        "title": "3-Table Inner Join with Projection",
        "category": "Relational Joins",
        "description": "Joins races, tracks, and countries to produce the 2026 race calendar.",
        "sql": """SELECT r.round_no, t.name AS track, c.name AS country, r.race_date, r.status
FROM races r
JOIN tracks t ON t.track_id = r.track_id
JOIN countries c ON c.country_id = t.country_id
ORDER BY r.round_no LIMIT 10;"""
    },
    {
        "id": 2,
        "title": "Left Outer Join with NULL Replacement",
        "category": "Relational Joins",
        "description": "Preserves reserve drivers without assigned teams using LEFT JOIN and COALESCE.",
        "sql": """SELECT d.code, d.full_name, COALESCE(tm.name, 'Independent / Reserve') AS team
FROM drivers d 
LEFT JOIN teams tm ON tm.team_id = d.team_id;"""
    },
    {
        "id": 3,
        "title": "Aggregation with GROUP BY & HAVING",
        "category": "Aggregation",
        "description": "Groups tracks by host country and filters aggregates using HAVING clause.",
        "sql": """SELECT c.name AS country, 
       COUNT(t.track_id) AS track_count,
       ROUND(AVG(t.pit_loss_s)::numeric, 2) AS avg_pit_loss_s,
       ROUND(AVG(t.laps)::numeric, 1) AS avg_laps
FROM tracks t 
JOIN countries c ON c.country_id = t.country_id
GROUP BY c.name 
HAVING COUNT(t.track_id) >= 1
ORDER BY track_count DESC, avg_pit_loss_s DESC LIMIT 8;"""
    },
    {
        "id": 4,
        "title": "Nested Scalar Subquery",
        "category": "Subqueries",
        "description": "Filters tracks having pit stop time loss strictly greater than the global average.",
        "sql": """SELECT name, pit_loss_s, deg_factor 
FROM tracks
WHERE pit_loss_s > (SELECT AVG(pit_loss_s) FROM tracks)
ORDER BY pit_loss_s DESC;"""
    },
    {
        "id": 5,
        "title": "Existential Quantification (EXISTS)",
        "category": "Subqueries",
        "description": "Uses EXISTS semi-join to find circuits that have successfully hosted completed races.",
        "sql": """SELECT t.name, t.laps 
FROM tracks t
WHERE EXISTS (
    SELECT 1 FROM races r
    WHERE r.track_id = t.track_id AND r.status = 'completed'
) LIMIT 8;"""
    },
    {
        "id": 6,
        "title": "Correlated Subquery",
        "category": "Subqueries",
        "description": "Evaluates track lap count against the dynamic average of tracks in that same country.",
        "sql": """SELECT t.name, t.laps, c.name AS country
FROM tracks t
JOIN countries c ON c.country_id = t.country_id
WHERE t.laps >= (
    SELECT AVG(t2.laps) 
    FROM tracks t2 
    WHERE t2.country_id = t.country_id
) LIMIT 8;"""
    },
    {
        "id": 7,
        "title": "Set Operations (INTERSECT & EXCEPT)",
        "category": "Set Operations",
        "description": "Applies relational set intersection to find tracks with high wear and overtaking ease.",
        "sql": """SELECT name FROM tracks WHERE deg_factor >= 1.1
INTERSECT
SELECT name FROM tracks WHERE overtake_penalty_s = 0;"""
    },
    {
        "id": 8,
        "title": "Three-Valued Logic & DNF Analysis",
        "category": "Relational Theory",
        "description": "Demonstrates SQL three-valued logic (NULL handling) for unclassified retirements.",
        "sql": """SELECT d.code, d.full_name, r.grid_pos, 
       CASE WHEN r.finish_pos IS NULL THEN 'DNF (Did Not Finish)' ELSE r.finish_pos::TEXT END AS status
FROM results r
JOIN drivers d ON d.driver_id = r.driver_id
WHERE r.race_id = 15;"""
    },
    {
        "id": 9,
        "title": "Self Join (Paired Entities)",
        "category": "Relational Joins",
        "description": "Pairs distinct Formula 1 circuits situated inside the same host country.",
        "sql": """SELECT a.name AS circuit_1, b.name AS circuit_2, c.name AS country
FROM tracks a
JOIN tracks b ON a.country_id = b.country_id AND a.track_id < b.track_id
JOIN countries c ON c.country_id = a.country_id;"""
    },
    {
        "id": 10,
        "title": "Relational View Querying (v_stint_summary)",
        "category": "Views",
        "description": "Queries the predefined relational view encapsulating 5 base tables.",
        "sql": """SELECT track, driver, stint_no, compound, stint_laps 
FROM v_stint_summary 
WHERE track = 'Monza' 
ORDER BY driver, stint_no;"""
    },
    {
        "id": 11,
        "title": "Relational Division (Universal Quantifier)",
        "category": "Relational Theory",
        "description": "Finds drivers who utilized ALL available dry compounds (SOFT, MEDIUM, HARD) via double NOT EXISTS.",
        "sql": """SELECT d.driver_id, d.code, d.full_name 
FROM drivers d
WHERE NOT EXISTS (
    SELECT 1 FROM compounds c
    WHERE c.is_wet = FALSE 
      AND NOT EXISTS (
        SELECT 1 FROM stints s
        WHERE s.driver_id = d.driver_id 
          AND s.compound_id = c.compound_id
    )
);"""
    },
    {
        "id": 12,
        "title": "Window Functions (LAG & Partitioned Pace)",
        "category": "Advanced Analytics",
        "description": "Computes lap-to-lap pace degradation using LAG() and moving partitioned averages.",
        "sql": """SELECT driver_id, lap_no, lap_time_s,
       LAG(lap_time_s, 1) OVER (PARTITION BY driver_id ORDER BY lap_no) AS prev_lap_s,
       ROUND((lap_time_s - LAG(lap_time_s, 1) OVER (PARTITION BY driver_id ORDER BY lap_no))::numeric, 2) AS delta_s,
       ROUND(AVG(lap_time_s) OVER (PARTITION BY driver_id)::numeric, 2) AS driver_mean_pace
FROM lap_telemetry
WHERE race_id = 15 LIMIT 10;"""
    },
    {
        "id": 13,
        "title": "Materialized View Standings (mv_driver_championship)",
        "category": "Performance Views",
        "description": "Inspects the indexed materialized view computing driver championship points and rank.",
        "sql": """SELECT championship_rank, code, full_name, team, wins, podiums, total_points
FROM mv_driver_championship
ORDER BY championship_rank;"""
    },
    {
        "id": 14,
        "title": "Explicit Pit Stop Stationary Telemetry",
        "category": "Domain Analytics",
        "description": "Analyzes wheel-gun stationary duration and crew efficiency from the pit_stops entity.",
        "sql": """SELECT d.code AS driver, tm.name AS team, ps.stop_no, ps.lap_no,
       ps.stationary_time_s, ps.pit_duration_s, c.name AS fitted_compound
FROM pit_stops ps
JOIN drivers d ON d.driver_id = ps.driver_id
LEFT JOIN teams tm ON tm.team_id = d.team_id
JOIN compounds c ON c.compound_id = ps.tyre_fitted_id
ORDER BY ps.stationary_time_s ASC;"""
    },
    {
        "id": 15,
        "title": "Table Partition Pruning Inspection",
        "category": "Physical Optimization",
        "description": "Demonstrates partition pruning on partitioned lap_telemetry table for Race 15.",
        "sql": """SELECT race_id, driver_id, lap_no, lap_time_s
FROM lap_telemetry
WHERE race_id = 15 AND lap_no >= 20;"""
    },
    {
        "id": 16,
        "title": "Audit Trail Inspection (Change Data Capture)",
        "category": "Security & Triggers",
        "description": "Reads row-level audit changes captured automatically by PL/pgSQL triggers.",
        "sql": """SELECT audit_id, table_name, action_type, record_id,
       new_data->>'stops' AS stops, changed_by, changed_at
FROM audit_log
ORDER BY changed_at DESC LIMIT 10;"""
    },
    {
        "id": 17,
        "title": "Recursive CTE Strategy Evaluation",
        "category": "Hierarchical Queries",
        "description": "Executes the recursive plan_strategies(track, weather) CTE to evaluate state-space pit combinations.",
        "sql": """SELECT stops, compounds, stint_laps, total_s, delta_s, rnk
FROM plan_strategies(13, 1)
LIMIT 6;"""
    },
    {
        "id": 18,
        "title": "Three-Valued Logic Aggregation (Nullability & DNF)",
        "category": "Relational Theory",
        "description": "Measures completion ratios, classified finishers, and NULL finish positions across results.",
        "sql": """SELECT COUNT(*) AS total_entrants, 
       COUNT(finish_pos) AS classified_finishers,
       COUNT(*) - COUNT(finish_pos) AS dnf_count
FROM results;"""
    },
    {
        "id": 19,
        "title": "Relational Set Operations (UNION of Outliers)",
        "category": "Set Operations",
        "description": "Unions distinct high-distance circuits with extreme pit-lane penalty venues.",
        "sql": """SELECT name, 'High Lap Distance' AS category, laps AS value FROM tracks WHERE laps >= 70
UNION
SELECT name, 'High Pit Lane Loss' AS category, pit_loss_s AS value FROM tracks WHERE pit_loss_s >= 24;"""
    },
    {
        "id": 20,
        "title": "Correlated Track Distance vs Country Averages",
        "category": "Subqueries",
        "description": "Calculates each circuit lap count against the correlated average of all tracks in the same nation.",
        "sql": """SELECT t.name, t.laps, c.name AS country,
       (SELECT ROUND(AVG(t2.laps)::numeric, 1) FROM tracks t2 WHERE t2.country_id = t.country_id) AS country_avg_laps
FROM tracks t
JOIN countries c ON c.country_id = t.country_id
ORDER BY t.laps DESC LIMIT 10;"""
    }
]


@app.get("/academic/queries")
def list_academic_queries():
    return ACADEMIC_QUERIES


@app.post("/academic/query/{query_id}/run")
def execute_academic_query(query_id: int):
    q_meta = next((q for q in ACADEMIC_QUERIES if q["id"] == query_id), None)
    if not q_meta:
        raise HTTPException(404, "Academic query not found")

    start_time = time.time()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(q_meta["sql"]))
            columns = list(result.keys())
            data = [dict(r._mapping) for r in result]
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            return {
                "id": q_meta["id"],
                "title": q_meta["title"],
                "category": q_meta["category"],
                "sql": q_meta["sql"],
                "execution_time_ms": elapsed_ms,
                "row_count": len(data),
                "columns": columns,
                "rows": data
            }
    except SQLAlchemyError as err:
        raise HTTPException(500, f"Database error executing query #{query_id}: {str(err)}")


@app.get("/academic/explain")
def explain_query(sql: Optional[str] = None):
    target_sql = sql or "SELECT * FROM tracks WHERE pit_loss_s > 22.0;"
    try:
        with engine.connect() as conn:
            plan_rows = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE) {target_sql}")).fetchall()
            lines = [r[0] for r in plan_rows]
            return {
                "target_sql": target_sql,
                "plan_text": "\n".join(lines),
                "lines": lines
            }
    except SQLAlchemyError as err:
        raise HTTPException(500, f"Explain error: {str(err)}")


@app.get("/academic/audit-log")
def get_audit_trail():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT audit_id, table_name, action_type, record_id,
                   old_data, new_data, changed_by, changed_at
            FROM audit_log
            ORDER BY changed_at DESC LIMIT 50""")


class AuditSimulateRequest(BaseModel):
    action: str = "INSERT"  # "INSERT", "UPDATE", "DELETE"
    track_id: Optional[int] = 13  # Monza
    stops: Optional[int] = 2


@app.post("/academic/audit/simulate")
def simulate_audit_event(req: AuditSimulateRequest):
    """
    Directly exercises the PostgreSQL PL/pgSQL audit trigger trg_audit_plans
    on strategy_plans to demonstrate Change Data Capture (CDC) in real time.
    """
    act = req.action.upper()
    with engine.begin() as conn:
        if act == "INSERT":
            res = conn.execute(text("""
                INSERT INTO strategy_plans (track_id, weather_id, stops, delta_s)
                VALUES (:t, 1, :s, 0.0)
                RETURNING plan_id;
            """), {"t": req.track_id or 13, "s": req.stops or 2})
            new_id = res.scalar()
            return {
                "status": "success",
                "action": "INSERT",
                "record_id": str(new_id),
                "message": f"INSERT on strategy_plans (plan_id={new_id}) fired trg_audit_plans trigger -> logged into audit_log."
            }
        elif act == "UPDATE":
            latest = conn.execute(text("SELECT plan_id, delta_s FROM strategy_plans ORDER BY plan_id DESC LIMIT 1")).mappings().first()
            if not latest:
                raise HTTPException(404, "No strategy plans available to update. Please trigger an INSERT first.")
            new_delta = round((latest["delta_s"] or 0.0) + 1.25, 2)
            conn.execute(text("""
                UPDATE strategy_plans SET delta_s = :d WHERE plan_id = :p
            """), {"d": new_delta, "p": latest["plan_id"]})
            return {
                "status": "success",
                "action": "UPDATE",
                "record_id": str(latest["plan_id"]),
                "message": f"UPDATE on strategy_plans (plan_id={latest['plan_id']}) fired trg_audit_plans -> captured old and new JSONB states in audit_log."
            }
        elif act == "DELETE":
            latest = conn.execute(text("SELECT plan_id FROM strategy_plans ORDER BY plan_id DESC LIMIT 1")).mappings().first()
            if not latest:
                raise HTTPException(404, "No strategy plans available to delete.")
            conn.execute(text("DELETE FROM plan_stints WHERE plan_id = :p"), {"p": latest["plan_id"]})
            conn.execute(text("DELETE FROM strategy_plans WHERE plan_id = :p"), {"p": latest["plan_id"]})
            return {
                "status": "success",
                "action": "DELETE",
                "record_id": str(latest["plan_id"]),
                "message": f"DELETE on strategy_plans (plan_id={latest['plan_id']}) fired trg_audit_plans -> archived historical state into audit_log."
            }
        else:
            raise HTTPException(400, "Invalid action. Use INSERT, UPDATE, or DELETE.")


@app.get("/academic/championship")
def get_championship_standings(season: Optional[int] = None):
    try:
        with engine.connect() as conn:
            if season:
                data = rows(conn, "SELECT * FROM mv_driver_championship WHERE season = :s ORDER BY championship_rank", {"s": season})
            else:
                data = rows(conn, "SELECT * FROM mv_driver_championship ORDER BY season DESC, championship_rank")

            if data and all(r.get("total_points", 0) == 0 for r in data):
                try:
                    with engine.begin() as refresh_conn:
                        refresh_conn.execute(text("REFRESH MATERIALIZED VIEW mv_driver_championship;"))
                    if season:
                        data = rows(conn, "SELECT * FROM mv_driver_championship WHERE season = :s ORDER BY championship_rank", {"s": season})
                    else:
                        data = rows(conn, "SELECT * FROM mv_driver_championship ORDER BY season DESC, championship_rank")
                except Exception:
                    pass
            return data
    except Exception as e:
        raise HTTPException(500, f"Error querying championship standings: {str(e)}")


@app.post("/academic/refresh-mview")
def refresh_championship_standings():
    start = time.time()
    with engine.begin() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW mv_driver_championship;"))
    elapsed_ms = round((time.time() - start) * 1000, 2)
    return {"message": "Materialized view refreshed successfully", "duration_ms": elapsed_ms}


@app.post("/academic/safety-car-procedure")
def call_safety_car_procedure(plan_id: int = Query(..., description="Target plan ID"),
                              discount_pct: float = Query(50.0, description="Pit time discount %")):
    with engine.begin() as conn:
        # Check plan
        plan = conn.execute(text("SELECT delta_s, track_id FROM strategy_plans WHERE plan_id = :p"), {"p": plan_id}).first()
        if not plan:
            raise HTTPException(404, "Strategy plan not found")
        old_delta = plan[0]
        track = conn.execute(text("SELECT pit_loss_s, name FROM tracks WHERE track_id = :t"), {"t": plan[1]}).first()
        pit_loss = track[0] if track and track[0] is not None else 20.0
        time_saved = round(pit_loss * (discount_pct / 100.0), 2)
        
        # Call procedure
        conn.execute(text("CALL sp_apply_safety_car(:p, :d, NULL, NULL)"), {"p": plan_id, "d": discount_pct})
        updated = conn.execute(text("SELECT delta_s FROM strategy_plans WHERE plan_id = :p"), {"p": plan_id}).first()
    return {
        "plan_id": plan_id,
        "track_name": track[1] if track else "Unknown",
        "nominal_pit_loss_s": pit_loss,
        "old_delta_s": old_delta,
        "new_delta_s": updated[0],
        "time_saved_s": time_saved,
        "discount_pct": discount_pct,
        "message": f"Safety Car deployed: Pit loss reduced by {discount_pct}%, saving {time_saved}s."
    }



# -----------------------------------------------------------------------------
# REAL F1 TELEMETRY & HISTORICAL ANALYTICS ENDPOINTS
# -----------------------------------------------------------------------------

class IngestionRequest(BaseModel):
    season: int
    round_no: Optional[int] = None
    max_rounds: Optional[int] = None


@app.get("/analytics/seasons")
def list_seasons():
    with engine.connect() as conn:
        data = rows(conn, "SELECT DISTINCT season FROM races ORDER BY season DESC;")
        return [r["season"] for r in data]


@app.get("/analytics/races")
def list_races(season: Optional[int] = None, has_telemetry_only: bool = False):
    with engine.connect() as conn:
        query = """
            SELECT r.race_id, r.season, r.round_no, r.race_date, r.status,
                   t.track_id, t.name AS track_name, c.name AS country,
                   (SELECT COUNT(*) FROM lap_telemetry lt WHERE lt.race_id = r.race_id) AS lap_count,
                   (SELECT COUNT(*) FROM pit_stops ps WHERE ps.race_id = r.race_id) AS pit_count
            FROM races r
            JOIN tracks t ON t.track_id = r.track_id
            JOIN countries c ON c.country_id = t.country_id
            WHERE (:s IS NULL OR r.season = :s)
        """
        if has_telemetry_only:
            query += " AND (SELECT COUNT(*) FROM lap_telemetry lt WHERE lt.race_id = r.race_id) > 0"
        query += " ORDER BY r.season DESC, r.round_no ASC;"
        return rows(conn, query, {"s": season})


@app.get("/analytics/drivers")
def list_drivers(race_id: Optional[int] = None):
    with engine.connect() as conn:
        return rows(conn, """
            SELECT DISTINCT d.driver_id, d.code, d.full_name, COALESCE(tm.name, 'Independent') AS team
            FROM drivers d
            LEFT JOIN teams tm ON tm.team_id = d.team_id
            JOIN results res ON res.driver_id = d.driver_id
            WHERE (:r IS NULL OR res.race_id = :r)
            ORDER BY d.code;
        """, {"r": race_id})


@app.get("/analytics/laps")
def list_laps(race_id: int, driver_code: Optional[str] = None):
    with engine.connect() as conn:
        return rows(conn, """
            SELECT lt.lap_no, d.code AS driver_code, d.full_name AS driver_name,
                   lt.lap_time_s, lt.sector1_s, lt.sector2_s, lt.sector3_s,
                   lt.tyre_age_laps, lt.is_pit_lap, c.name AS compound
            FROM lap_telemetry lt
            JOIN drivers d ON d.driver_id = lt.driver_id
            JOIN compounds c ON c.compound_id = lt.compound_id
            WHERE lt.race_id = :r AND (:d IS NULL OR d.code = :d)
            ORDER BY lt.lap_no, d.code;
        """, {"r": race_id, "d": driver_code})


@app.get("/analytics/driver-comparison")
def compare_drivers(race_id: int, driver1: str, driver2: str):
    with engine.connect() as conn:
        return rows(conn, """
            WITH d1 AS (
                SELECT lt.lap_no, lt.lap_time_s, lt.tyre_age_laps, c.name AS compound
                FROM lap_telemetry lt
                JOIN drivers d ON d.driver_id = lt.driver_id
                JOIN compounds c ON c.compound_id = lt.compound_id
                WHERE lt.race_id = :r AND d.code = :c1
            ),
            d2 AS (
                SELECT lt.lap_no, lt.lap_time_s, lt.tyre_age_laps, c.name AS compound
                FROM lap_telemetry lt
                JOIN drivers d ON d.driver_id = lt.driver_id
                JOIN compounds c ON c.compound_id = lt.compound_id
                WHERE lt.race_id = :r AND d.code = :c2
            )
            SELECT COALESCE(d1.lap_no, d2.lap_no) AS lap_no,
                   d1.lap_time_s AS d1_lap_time,
                   d1.compound AS d1_compound,
                   d1.tyre_age_laps AS d1_age,
                   d2.lap_time_s AS d2_lap_time,
                   d2.compound AS d2_compound,
                   d2.tyre_age_laps AS d2_age,
                   ROUND((d1.lap_time_s - d2.lap_time_s)::numeric, 3) AS delta_s
            FROM d1 FULL OUTER JOIN d2 ON d1.lap_no = d2.lap_no
            ORDER BY lap_no;
        """, {"r": race_id, "c1": driver1.upper(), "c2": driver2.upper()})


@app.get("/analytics/tyre-degradation")
def tyre_degradation(race_id: int):
    with engine.connect() as conn:
        return rows(conn, """
            SELECT c.name AS compound,
                   lt.tyre_age_laps,
                   ROUND(AVG(lt.lap_time_s)::numeric, 3) AS avg_lap_time,
                   ROUND(MIN(lt.lap_time_s)::numeric, 3) AS min_lap_time,
                   COUNT(*) AS lap_count
            FROM lap_telemetry lt
            JOIN compounds c ON c.compound_id = lt.compound_id
            WHERE lt.race_id = :r AND lt.is_pit_lap = FALSE AND lt.lap_time_s IS NOT NULL
            GROUP BY c.name, lt.tyre_age_laps
            ORDER BY c.name, lt.tyre_age_laps;
        """, {"r": race_id})


@app.get("/analytics/stints")
def list_stints(race_id: int):
    with engine.connect() as conn:
        return rows(conn, """
            SELECT s.stint_no, d.code AS driver, d.full_name, tm.name AS team,
                   c.name AS compound, s.start_lap, s.end_lap,
                   (s.end_lap - s.start_lap + 1) AS total_laps
            FROM stints s
            JOIN drivers d ON d.driver_id = s.driver_id
            LEFT JOIN teams tm ON tm.team_id = d.team_id
            JOIN compounds c ON c.compound_id = s.compound_id
            WHERE s.race_id = :r
            ORDER BY d.code, s.stint_no;
        """, {"r": race_id})


@app.get("/analytics/pit-stops")
def list_pit_stops(race_id: int):
    with engine.connect() as conn:
        return rows(conn, """
            SELECT ps.stop_no, ps.lap_no, d.code AS driver, tm.name AS team,
                   ps.pit_duration_s, ps.stationary_time_s
            FROM pit_stops ps
            JOIN drivers d ON d.driver_id = ps.driver_id
            LEFT JOIN teams tm ON tm.team_id = d.team_id
            WHERE ps.race_id = :r
            ORDER BY ps.lap_no, ps.stop_no;
        """, {"r": race_id})


@app.post("/analytics/import")
def trigger_data_import(req: IngestionRequest):
    importer = DatabaseImporter()
    try:
        if req.round_no is not None:
            res = importer.import_round(req.season, req.round_no)
            return {"status": "success", "result": res}
        else:
            res = importer.import_season(req.season, max_rounds=req.max_rounds)
            return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(500, f"Import failed: {str(e)}")


@app.get("/analytics/import/status")
def import_job_status():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT job_id, season, round_no, session_type, status,
                   laps_imported, stints_imported, stops_imported,
                   error_message, started_at, finished_at
            FROM ingestion_jobs
            ORDER BY started_at DESC LIMIT 20;
        """)


# Static UI mount
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
