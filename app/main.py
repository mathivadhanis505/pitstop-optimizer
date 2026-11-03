from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .database import engine
from .strategy import build_response

app = FastAPI(title="F1 Pit Stop Strategy DSS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],   # a React dev server, if you add one later
    allow_methods=["*"],
    allow_headers=["*"],
)


def rows(conn, sql, params=None):
    return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]


def check_track(conn, track_id):
    found = conn.execute(text("SELECT 1 FROM tracks WHERE track_id = :id"),
                         {"id": track_id}).first()
    if not found:
        raise HTTPException(404, "Track not found")


def get_weather_id(conn, name):
    wid = conn.execute(text("SELECT weather_id FROM weather_conditions WHERE name = :n"),
                       {"n": name.upper()}).scalar()
    if wid is None:
        raise HTTPException(400, "Unknown weather. Use DRY, DAMP or WET")
    return wid


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/tracks")
def list_tracks():
    # only circuits that are not cancelled this season
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


@app.get("/strategy/{track_id}")
def get_strategy(track_id: int, weather: str = "DRY"):
    with engine.connect() as conn:
        check_track(conn, track_id)
        wid = get_weather_id(conn, weather)
        data = rows(conn, "SELECT * FROM plan_strategies(:t, :w)",
                    {"t": track_id, "w": wid})
    return build_response(data)


@app.post("/strategy/{track_id}/save")
def save_best(track_id: int, weather: str = "DRY"):
    # one transaction: commits on success, rolls back on any error
    with engine.begin() as conn:
        check_track(conn, track_id)
        wid = get_weather_id(conn, weather)
        data = rows(conn, "SELECT * FROM plan_strategies(:t, :w) "
                          "WHERE feasible ORDER BY rnk LIMIT 1",
                    {"t": track_id, "w": wid})
        if not data:
            raise HTTPException(409, "No viable strategy for these conditions")
        best = data[0]
        plan_id = conn.execute(text(
            "INSERT INTO strategy_plans (track_id, weather_id, stops) "
            "VALUES (:t, :w, :s) RETURNING plan_id"),
            {"t": track_id, "w": wid, "s": best["stops"]}).scalar()
        names = best["compounds"].split(" > ")
        for n, (comp, laps) in enumerate(zip(names, best["stint_laps"]), start=1):
            conn.execute(text(
                "INSERT INTO plan_stints (plan_id, stint_no, compound_id, stint_laps) "
                "VALUES (:p, :n, (SELECT compound_id FROM compounds WHERE name = :c), :l)"),
                {"p": plan_id, "n": n, "c": comp, "l": laps})
    return {"saved_plan_id": plan_id}


@app.get("/plans")
def saved_plans():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT p.plan_id, t.name AS track, w.name AS weather, p.stops,
                   string_agg(c.name, ' > ' ORDER BY ps.stint_no) AS compounds
            FROM strategy_plans p
            JOIN tracks t              ON t.track_id = p.track_id
            JOIN weather_conditions w  ON w.weather_id = p.weather_id
            JOIN plan_stints ps        ON ps.plan_id = p.plan_id
            JOIN compounds c           ON c.compound_id = ps.compound_id
            GROUP BY p.plan_id, t.name, w.name, p.stops
            ORDER BY p.plan_id""")


@app.get("/reports/compound-usage")
def compound_usage():
    with engine.connect() as conn:
        return rows(conn, """
            SELECT compound, COUNT(*) AS stints,
                   CAST(AVG(stint_laps) AS NUMERIC(5,1)) AS avg_stint_laps
            FROM v_stint_summary
            GROUP BY compound
            ORDER BY stints DESC""")


# simple web UI (plain HTML + JS) served at /ui/
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
