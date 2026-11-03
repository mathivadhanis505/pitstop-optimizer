DROP TABLE IF EXISTS plan_stints, strategy_plans, stints, results, races,
                     drivers, teams, compound_weather, weather_conditions,
                     tracks, compounds, countries CASCADE;

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

-- M:N between compounds and weather, with attributes
CREATE TABLE compound_weather (
    compound_id    INT REFERENCES compounds(compound_id),
    weather_id     INT REFERENCES weather_conditions(weather_id),
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

CREATE TABLE races (
    race_id   SERIAL PRIMARY KEY,
    season    INT NOT NULL,
    round_no  INT NOT NULL,
    track_id  INT NOT NULL REFERENCES tracks(track_id),
    race_date DATE NOT NULL,
    status    VARCHAR(10) NOT NULL DEFAULT 'scheduled'
              CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    UNIQUE (season, round_no),
    UNIQUE (season, track_id)
);

-- M:N between drivers and races. finish_pos NULL = did not finish
CREATE TABLE results (
    race_id    INT REFERENCES races(race_id) ON DELETE CASCADE,
    driver_id  INT REFERENCES drivers(driver_id),
    grid_pos   INT CHECK (grid_pos BETWEEN 1 AND 24),
    finish_pos INT CHECK (finish_pos BETWEEN 1 AND 24),
    PRIMARY KEY (race_id, driver_id)
);

-- weak entity: identified by result key + stint_no
CREATE TABLE stints (
    race_id     INT,
    driver_id   INT,
    stint_no    INT,
    compound_id INT NOT NULL REFERENCES compounds(compound_id),
    start_lap   INT NOT NULL CHECK (start_lap >= 1),
    end_lap     INT NOT NULL,
    PRIMARY KEY (race_id, driver_id, stint_no),
    FOREIGN KEY (race_id, driver_id) REFERENCES results(race_id, driver_id) ON DELETE CASCADE,
    CHECK (end_lap >= start_lap)
);

CREATE TABLE strategy_plans (
    plan_id    SERIAL PRIMARY KEY,
    track_id   INT NOT NULL REFERENCES tracks(track_id),
    weather_id INT NOT NULL REFERENCES weather_conditions(weather_id),
    stops      INT NOT NULL CHECK (stops BETWEEN 0 AND 4),
    delta_s    DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- weak entity
CREATE TABLE plan_stints (
    plan_id     INT REFERENCES strategy_plans(plan_id) ON DELETE CASCADE,
    stint_no    INT,
    compound_id INT NOT NULL REFERENCES compounds(compound_id),
    stint_laps  INT NOT NULL CHECK (stint_laps > 0),
    PRIMARY KEY (plan_id, stint_no)
);

-- Indexes (B-tree). PK and UNIQUE columns already get one automatically
CREATE INDEX idx_races_track     ON races(track_id);
CREATE INDEX idx_results_driver  ON results(driver_id);
CREATE INDEX idx_stints_compound ON stints(compound_id);
CREATE INDEX idx_cw_weather      ON compound_weather(weather_id);

-- Views
CREATE VIEW v_calendar AS
SELECT r.round_no, r.race_date, r.status, t.track_id, t.slug,
       t.name AS track, c.name AS country
FROM races r
JOIN tracks t ON t.track_id = r.track_id
JOIN countries c ON c.country_id = t.country_id
ORDER BY r.round_no;

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

-- ASSERTION substitute: PostgreSQL has no CREATE ASSERTION.
-- Rule: a saved plan's stint laps must add up to the race distance (checked at COMMIT)
CREATE OR REPLACE FUNCTION check_plan_laps() RETURNS trigger AS $$
DECLARE
    total INT;
    need  INT;
BEGIN
    SELECT SUM(stint_laps) INTO total FROM plan_stints WHERE plan_id = NEW.plan_id;
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
