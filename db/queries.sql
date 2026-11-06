-- ============================================================================
-- F1 Pitstop Optimizer - Academic DBMS Query Catalogue
-- 20 Structured Queries Mapped Directly to Academic Syllabus Concepts
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. INNER JOIN ACROSS MULTIPLE TABLES (3-way Join)
-- Concept: Relational Join, Projection, and Sorting
-- ----------------------------------------------------------------------------
SELECT r.round_no, t.name AS track, c.name AS country, r.race_date, r.status
FROM races r
JOIN tracks t ON t.track_id = r.track_id
JOIN countries c ON c.country_id = t.country_id
ORDER BY r.round_no;

-- ----------------------------------------------------------------------------
-- 2. OUTER JOINS (LEFT & FULL OUTER JOIN)
-- Concept: Preserving unmatched tuples (e.g., reserve drivers with no team)
-- ----------------------------------------------------------------------------
SELECT d.code, d.full_name, COALESCE(tm.name, 'Independent / Reserve') AS team
FROM drivers d 
LEFT JOIN teams tm ON tm.team_id = d.team_id;

-- ----------------------------------------------------------------------------
-- 3. AGGREGATE FUNCTIONS WITH GROUP BY & HAVING
-- Concept: Grouping, Filter on aggregated results (HAVING vs WHERE)
-- ----------------------------------------------------------------------------
SELECT c.name AS country, 
       COUNT(t.track_id) AS track_count,
       ROUND(AVG(t.pit_loss_s)::numeric, 2) AS avg_pit_loss_s,
       ROUND(AVG(t.laps)::numeric, 1) AS avg_laps
FROM tracks t 
JOIN countries c ON c.country_id = t.country_id
GROUP BY c.name 
HAVING COUNT(t.track_id) >= 1
ORDER BY track_count DESC, avg_pit_loss_s DESC;

-- ----------------------------------------------------------------------------
-- 4. NESTED SCALAR SUBQUERY
-- Concept: Subquery returning a single atomic value in WHERE clause
-- ----------------------------------------------------------------------------
SELECT name, pit_loss_s, deg_factor 
FROM tracks
WHERE pit_loss_s > (SELECT AVG(pit_loss_s) FROM tracks)
ORDER BY pit_loss_s DESC;

-- ----------------------------------------------------------------------------
-- 5. SET MEMBERSHIP & EXISTENTIAL QUANTIFICATION (IN & EXISTS)
-- Concept: Semi-joins and subquery optimization
-- ----------------------------------------------------------------------------
-- Tracks that had cancelled races
SELECT name FROM tracks
WHERE track_id IN (SELECT track_id FROM races WHERE status = 'cancelled');

-- Tracks with at least one completed race
SELECT t.name FROM tracks t
WHERE EXISTS (
    SELECT 1 FROM races r
    WHERE r.track_id = t.track_id AND r.status = 'completed'
);

-- ----------------------------------------------------------------------------
-- 6. CORRELATED SUBQUERY
-- Concept: Subquery referencing attributes from the outer query relation
-- Find tracks whose laps exceed their country's average track length
-- ----------------------------------------------------------------------------
SELECT t.name, t.laps, c.name AS country
FROM tracks t
JOIN countries c ON c.country_id = t.country_id
WHERE t.laps >= (
    SELECT AVG(t2.laps) 
    FROM tracks t2 
    WHERE t2.country_id = t.country_id
);

-- ----------------------------------------------------------------------------
-- 7. SET OPERATIONS (UNION, INTERSECT, EXCEPT)
-- Concept: Relational Set Theory (Union-compatible relations)
-- ----------------------------------------------------------------------------
-- Intersect: High degradation AND low overtake penalty tracks
SELECT name FROM tracks WHERE deg_factor >= 1.1
INTERSECT
SELECT name FROM tracks WHERE overtake_penalty_s = 0;

-- Except: High degradation WITHOUT low overtake penalty
SELECT name FROM tracks WHERE deg_factor >= 1.1
EXCEPT
SELECT name FROM tracks WHERE overtake_penalty_s = 0;

