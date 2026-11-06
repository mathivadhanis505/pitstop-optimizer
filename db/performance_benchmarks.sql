-- ============================================================================
-- F1 Pitstop Optimizer - Query Optimization & Performance Benchmarks
-- EXPLAIN ANALYZE, Index Selection, Partition Pruning, and MView Caching
-- ============================================================================

-- ----------------------------------------------------------------------------
-- BENCHMARK 1: SEQUENTIAL SCAN VS. INDEX SCAN (B-TREE)
-- Demonstrates: Planner cost estimation, buffers, and forced index usage
-- ----------------------------------------------------------------------------

-- Step 1: Default planner behavior
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT name, laps, pit_loss_s FROM tracks WHERE pit_loss_s > 22.0;

-- Step 2: Disable sequential scan to inspect Index Scan execution cost
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT name, laps, pit_loss_s FROM tracks WHERE pit_loss_s > 22.0;
RESET enable_seqscan;


-- ----------------------------------------------------------------------------
-- BENCHMARK 2: PARTIAL INDEX ACCELERATION
-- Demonstrates: Indexing a selective subset of records saves index space & I/O
-- ----------------------------------------------------------------------------

-- Query querying only scheduled races (matches partial index predicate)
EXPLAIN (ANALYZE, BUFFERS)
SELECT round_no, track_id, race_date 
FROM races 
WHERE status = 'scheduled' AND race_date > '2026-11-01';


-- ----------------------------------------------------------------------------
-- BENCHMARK 3: TABLE PARTITION PRUNING
-- Demonstrates: PostgreSQL static & run-time partition pruning
-- Querying Race 15 only scans 'lap_telemetry_r11_to_r20', ignoring others!
-- ----------------------------------------------------------------------------

EXPLAIN (ANALYZE, BUFFERS)
SELECT driver_id, lap_no, lap_time_s
FROM lap_telemetry
WHERE race_id = 15 AND lap_no > 20;


-- ----------------------------------------------------------------------------
-- BENCHMARK 4: MATERIALIZED VIEW VS. ON-THE-FLY COMPUTED AGGREGATIONS
-- Demonstrates: Precomputed analytics vs expensive multi-table GROUP BY
-- ----------------------------------------------------------------------------

-- Query A: Dynamic join across 4 tables with window ranking and filtering
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.driver_id, d.code, d.full_name, tm.name AS team,
       COUNT(r.race_id) FILTER (WHERE r.finish_pos = 1) AS wins,
       SUM(CASE WHEN r.finish_pos = 1 THEN 25 ELSE 0 END) AS total_points,
       RANK() OVER (ORDER BY SUM(CASE WHEN r.finish_pos = 1 THEN 25 ELSE 0 END) DESC) AS championship_rank
FROM drivers d
LEFT JOIN teams tm ON tm.team_id = d.team_id
LEFT JOIN results r ON r.driver_id = d.driver_id
GROUP BY d.driver_id, d.code, d.full_name, tm.name;

-- Query B: Reading directly from Materialized View (Orders of magnitude faster)
EXPLAIN (ANALYZE, BUFFERS)
SELECT driver_id, code, full_name, team, wins, total_points, championship_rank
FROM mv_driver_championship;

