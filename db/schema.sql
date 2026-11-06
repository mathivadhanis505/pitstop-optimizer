-- ============================================================================
-- F1 Pitstop Optimizer - Relational Database Schema (PostgreSQL)
-- Academic DBMS Showcase: Relational Modeling, Integrity Constraints,
-- Partitioning, Materialized Views, and Audit Triggers
-- ============================================================================

DROP TABLE IF EXISTS ingestion_jobs CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS lap_telemetry CASCADE;
DROP TABLE IF EXISTS pit_boxes CASCADE;
DROP TABLE IF EXISTS pit_stops CASCADE;
DROP TABLE IF EXISTS plan_stints, strategy_plans, stints, results, races,
                     drivers, teams, compound_weather, weather_conditions,
                     tracks, compounds, countries CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_driver_championship CASCADE;
DROP VIEW IF EXISTS v_driver_roster CASCADE;
DROP VIEW IF EXISTS v_stint_summary CASCADE;
DROP VIEW IF EXISTS v_calendar CASCADE;

-- ----------------------------------------------------------------------------
-- 1. BASE ENTITIES
-- ----------------------------------------------------------------------------

CREATE TABLE countries (
    country_id SERIAL PRIMARY KEY,
    name       VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE tracks (
    track_id           SERIAL PRIMARY KEY,
    name               VARCHAR(80) NOT NULL UNIQUE,
    slug               VARCHAR(30) NOT NULL UNIQUE,
    country_id         INT NOT NULL REFERENCES countries(country_id),
    laps               INT NOT NULL CHECK (laps BETWEEN 30 AND 90),
    pit_loss_s         DOUBLE PRECISION NOT NULL CHECK (pit_loss_s > 0),
    deg_factor         DOUBLE PRECISION NOT NULL CHECK (deg_factor > 0),
    overtake_penalty_s DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (overtake_penalty_s >= 0)
);

CREATE TABLE compounds (
    compound_id   SERIAL PRIMARY KEY,
    name          VARCHAR(10) NOT NULL UNIQUE,
    hardness_rank INT NOT NULL UNIQUE,
    colour_hex    CHAR(7) NOT NULL,
    is_wet        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE weather_conditions (
    weather_id             SERIAL PRIMARY KEY,
    name                   VARCHAR(10) NOT NULL UNIQUE,
    description            VARCHAR(80) NOT NULL,
    min_stops              INT NOT NULL CHECK (min_stops BETWEEN 0 AND 3),
    requires_two_compounds BOOLEAN NOT NULL
);

-- M:N associative entity between compounds and weather conditions
CREATE TABLE compound_weather (
    compound_id    INT REFERENCES compounds(compound_id) ON DELETE CASCADE,
    weather_id     INT REFERENCES weather_conditions(weather_id) ON DELETE CASCADE,
    pace_offset_s  DOUBLE PRECISION NOT NULL,
    deg_per_lap_s  DOUBLE PRECISION NOT NULL CHECK (deg_per_lap_s > 0),
    base_life_laps INT NOT NULL CHECK (base_life_laps > 0),
    PRIMARY KEY (compound_id, weather_id)
);

CREATE TABLE teams (
    team_id SERIAL PRIMARY KEY,
    name    VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE drivers (
    driver_id SERIAL PRIMARY KEY,
    code      CHAR(3) NOT NULL UNIQUE,
    full_name VARCHAR(60) NOT NULL,
    team_id   INT REFERENCES teams(team_id) ON DELETE SET NULL
);

-- ----------------------------------------------------------------------------
-- 2. RACE CALENDAR, RESULTS & WEAK ENTITIES
-- ----------------------------------------------------------------------------

CREATE TABLE races (
    race_id   SERIAL PRIMARY KEY,
    season    INT NOT NULL,
    round_no  INT NOT NULL,
    track_id  INT NOT NULL REFERENCES tracks(track_id),
    race_date DATE NOT NULL,
    status    VARCHAR(10) NOT NULL DEFAULT 'scheduled'
              CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    UNIQUE (season, round_no)
);

-- M:N relationship between drivers and races. finish_pos IS NULL = DNF
CREATE TABLE results (
    race_id        INT REFERENCES races(race_id) ON DELETE CASCADE,
    driver_id      INT REFERENCES drivers(driver_id) ON DELETE CASCADE,
    grid_pos       INT CHECK (grid_pos BETWEEN 1 AND 24),
    finish_pos     INT CHECK (finish_pos BETWEEN 1 AND 24),
    points_awarded INT CHECK (points_awarded >= 0),
    PRIMARY KEY (race_id, driver_id)
);

-- Weak entity: identified by composite (race_id, driver_id) + stint_no
CREATE TABLE stints (
    race_id     INT,
    driver_id   INT,
    stint_no    INT CHECK (stint_no >= 1),
    compound_id INT NOT NULL REFERENCES compounds(compound_id),
    start_lap   INT NOT NULL CHECK (start_lap >= 1),
    end_lap     INT NOT NULL,
    PRIMARY KEY (race_id, driver_id, stint_no),
    FOREIGN KEY (race_id, driver_id) REFERENCES results(race_id, driver_id) ON DELETE CASCADE,
    CHECK (end_lap >= start_lap)
);

-- Explicit Pit Stop Entity (Detailed execution metrics per pit event)
CREATE TABLE pit_stops (
    pit_stop_id       SERIAL PRIMARY KEY,
    race_id           INT NOT NULL,
    driver_id         INT NOT NULL,
    stop_no           INT NOT NULL CHECK (stop_no >= 1),
    lap_no            INT NOT NULL CHECK (lap_no >= 1),
    pit_duration_s    DOUBLE PRECISION CHECK (pit_duration_s IS NULL OR pit_duration_s > 0),
    stationary_time_s DOUBLE PRECISION CHECK (stationary_time_s IS NULL OR stationary_time_s > 0),
    tyre_fitted_id    INT REFERENCES compounds(compound_id),
    crew_penalty_s    DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (crew_penalty_s >= 0),
    FOREIGN KEY (race_id, driver_id) REFERENCES results(race_id, driver_id) ON DELETE CASCADE,
    UNIQUE (race_id, driver_id, stop_no)
);

-- ----------------------------------------------------------------------------
-- 3. STRATEGY PLANNING SYSTEM
-- ----------------------------------------------------------------------------

CREATE TABLE strategy_plans (
    plan_id    SERIAL PRIMARY KEY,
    track_id   INT NOT NULL REFERENCES tracks(track_id),
    weather_id INT NOT NULL REFERENCES weather_conditions(weather_id),
    stops      INT NOT NULL CHECK (stops BETWEEN 0 AND 4),
    delta_s    DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Weak entity: identified by plan_id + stint_no
CREATE TABLE plan_stints (
    plan_id     INT REFERENCES strategy_plans(plan_id) ON DELETE CASCADE,
    stint_no    INT CHECK (stint_no >= 1),
    compound_id INT NOT NULL REFERENCES compounds(compound_id),
    stint_laps  INT NOT NULL CHECK (stint_laps > 0),
    PRIMARY KEY (plan_id, stint_no)
);

-- ----------------------------------------------------------------------------
-- 4. CONCURRENCY & RESOURCE ALLOCATION (Pit Box Locking)
-- ----------------------------------------------------------------------------

CREATE TABLE pit_boxes (
    team_id      INT PRIMARY KEY REFERENCES teams(team_id) ON DELETE CASCADE,
    box_number   INT NOT NULL UNIQUE,
    is_occupied  BOOLEAN NOT NULL DEFAULT FALSE,
    current_car  INT REFERENCES drivers(driver_id) ON DELETE SET NULL,
    last_service TIMESTAMP DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- 5. TABLE PARTITIONING DEMONSTRATION (Lap-by-Lap Telemetry)
-- ----------------------------------------------------------------------------

CREATE TABLE lap_telemetry (
    race_id       INT NOT NULL,
    driver_id     INT NOT NULL,
    lap_no        INT NOT NULL,
    lap_time_s    DOUBLE PRECISION CHECK (lap_time_s IS NULL OR lap_time_s > 0),
    sector1_s     DOUBLE PRECISION CHECK (sector1_s IS NULL OR sector1_s > 0),
    sector2_s     DOUBLE PRECISION CHECK (sector2_s IS NULL OR sector2_s > 0),
    sector3_s     DOUBLE PRECISION CHECK (sector3_s IS NULL OR sector3_s > 0),
    tyre_age_laps INT NOT NULL CHECK (tyre_age_laps >= 0),
    position      INT CHECK (position IS NULL OR (position BETWEEN 1 AND 24)),
    compound_id   INT REFERENCES compounds(compound_id),
    is_pit_lap    BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (race_id, driver_id, lap_no)
) PARTITION BY RANGE (race_id);

CREATE TABLE lap_telemetry_r1_to_r10 PARTITION OF lap_telemetry
    FOR VALUES FROM (1) TO (11);

CREATE TABLE lap_telemetry_r11_to_r20 PARTITION OF lap_telemetry
    FOR VALUES FROM (11) TO (21);

CREATE TABLE lap_telemetry_r21_to_r30 PARTITION OF lap_telemetry
    FOR VALUES FROM (21) TO (31);

CREATE TABLE lap_telemetry_default PARTITION OF lap_telemetry DEFAULT;

-- Ingestion Status Tracking Table
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id          SERIAL PRIMARY KEY,
    season          INT NOT NULL,
    round_no        INT,
    session_type    VARCHAR(10) NOT NULL DEFAULT 'R',
    status          VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    laps_imported   INT NOT NULL DEFAULT 0,
    stints_imported INT NOT NULL DEFAULT 0,
    stops_imported  INT NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMP NOT NULL DEFAULT clock_timestamp(),
    finished_at     TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 6. AUDIT TRAIL / CHANGE DATA CAPTURE (CDC)
-- ----------------------------------------------------------------------------

CREATE TABLE audit_log (
    audit_id    SERIAL PRIMARY KEY,
    table_name  VARCHAR(50) NOT NULL,
    action_type VARCHAR(10) NOT NULL CHECK (action_type IN ('INSERT', 'UPDATE', 'DELETE')),
    record_id   TEXT NOT NULL,
    old_data    JSONB,
    new_data    JSONB,
    changed_by  VARCHAR(50) DEFAULT CURRENT_USER,
    changed_at  TIMESTAMP NOT NULL DEFAULT clock_timestamp()
);

-- ----------------------------------------------------------------------------
-- 7. INDEXING STRATEGY (B-Tree, Partial, Composite, Expression)
-- ----------------------------------------------------------------------------

-- Standard B-Tree Indexes
CREATE INDEX idx_races_track          ON races(track_id);
CREATE INDEX idx_results_driver       ON results(driver_id);
CREATE INDEX idx_stints_compound      ON stints(compound_id);
CREATE INDEX idx_cw_weather           ON compound_weather(weather_id);

-- Composite Index (Accelerates driver race lookups)
CREATE INDEX idx_pit_stops_driver_race ON pit_stops(race_id, driver_id);
CREATE INDEX idx_stints_race_driver   ON stints(race_id, driver_id);

-- Partial Index (Only index pending/scheduled races for quick calendar lookups)
CREATE INDEX idx_races_scheduled      ON races(race_date) WHERE status = 'scheduled';

-- Expression / Functional Index (Case-insensitive slug search)
CREATE INDEX idx_tracks_slug_lower    ON tracks (LOWER(slug));

-- Telemetry analytical index
CREATE INDEX idx_telemetry_laptime       ON lap_telemetry (lap_time_s);
CREATE INDEX idx_telemetry_race_driver   ON lap_telemetry (race_id, driver_id);
CREATE INDEX idx_telemetry_driver_lap    ON lap_telemetry (driver_id, lap_no);
CREATE INDEX idx_telemetry_compound      ON lap_telemetry (compound_id);
CREATE INDEX idx_telemetry_tyre_age      ON lap_telemetry (compound_id, tyre_age_laps);

-- ----------------------------------------------------------------------------
-- 8. STANDARD & MATERIALIZED VIEWS
-- ----------------------------------------------------------------------------

-- Standard View 1: Calendar & Track details
CREATE VIEW v_calendar AS
SELECT r.round_no, r.race_date, r.status, t.track_id, t.slug,
       t.name AS track, c.name AS country
FROM races r
JOIN tracks t ON t.track_id = r.track_id
JOIN countries c ON c.country_id = t.country_id
ORDER BY r.round_no;

-- Standard View 2: Stint Summary
CREATE VIEW v_stint_summary AS
SELECT ra.race_id, tr.name AS track, d.code AS driver, s.stint_no,
       cp.name AS compound, s.start_lap, s.end_lap,
       (s.end_lap - s.start_lap + 1) AS stint_laps
FROM stints s
JOIN results rs   ON rs.race_id = s.race_id AND rs.driver_id = s.driver_id
JOIN races ra     ON ra.race_id = rs.race_id
JOIN tracks tr    ON tr.track_id = ra.track_id
JOIN drivers d    ON d.driver_id = rs.driver_id
JOIN compounds cp ON cp.compound_id = s.compound_id;

-- Updatable View 3: Driver Roster (Supports INSTEAD OF Triggers)
CREATE VIEW v_driver_roster AS
SELECT d.driver_id, d.code, d.full_name, tm.team_id, tm.name AS team_name
FROM drivers d
LEFT JOIN teams tm ON tm.team_id = d.team_id;

-- Materialized View: Driver Championship Standings with Window Rankings partitioned by Season
CREATE MATERIALIZED VIEW mv_driver_championship AS
SELECT r.season, d.driver_id, d.code, d.full_name, tm.name AS team,
       COUNT(r.race_id) FILTER (WHERE res.finish_pos = 1) AS wins,
       COUNT(r.race_id) FILTER (WHERE res.finish_pos <= 3) AS podiums,
       COUNT(r.race_id) FILTER (WHERE res.finish_pos IS NOT NULL) AS finishes,
       COALESCE(SUM(COALESCE(res.points_awarded, CASE 
           WHEN res.finish_pos = 1 THEN 25
           WHEN res.finish_pos = 2 THEN 18
           WHEN res.finish_pos = 3 THEN 15
           WHEN res.finish_pos = 4 THEN 12
           WHEN res.finish_pos = 5 THEN 10
           WHEN res.finish_pos = 6 THEN 8
           WHEN res.finish_pos = 7 THEN 6
           WHEN res.finish_pos = 8 THEN 4
           WHEN res.finish_pos = 9 THEN 2
           WHEN res.finish_pos = 10 THEN 1
           ELSE 0 END)), 0) AS total_points,
       ROW_NUMBER() OVER (
           PARTITION BY r.season 
           ORDER BY 
               COALESCE(SUM(COALESCE(res.points_awarded, CASE 
                   WHEN res.finish_pos = 1 THEN 25
                   WHEN res.finish_pos = 2 THEN 18
                   WHEN res.finish_pos = 3 THEN 15
                   WHEN res.finish_pos = 4 THEN 12
                   WHEN res.finish_pos = 5 THEN 10
                   WHEN res.finish_pos = 6 THEN 8
                   WHEN res.finish_pos = 7 THEN 6
                   WHEN res.finish_pos = 8 THEN 4
                   WHEN res.finish_pos = 9 THEN 2
                   WHEN res.finish_pos = 10 THEN 1
                   ELSE 0 END)), 0) DESC,
               COUNT(r.race_id) FILTER (WHERE res.finish_pos = 1) DESC,
               COUNT(r.race_id) FILTER (WHERE res.finish_pos <= 3) DESC,
               COUNT(r.race_id) FILTER (WHERE res.finish_pos IS NOT NULL) DESC,
               d.driver_id ASC
       ) AS championship_rank
FROM results res
JOIN races r ON r.race_id = res.race_id
JOIN drivers d ON d.driver_id = res.driver_id
LEFT JOIN teams tm ON tm.team_id = d.team_id
GROUP BY r.season, d.driver_id, d.code, d.full_name, tm.name;

CREATE UNIQUE INDEX idx_mv_driver_champ_pk ON mv_driver_championship(season, driver_id);

-- ----------------------------------------------------------------------------
-- 9. ASSERTION SUBSTITUTE / DEFERRED CONSTRAINT TRIGGER
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION check_plan_laps() RETURNS trigger AS $$
DECLARE
    total INT;
    need  INT;
BEGIN
    SELECT COALESCE(SUM(stint_laps), 0) INTO total FROM plan_stints WHERE plan_id = NEW.plan_id;
    SELECT t.laps INTO need
    FROM strategy_plans p JOIN tracks t ON t.track_id = p.track_id
    WHERE p.plan_id = NEW.plan_id;
    IF total <> need THEN
        RAISE EXCEPTION 'Plan % stint laps (%) do not equal race laps (%)',
                        NEW.plan_id, total, need;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_plan_laps
AFTER INSERT ON plan_stints
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION check_plan_laps();