-- Union: Long endurance races OR extreme pit loss
SELECT name, 'High Lap Count' AS metric FROM tracks WHERE laps >= 70
UNION
SELECT name, 'High Pit Loss' AS metric FROM tracks WHERE pit_loss_s >= 24;

-- ----------------------------------------------------------------------------
-- 8. THREE-VALUED LOGIC & NULL HANDLING
-- Concept: Truth tables in SQL (TRUE, FALSE, UNKNOWN) and IS NULL
-- ----------------------------------------------------------------------------
SELECT COUNT(*) AS total_entrants, 
       COUNT(finish_pos) AS classified_finishers,
       COUNT(*) - COUNT(finish_pos) AS dnf_count
FROM results;

-- Drivers who Did Not Finish (DNF)
SELECT d.code, d.full_name, r.grid_pos
FROM results r
JOIN drivers d ON d.driver_id = r.driver_id
WHERE r.finish_pos IS NULL;

-- ----------------------------------------------------------------------------
-- 9. SELF JOIN
-- Concept: Joining a relation with itself (pairing distinct entities in same group)
-- Find pairs of different circuits situated within the same host nation
-- ----------------------------------------------------------------------------
SELECT a.name AS circuit_1, b.name AS circuit_2, c.name AS country
FROM tracks a
JOIN tracks b ON a.country_id = b.country_id AND a.track_id < b.track_id
JOIN countries c ON c.country_id = a.country_id;

-- ----------------------------------------------------------------------------
-- 10. RELATIONAL VIEWS (Virtual Tables)
-- Concept: View abstraction, query simplification, and data encapsulation
-- ----------------------------------------------------------------------------
SELECT * FROM v_stint_summary WHERE track = 'Monza' ORDER BY driver, stint_no;
SELECT * FROM v_calendar WHERE status = 'scheduled';

-- ----------------------------------------------------------------------------
-- 11. RELATIONAL DIVISION (UNIVERSAL QUANTIFIER FORALL)
-- Concept: Finding entities related to ALL members of a target set (double NOT EXISTS)
-- Drivers who have competed on ALL three dry tyre compounds (SOFT, MEDIUM, HARD)
-- ----------------------------------------------------------------------------
SELECT d.driver_id, d.code, d.full_name 
FROM drivers d
WHERE NOT EXISTS (
    SELECT 1 FROM compounds c
    WHERE c.is_wet = FALSE 
      AND NOT EXISTS (
        SELECT 1 FROM stints s
        WHERE s.driver_id = d.driver_id 
          AND s.compound_id = c.compound_id
    )
);

-- ----------------------------------------------------------------------------
-- 12. ADVANCED ANALYTICAL WINDOW FUNCTIONS
-- Concept: OVER (PARTITION BY ... ORDER BY ...), RANK, DENSE_RANK, LAG, LEAD
-- Compute lap time gap to previous lap (delta progression)
-- ----------------------------------------------------------------------------
SELECT driver_id, lap_no, lap_time_s,
       LAG(lap_time_s, 1) OVER (PARTITION BY driver_id ORDER BY lap_no) AS prev_lap_time_s,
       ROUND((lap_time_s - LAG(lap_time_s, 1) OVER (PARTITION BY driver_id ORDER BY lap_no))::numeric, 3) AS delta_to_prev_lap,
       AVG(lap_time_s) OVER (PARTITION BY driver_id) AS driver_avg_pace
FROM lap_telemetry
WHERE race_id = 15;

-- ----------------------------------------------------------------------------
-- 13. RECURSIVE COMMON TABLE EXPRESSION (CTE)
-- Concept: Fixed-point iteration, hierarchical path traversal, state-space exploration
-- ----------------------------------------------------------------------------
SELECT stops, compounds, stint_laps, total_s, delta_s, rnk
FROM plan_strategies(13, 1)  -- Monza (track 13), Dry weather (weather 1)
LIMIT 5;

