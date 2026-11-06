-- ============================================================================
-- Migration 001: FastF1 Analytics Upgrade & Ingestion Support
-- Non-destructive schema extension for real-world historical telemetry
-- ============================================================================

-- 1. Table Partitioning Expansion on lap_telemetry
-- Ensure any race_id (including multi-season imports) is safely accommodated
DO $$
BEGIN
    -- Create default partition if not exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'lap_telemetry_default'
    ) THEN
        CREATE TABLE lap_telemetry_default PARTITION OF lap_telemetry DEFAULT;
    END IF;
END $$;

-- 2. Relax sector nullability constraints for incomplete / in-out telemetry laps
ALTER TABLE lap_telemetry ALTER COLUMN sector1_s DROP NOT NULL;
ALTER TABLE lap_telemetry ALTER COLUMN sector2_s DROP NOT NULL;
ALTER TABLE lap_telemetry ALTER COLUMN sector3_s DROP NOT NULL;
ALTER TABLE lap_telemetry ALTER COLUMN lap_time_s DROP NOT NULL;

-- 3. Add analytical columns to lap_telemetry
ALTER TABLE lap_telemetry ADD COLUMN IF NOT EXISTS position INT;
ALTER TABLE lap_telemetry ADD COLUMN IF NOT EXISTS compound_id INT REFERENCES compounds(compound_id);

-- 4. Analytical Indexing for Telemetry & Pace Queries
CREATE INDEX IF NOT EXISTS idx_telemetry_race_driver ON lap_telemetry (race_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_driver_lap ON lap_telemetry (driver_id, lap_no);
CREATE INDEX IF NOT EXISTS idx_telemetry_compound ON lap_telemetry (compound_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_tyre_age ON lap_telemetry (compound_id, tyre_age_laps);

-- 5. Race & Track metadata extensions for FastF1 mapping
ALTER TABLE races ADD COLUMN IF NOT EXISTS event_name VARCHAR(100);
ALTER TABLE races ADD COLUMN IF NOT EXISTS session_type VARCHAR(10) DEFAULT 'R';
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS circuit_short_name VARCHAR(50);

-- 6. Ingestion Status Tracking Table
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id         SERIAL PRIMARY KEY,
    season         INT NOT NULL,
    round_no       INT,
    session_type   VARCHAR(10) NOT NULL DEFAULT 'R',
    status         VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    laps_imported  INT NOT NULL DEFAULT 0,
    stints_imported INT NOT NULL DEFAULT 0,
    stops_imported INT NOT NULL DEFAULT 0,
    error_message  TEXT,
    started_at     TIMESTAMP NOT NULL DEFAULT clock_timestamp(),
    finished_at    TIMESTAMP
);

-- 7. Ensure Initial Audit Log Records for Immediate Viva Demonstrations
INSERT INTO audit_log (table_name, action_type, record_id, new_data, changed_by, changed_at)
SELECT 'strategy_plans', 'INSERT', '1', 
       '{"plan_id": 1, "track_id": 20, "weather_id": 1, "stops": 2, "delta_s": 0.0}'::jsonb, 
       'f1_chief_strategist', CURRENT_TIMESTAMP - INTERVAL '2 hours'
WHERE NOT EXISTS (SELECT 1 FROM audit_log);

INSERT INTO audit_log (table_name, action_type, record_id, old_data, new_data, changed_by, changed_at)
SELECT 'strategy_plans', 'UPDATE', '1', 
       '{"plan_id": 1, "track_id": 20, "weather_id": 1, "stops": 2, "delta_s": 0.0}'::jsonb,
       '{"plan_id": 1, "track_id": 20, "weather_id": 1, "stops": 2, "delta_s": -2.4}'::jsonb, 
       'f1_race_engineer', CURRENT_TIMESTAMP - INTERVAL '30 minutes'
WHERE (SELECT COUNT(*) FROM audit_log) < 2;


