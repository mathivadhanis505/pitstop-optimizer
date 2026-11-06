-- ============================================================================
-- F1 Pitstop Optimizer - Database Programmability (PostgreSQL)
-- Stored Functions, Recursive CTEs, Stored Procedures, and PL/pgSQL Triggers
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. RECURSIVE CTE STRATEGY PLANNING FUNCTION
-- ----------------------------------------------------------------------------
DROP FUNCTION IF EXISTS plan_strategies(INT, INT);

CREATE OR REPLACE FUNCTION plan_strategies(p_track INT, p_weather INT)
RETURNS TABLE (
    stops             INT,
    compounds         TEXT,
    stint_laps        INT[],
    feasible          BOOLEAN,
    overrun_laps      DOUBLE PRECISION,
    limiting_compound TEXT,
    pit_cost_s        DOUBLE PRECISION,
    pace_cost_s       DOUBLE PRECISION,
    wear_cost_s       DOUBLE PRECISION,
    total_s           DOUBLE PRECISION,
    rnk               INT,
    delta_s           DOUBLE PRECISION
) AS $$
WITH RECURSIVE
trk AS (
    SELECT laps, pit_loss_s, overtake_penalty_s, deg_factor
    FROM tracks WHERE track_id = p_track
),
wx AS (
    SELECT min_stops, requires_two_compounds
    FROM weather_conditions WHERE weather_id = p_weather
),
cw AS (   -- tyres allowed in this weather
    SELECT c.compound_id, c.name, c.hardness_rank,
           x.pace_offset_s, x.deg_per_lap_s, x.base_life_laps
    FROM compound_weather x
    JOIN compounds c ON c.compound_id = x.compound_id
    WHERE x.weather_id = p_weather
),
combo AS (  -- recursive: generate every tyre permutation, 1 to 4 stints
    SELECT s AS stops, 1 AS stint_no,
           ARRAY[c.compound_id] AS ids, c.hardness_rank AS last_rank
    FROM generate_series(0, 3) AS s
    CROSS JOIN cw c
    UNION ALL
    SELECT b.stops, b.stint_no + 1, b.ids || c.compound_id, c.hardness_rank
    FROM combo b
    JOIN cw c ON c.hardness_rank >= b.last_rank
    WHERE b.stint_no < b.stops + 1
),
full_combo AS (
    SELECT stops, ids FROM combo WHERE stint_no = stops + 1
),
valid_combo AS (  -- apply FIA & weather rules
    SELECT f.stops, f.ids
    FROM full_combo f CROSS JOIN wx
    WHERE f.stops >= wx.min_stops
      AND ( NOT wx.requires_two_compounds
            OR (SELECT COUNT(DISTINCT d.cid) FROM unnest(f.ids) AS d(cid)) >= 2 )
),
stint_calc AS (  -- calculate stint lengths across the race distance
    SELECT v.stops, v.ids, u.stint_no, cw.name, cw.pace_offset_s,
           cw.deg_per_lap_s, cw.base_life_laps, t.deg_factor,
           CASE WHEN u.stint_no < v.stops + 1
                THEN t.laps / (v.stops + 1)
                ELSE t.laps - (t.laps / (v.stops + 1)) * v.stops
           END AS len
    FROM valid_combo v
    CROSS JOIN trk t
    CROSS JOIN LATERAL unnest(v.ids) WITH ORDINALITY AS u(compound_id, stint_no)
    JOIN cw ON cw.compound_id = u.compound_id
),
scored AS (      -- aggregate costs per strategy combination
    SELECT sc.stops, sc.ids,
           string_agg(sc.name, ' > ' ORDER BY sc.stint_no) AS compounds,
           array_agg(sc.len ORDER BY sc.stint_no) AS stint_laps,
           bool_and(sc.len <= sc.base_life_laps / sc.deg_factor) AS feasible,
           GREATEST(MAX(sc.len - sc.base_life_laps / sc.deg_factor), 0) AS overrun_laps,
           (array_agg(sc.name ORDER BY sc.len - sc.base_life_laps / sc.deg_factor DESC))[1] AS limiting_compound,
           SUM(sc.pace_offset_s * sc.len) AS pace_cost_s,
           SUM(sc.deg_per_lap_s * sc.deg_factor * sc.len * (sc.len + 1) / 2.0) AS wear_cost_s
    FROM stint_calc sc
    GROUP BY sc.stops, sc.ids
),
priced AS (
    SELECT s.stops, s.compounds, s.stint_laps, s.feasible, s.overrun_laps,
           s.limiting_compound,
           s.stops * (t.pit_loss_s + t.overtake_penalty_s) AS pit_cost_s,
           s.pace_cost_s, s.wear_cost_s,
           s.stops * (t.pit_loss_s + t.overtake_penalty_s) + s.pace_cost_s + s.wear_cost_s AS total_s
    FROM scored s CROSS JOIN trk t
)
SELECT p.stops, p.compounds::TEXT, p.stint_laps, p.feasible,
       p.overrun_laps::DOUBLE PRECISION, p.limiting_compound::TEXT,
       p.pit_cost_s, p.pace_cost_s, p.wear_cost_s, p.total_s,
       (CASE WHEN p.feasible
             THEN ROW_NUMBER() OVER (PARTITION BY p.feasible ORDER BY p.total_s, p.stops)
        END)::INT AS rnk,
       p.total_s - MIN(p.total_s) FILTER (WHERE p.feasible) OVER () AS delta_s