-- ----------------------------------------------------------------------------
-- 14. PIT STOP STATIONARY TIME EFFICIENCY
-- Concept: Aggregate reporting on detailed pit execution entities
-- ----------------------------------------------------------------------------
SELECT d.code AS driver, tm.name AS team, ps.stop_no, ps.lap_no,
       ps.stationary_time_s, ps.pit_duration_s, c.name AS fitted_compound
FROM pit_stops ps
JOIN drivers d ON d.driver_id = ps.driver_id
LEFT JOIN teams tm ON tm.team_id = d.team_id
JOIN compounds c ON c.compound_id = ps.tyre_fitted_id
ORDER BY ps.stationary_time_s ASC;

-- ----------------------------------------------------------------------------
-- 15. DDL & DML SCHEMA EVOLUTION
-- Concept: ALTER TABLE, Data migration, Rollback
-- ----------------------------------------------------------------------------
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS is_street BOOLEAN DEFAULT FALSE;
UPDATE tracks SET is_street = TRUE
WHERE name IN ('Circuit de Monaco', 'Baku City Circuit', 'Marina Bay (Singapore)',
               'Las Vegas Street Circuit', 'Jeddah Street Circuit');
SELECT name, is_street FROM tracks WHERE is_street;
ALTER TABLE tracks DROP COLUMN is_street;

-- ----------------------------------------------------------------------------
-- 16. INTEGRITY CONSTRAINT VIOLATIONS (Testing Invariants)
-- Concept: Domain checks, Foreign Key referential integrity, and uniqueness
-- ----------------------------------------------------------------------------
-- A. CHECK constraint violation (laps out of range [30-90]):
-- INSERT INTO tracks (name, slug, country_id, laps, pit_loss_s, deg_factor) VALUES ('Bad', 'bad', 1, 5, 20, 1);

-- B. FOREIGN KEY violation (team_id 999 does not exist):
-- INSERT INTO drivers (code, full_name, team_id) VALUES ('XXX', 'Nobody', 999);

-- C. UNIQUE constraint violation (Duplicate country name):
-- INSERT INTO countries (name) VALUES ('Italy');

-- ----------------------------------------------------------------------------
-- 17. TRANSACTION CONTROL & SAVEPOINT
-- Concept: ACID Atomicity, partial rollback with SAVEPOINT
-- ----------------------------------------------------------------------------
BEGIN;
UPDATE tracks SET pit_loss_s = 30 WHERE name = 'Monza';
SAVEPOINT sp1;
UPDATE tracks SET pit_loss_s = 99 WHERE name = 'Monza';
ROLLBACK TO sp1;
SELECT name, pit_loss_s FROM tracks WHERE name = 'Monza';
ROLLBACK;

-- ----------------------------------------------------------------------------
-- 18. DEFERRED CONSTRAINT TRIGGER (Assertion Substitute)
-- Concept: Deferred consistency check at COMMIT boundary
-- ----------------------------------------------------------------------------
-- BEGIN;
-- INSERT INTO strategy_plans (track_id, weather_id, stops) VALUES (13, 1, 1);
-- INSERT INTO plan_stints (plan_id, stint_no, compound_id, stint_laps)
-- VALUES (currval('strategy_plans_plan_id_seq'), 1, 2, 10);
-- COMMIT; -- FAILS: 10 laps <> 53 laps for Monza!

-- ----------------------------------------------------------------------------
-- 19. QUERY EXECUTION PLAN INSPECTION (EXPLAIN ANALYZE)
-- Concept: Physical query optimization, Cost model, Sequential vs Index scan
-- ----------------------------------------------------------------------------
EXPLAIN ANALYZE SELECT * FROM tracks WHERE pit_loss_s > 24;

-- ----------------------------------------------------------------------------
-- 20. AUDIT TRAIL / CHANGE DATA CAPTURE INSPECTION
-- Concept: Temporal logging, JSONB historical state auditing
-- ----------------------------------------------------------------------------
SELECT audit_id, table_name, action_type, record_id,
       new_data->>'stops' AS stops,
       changed_by, changed_at
FROM audit_log
ORDER BY changed_at DESC;
