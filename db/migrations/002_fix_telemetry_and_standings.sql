-- ============================================================================
-- Migration 002: Fix Pit Stops Constraints, Safety Car Procedure, & Standings View
-- Non-destructive: preserves existing schema, academic queries, and data
-- ============================================================================

-- 1. Relax NOT NULL constraints on pit_stops to accommodate real telemetry/feed data
ALTER TABLE pit_stops ALTER COLUMN stationary_time_s DROP NOT NULL;
ALTER TABLE pit_stops ALTER COLUMN tyre_fitted_id DROP NOT NULL;
ALTER TABLE pit_stops ALTER COLUMN pit_duration_s DROP NOT NULL;

ALTER TABLE pit_stops DROP CONSTRAINT IF EXISTS pit_stops_stationary_time_s_check;
ALTER TABLE pit_stops ADD CONSTRAINT pit_stops_stationary_time_s_check 
    CHECK (stationary_time_s IS NULL OR stationary_time_s > 0);

ALTER TABLE pit_stops DROP CONSTRAINT IF EXISTS pit_stops_pit_duration_s_check;
ALTER TABLE pit_stops ADD CONSTRAINT pit_stops_pit_duration_s_check 
    CHECK (pit_duration_s IS NULL OR pit_duration_s > 0);

-- 2. Drop restrictive UNIQUE (season, track_id) to allow full multi-round calendars
ALTER TABLE races DROP CONSTRAINT IF EXISTS races_season_track_id_key;

-- 3. Update pit stop validation trigger function to safely handle real race telemetry
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

-- 4. Correct stored procedure sp_apply_safety_car
-- Pitting under Safety Car reduces pit loss relative to racing pace, granting a time advantage
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

    -- Safety Car reduces pit loss (cars on track travel ~40-50% slower, so pit loss delta is reduced)
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

-- 5. Recreate Materialized View with ROW_NUMBER() and deterministic tie-breaking
DROP MATERIALIZED VIEW IF EXISTS mv_driver_championship CASCADE;

CREATE MATERIALIZED VIEW mv_driver_championship AS
SELECT r.season, d.driver_id, d.code, d.full_name, COALESCE(tm.name, 'Independent') AS team,
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
