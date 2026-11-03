-- 1. INNER JOIN across 3 tables
SELECT r.round_no, t.name AS track, c.name AS country, r.status
FROM races r
JOIN tracks t ON t.track_id = r.track_id
JOIN countries c ON c.country_id = t.country_id
ORDER BY r.round_no;

-- 2. LEFT JOIN (driver with no team shows NULL)
SELECT d.code, d.full_name, tm.name AS team
FROM drivers d LEFT JOIN teams tm ON tm.team_id = d.team_id;

-- 3. Aggregate + GROUP BY + HAVING
SELECT c.name AS country, COUNT(*) AS tracks,
       ROUND(AVG(t.pit_loss_s)::numeric, 1) AS avg_pit_loss
FROM tracks t JOIN countries c ON c.country_id = t.country_id
GROUP BY c.name HAVING COUNT(*) > 1
ORDER BY tracks DESC;

-- 4. Nested query (scalar subquery)
SELECT name, pit_loss_s FROM tracks
WHERE pit_loss_s > (SELECT AVG(pit_loss_s) FROM tracks);

-- 5. IN and EXISTS
SELECT name FROM tracks
WHERE track_id IN (SELECT track_id FROM races WHERE status = 'cancelled');

SELECT t.name FROM tracks t
WHERE EXISTS (SELECT 1 FROM races r
              WHERE r.track_id = t.track_id AND r.status = 'completed');

-- 6. Correlated subquery: tracks longer than their country's average
SELECT t.name, t.laps FROM tracks t
WHERE t.laps > (SELECT AVG(t2.laps) FROM tracks t2
                WHERE t2.country_id = t.country_id);

-- 7. Set operations
SELECT name FROM tracks WHERE deg_factor >= 1.1
INTERSECT
SELECT name FROM tracks WHERE overtake_penalty_s = 0;

SELECT name FROM tracks WHERE deg_factor >= 1.1
EXCEPT
SELECT name FROM tracks WHERE overtake_penalty_s = 0;

SELECT name FROM tracks WHERE laps >= 70
UNION
SELECT name FROM tracks WHERE pit_loss_s >= 25;

-- 8. Three-valued logic (NULL = DNF)
SELECT COUNT(*) AS all_rows, COUNT(finish_pos) AS non_null FROM results;
SELECT * FROM results WHERE finish_pos = NULL;
SELECT * FROM results WHERE finish_pos IS NULL;
SELECT * FROM results WHERE finish_pos <> 1;
SELECT * FROM results WHERE finish_pos <> 1 OR finish_pos IS NULL;

-- 9. Self join: pairs of tracks in the same country
SELECT a.name AS track_a, b.name AS track_b, c.name AS country
FROM tracks a
JOIN tracks b ON a.country_id = b.country_id AND a.track_id < b.track_id
JOIN countries c ON c.country_id = a.country_id;

-- 10. Views
SELECT * FROM v_stint_summary ORDER BY driver, stint_no;
SELECT * FROM v_calendar WHERE status <> 'completed';

-- 11. Relational division: drivers who used ALL of SOFT, MEDIUM, HARD
SELECT d.code FROM drivers d
WHERE NOT EXISTS (
    SELECT 1 FROM compounds c
    WHERE c.is_wet = FALSE AND NOT EXISTS (
        SELECT 1 FROM stints s
        WHERE s.driver_id = d.driver_id AND s.compound_id = c.compound_id));

-- 12. DDL + DML
ALTER TABLE tracks ADD COLUMN is_street BOOLEAN DEFAULT FALSE;
UPDATE tracks SET is_street = TRUE
WHERE name IN ('Circuit de Monaco', 'Baku City Circuit', 'Marina Bay (Singapore)',
               'Las Vegas Street Circuit', 'Jeddah Street Circuit');
SELECT name FROM tracks WHERE is_street;
ALTER TABLE tracks DROP COLUMN is_street;

-- 13. Constraint violations (each should ERROR)
INSERT INTO tracks (name, slug, country_id, laps, pit_loss_s, deg_factor)
VALUES ('Bad', 'bad', 1, 5, 20, 1);
INSERT INTO drivers (code, full_name, team_id) VALUES ('XXX', 'Nobody', 99);
INSERT INTO countries (name) VALUES ('Italy');

-- 14. Transaction with SAVEPOINT
BEGIN;
UPDATE tracks SET pit_loss_s = 30 WHERE name = 'Monza';
SAVEPOINT sp1;
UPDATE tracks SET pit_loss_s = 99 WHERE name = 'Monza';
ROLLBACK TO sp1;
SELECT name, pit_loss_s FROM tracks WHERE name = 'Monza';
ROLLBACK;

-- 15. Assertion substitute: should FAIL at COMMIT (10 laps <> 53)
BEGIN;
INSERT INTO strategy_plans (track_id, weather_id, stops) VALUES (13, 1, 1);
INSERT INTO plan_stints (plan_id, stint_no, compound_id, stint_laps)
VALUES (currval('strategy_plans_plan_id_seq'), 1, 2, 10);
COMMIT;

-- 16. Indexing
CREATE INDEX idx_tracks_pit_loss ON tracks (pit_loss_s);
EXPLAIN ANALYZE SELECT * FROM tracks WHERE pit_loss_s > 24;
SET enable_seqscan = off;
EXPLAIN ANALYZE SELECT * FROM tracks WHERE pit_loss_s > 24;
RESET enable_seqscan;
