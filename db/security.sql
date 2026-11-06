-- ============================================================================
-- F1 Pitstop Optimizer - Security & Access Control (PostgreSQL)
-- Role-Based Access Control (RBAC) & Row-Level Security (RLS)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. ROLE-BASED ACCESS CONTROL (RBAC)
-- Demonstrates: CREATE ROLE, GRANT, REVOKE, Principle of Least Privilege
-- ----------------------------------------------------------------------------

-- Role 1: Guest / Public Viewer (Read-only on public calendar & results)
DROP ROLE IF EXISTS f1_viewer;
CREATE ROLE f1_viewer WITH LOGIN PASSWORD 'viewer_pass';
GRANT USAGE ON SCHEMA public TO f1_viewer;
GRANT SELECT ON v_calendar, v_stint_summary, mv_driver_championship, tracks, compounds TO f1_viewer;

-- Role 2: Race Strategist / Telemetry Engineer
DROP ROLE IF EXISTS race_engineer;
CREATE ROLE race_engineer WITH LOGIN PASSWORD 'engineer_pass';
GRANT USAGE ON SCHEMA public TO race_engineer;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO race_engineer;
GRANT INSERT, UPDATE ON strategy_plans, plan_stints, pit_stops TO race_engineer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO race_engineer;
GRANT EXECUTE ON FUNCTION plan_strategies(INT, INT) TO race_engineer;
GRANT EXECUTE ON PROCEDURE sp_apply_safety_car(INT, DOUBLE PRECISION) TO race_engineer;

-- Role 3: Database Administrator (Full DDL & DML permissions)
DROP ROLE IF EXISTS f1_admin;
CREATE ROLE f1_admin WITH SUPERUSER LOGIN PASSWORD 'admin_pass';

-- ----------------------------------------------------------------------------
-- 2. ROW-LEVEL SECURITY (RLS) - MULTI-TENANCY DEMONSTRATION
-- Demonstrates: ALTER TABLE ... ENABLE ROW LEVEL SECURITY, CREATE POLICY
-- Scenario: Each race engineer can only view and modify strategy plans
-- created by or assigned to their respective team.
-- ----------------------------------------------------------------------------

-- Add team ownership column to strategy_plans
ALTER TABLE strategy_plans ADD COLUMN IF NOT EXISTS team_id INT REFERENCES teams(team_id);

-- Enable RLS
ALTER TABLE strategy_plans ENABLE ROW LEVEL SECURITY;

-- Policy 1: Full access for Admin role
DROP POLICY IF EXISTS p_admin_all ON strategy_plans;
CREATE POLICY p_admin_all ON strategy_plans
    FOR ALL
    TO f1_admin
    USING (true)
    WITH CHECK (true);

-- Policy 2: Engineers can only see their own team's secret strategies
-- (Uses current_setting session variable 'app.current_team_id')
DROP POLICY IF EXISTS p_team_isolation ON strategy_plans;
CREATE POLICY p_team_isolation ON strategy_plans
    FOR ALL
    TO race_engineer
    USING (
        team_id IS NULL OR 
        team_id = NULLIF(current_setting('app.current_team_id', true), '')::INT
    )
    WITH CHECK (
        team_id = NULLIF(current_setting('app.current_team_id', true), '')::INT
    );

-- ----------------------------------------------------------------------------
-- 3. RLS TESTING SCRIPT (HOW TO DEMO IN VIVA)
-- ----------------------------------------------------------------------------
/*
-- 1. As Mercedes engineer (team_id = 1):
SET ROLE race_engineer;
SET app.current_team_id = '1';
INSERT INTO strategy_plans (track_id, weather_id, stops, team_id) VALUES (13, 1, 1, 1);
SELECT plan_id, track_id, team_id FROM strategy_plans; -- Returns Mercedes plans

-- 2. Switch context to Ferrari engineer (team_id = 2):
SET app.current_team_id = '2';
SELECT plan_id, track_id, team_id FROM strategy_plans; -- Mercedes plan is invisible!

-- Reset
RESET ROLE;
*/