FROM priced p
ORDER BY p.feasible DESC, p.total_s;
$$ LANGUAGE sql STABLE;

-- ----------------------------------------------------------------------------
-- 2. STORED PROCEDURE: IN-RACE SAFETY CAR ADJUSTMENT
-- Demonstrates: Stored Procedure (CREATE PROCEDURE), IN/OUT params, UPDATE logic
-- ----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_apply_safety_car(
    IN p_plan_id INT,
    IN p_discount_pct DOUBLE PRECISION,
    OUT p_old_delta DOUBLE PRECISION,
    OUT p_new_delta DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_track_id INT;
    v_old_pit_loss DOUBLE PRECISION;
    v_pit_time_saved DOUBLE PRECISION;
BEGIN
    -- Validate plan
    SELECT track_id, delta_s INTO v_track_id, p_old_delta
    FROM strategy_plans WHERE plan_id = p_plan_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Strategy plan % does not exist', p_plan_id;
    END IF;

    -- Safety Car reduces pit loss (cars on track travel ~40-50% slower, reducing relative pit loss)
    SELECT pit_loss_s INTO v_old_pit_loss FROM tracks WHERE track_id = v_track_id;
    IF v_old_pit_loss IS NULL THEN
        v_old_pit_loss := 20.0;
    END IF;
    v_pit_time_saved := v_old_pit_loss * (p_discount_pct / 100.0);

    -- Recalculate delta (negative delta = time advantage over green-flag strategy)
    p_new_delta := ROUND((p_old_delta - v_pit_time_saved)::numeric, 2);

    UPDATE strategy_plans
    SET delta_s = p_new_delta
    WHERE plan_id = p_plan_id;

    RAISE NOTICE 'Safety car applied to Plan %: old delta %, new delta % (pit time saved: %)',
                 p_plan_id, p_old_delta, p_new_delta, v_pit_time_saved;
END;
$$;

-- ----------------------------------------------------------------------------
-- 3. STORED PROCEDURE: RECORD EXPLICIT PIT STOP
-- Demonstrates: Multi-table transactional consistency in a stored procedure
-- ----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_record_pit_stop(
    IN p_race_id INT,
    IN p_driver_id INT,
    IN p_stop_no INT,
    IN p_lap_no INT,
    IN p_pit_duration DOUBLE PRECISION,
    IN p_stationary DOUBLE PRECISION,
    IN p_compound_name VARCHAR(10)
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_compound_id INT;
BEGIN
    SELECT compound_id INTO v_compound_id
    FROM compounds WHERE UPPER(name) = UPPER(p_compound_name);

    IF v_compound_id IS NULL THEN
        RAISE EXCEPTION 'Invalid compound %', p_compound_name;
    END IF;

    -- Insert pit stop execution
    INSERT INTO pit_stops (race_id, driver_id, stop_no, lap_no, pit_duration_s, stationary_time_s, tyre_fitted_id)
    VALUES (p_race_id, p_driver_id, p_stop_no, p_lap_no, p_pit_duration, p_stationary, v_compound_id);

    -- Ensure preceding stint is closed at this lap
    UPDATE stints
    SET end_lap = p_lap_no
    WHERE race_id = p_race_id AND driver_id = p_driver_id AND stint_no = p_stop_no;

    -- Start the next stint on the new compound
    INSERT INTO stints (race_id, driver_id, stint_no, compound_id, start_lap, end_lap)
    VALUES (p_race_id, p_driver_id, p_stop_no + 1, v_compound_id, p_lap_no + 1,
            (SELECT laps FROM tracks t JOIN races r ON r.track_id = t.track_id WHERE r.race_id = p_race_id))
    ON CONFLICT (race_id, driver_id, stint_no) 
    DO UPDATE SET compound_id = EXCLUDED.compound_id, start_lap = EXCLUDED.start_lap;

END;
$$;

-- ----------------------------------------------------------------------------
-- 4. TRIGGER: AUDIT TRAIL / CHANGE DATA CAPTURE
-- Demonstrates: Row-level AFTER trigger, TG_OP, JSONB serialization
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_audit_strategy_plans()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (table_name, action_type, record_id, new_data)
        VALUES ('strategy_plans', 'INSERT', NEW.plan_id::TEXT, to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (table_name, action_type, record_id, old_data, new_data)
        VALUES ('strategy_plans', 'UPDATE', NEW.plan_id::TEXT, to_jsonb(OLD), to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (table_name, action_type, record_id, old_data)
        VALUES ('strategy_plans', 'DELETE', OLD.plan_id::TEXT, to_jsonb(OLD));
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_plans ON strategy_plans;
CREATE TRIGGER trg_audit_plans
AFTER INSERT OR UPDATE OR DELETE ON strategy_plans
FOR EACH ROW EXECUTE FUNCTION fn_audit_strategy_plans();

-- ----------------------------------------------------------------------------
-- 5. TRIGGER: BEFORE INSERT ENFORCING FIA TIRE SAFETY RULES
-- Demonstrates: BEFORE trigger rejecting invalid states before write
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_pit_stop_bounds()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.lap_no IS NOT NULL AND NEW.lap_no > 120 THEN
        RAISE EXCEPTION 'Invalid pit stop lap % (exceeds theoretical maximum race distance)', NEW.lap_no;
    END IF;

    IF NEW.stationary_time_s IS NOT NULL AND NEW.pit_duration_s IS NOT NULL AND NEW.stationary_time_s > NEW.pit_duration_s THEN
        RAISE EXCEPTION 'Stationary time (%) cannot exceed total pit duration (%)',
                        NEW.stationary_time_s, NEW.pit_duration_s;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_pit_stop ON pit_stops;
CREATE TRIGGER trg_validate_pit_stop
BEFORE INSERT OR UPDATE ON pit_stops
FOR EACH ROW EXECUTE FUNCTION fn_check_pit_stop_bounds();

-- ----------------------------------------------------------------------------
-- 6. INSTEAD OF TRIGGER ON VIEW: UPDATABLE VIEW ABSTRACTION
-- Demonstrates: INSTEAD OF trigger updating base tables through a joined view
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_instead_of_driver_roster()
RETURNS TRIGGER AS $$
DECLARE
    v_team_id INT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Resolve team_id from team name if supplied
        IF NEW.team_name IS NOT NULL THEN
            SELECT team_id INTO v_team_id FROM teams WHERE LOWER(name) = LOWER(NEW.team_name);
            IF v_team_id IS NULL THEN
                INSERT INTO teams (name) VALUES (NEW.team_name) RETURNING team_id INTO v_team_id;
            END IF;
        ELSE
            v_team_id := NEW.team_id;
        END IF;

        INSERT INTO drivers (code, full_name, team_id)
        VALUES (NEW.code, NEW.full_name, v_team_id);
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.team_name IS NOT NULL AND (OLD.team_name IS DISTINCT FROM NEW.team_name) THEN
            SELECT team_id INTO v_team_id FROM teams WHERE LOWER(name) = LOWER(NEW.team_name);
            IF v_team_id IS NULL THEN
                INSERT INTO teams (name) VALUES (NEW.team_name) RETURNING team_id INTO v_team_id;
            END IF;
        ELSE
            v_team_id := NEW.team_id;
        END IF;

        UPDATE drivers
        SET code = NEW.code, full_name = NEW.full_name, team_id = v_team_id
        WHERE driver_id = OLD.driver_id;
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_driver_roster_io ON v_driver_roster;
CREATE TRIGGER trg_driver_roster_io
INSTEAD OF INSERT OR UPDATE ON v_driver_roster
FOR EACH ROW EXECUTE FUNCTION fn_instead_of_driver_roster();
