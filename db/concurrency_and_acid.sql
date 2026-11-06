-- ============================================================================
-- F1 Pitstop Optimizer - Transactions, Concurrency & ACID Controls
-- Academic Lab Experiments: Isolation Levels, Pessimistic Locking, Savepoints
-- ============================================================================

-- ----------------------------------------------------------------------------
-- EXPERIMENT 1: ATOMICITY & SAVEPOINT ROLLBACK
-- Demonstrates: Partial rollback without aborting the parent transaction
-- ----------------------------------------------------------------------------
BEGIN;
-- Step 1: Update pit loss
UPDATE tracks SET pit_loss_s = 25.0 WHERE slug = 'monza';

SAVEPOINT pre_degradation_change;

-- Step 2: Test an experimental extreme degradation factor
UPDATE tracks SET deg_factor = 99.9 WHERE slug = 'monza';

-- Verify extreme change inside transaction
SELECT name, pit_loss_s, deg_factor FROM tracks WHERE slug = 'monza';

-- Roll back to savepoint (reverting extreme deg_factor while keeping pit_loss_s)
ROLLBACK TO SAVEPOINT pre_degradation_change;

-- Verify state after partial rollback
SELECT name, pit_loss_s, deg_factor FROM tracks WHERE slug = 'monza';

-- Final rollback to preserve initial baseline
ROLLBACK;


-- ----------------------------------------------------------------------------
-- EXPERIMENT 2: CONSISTENCY & DEFERRED CONSTRAINT TRIGGER
-- Demonstrates: Intermediate inconsistent states permitted; enforced at COMMIT
-- ----------------------------------------------------------------------------
BEGIN;
-- Monza requires 53 laps. We insert a strategy with only 10 laps.
INSERT INTO strategy_plans (track_id, weather_id, stops) VALUES (13, 1, 1);

-- Deferred trigger is NOT fired yet here!
INSERT INTO plan_stints (plan_id, stint_no, compound_id, stint_laps)
VALUES (currval('strategy_plans_plan_id_seq'), 1, 2, 10);

-- Attempting to COMMIT will trigger trg_plan_laps and abort with EXCEPTION:
-- "ERROR: Plan X stint laps (10) do not equal race laps (53)"
COMMIT;


-- ----------------------------------------------------------------------------
-- EXPERIMENT 3: PESSIMISTIC CONCURRENCY CONTROL (SELECT ... FOR UPDATE)
-- Demonstrates: Preventing simultaneous pit lane double-stack collisions
-- Scenario: Both cars of Team 1 (RUS and ANT) call to pit on the same lap.
-- ----------------------------------------------------------------------------
-- Transaction Session A (Car 1 - RUS entering pit):
BEGIN;
SELECT box_number, is_occupied 
FROM pit_boxes 
WHERE team_id = 1 
FOR UPDATE; -- Acquires row-level exclusive lock on Team 1's pit box

UPDATE pit_boxes 
SET is_occupied = TRUE, current_car = 1, last_service = now() 
WHERE team_id = 1;

-- (Session B running concurrently trying to lock Team 1 will BLOCKED until Session A commits)
COMMIT;


-- ----------------------------------------------------------------------------
-- EXPERIMENT 4: TRANSACTION ISOLATION LEVELS & PHANTOM READS
-- Demonstrates: READ COMMITTED vs REPEATABLE READ
-- ----------------------------------------------------------------------------

-- Session 1 (Repeatable Read):
-- BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- SELECT COUNT(*) FROM strategy_plans WHERE stops = 1;
--
-- Session 2 (Concurrent Insert):
-- BEGIN;
-- INSERT INTO strategy_plans (track_id, weather_id, stops) VALUES (13, 1, 1);
-- COMMIT;
--
-- Back in Session 1:
-- SELECT COUNT(*) FROM strategy_plans WHERE stops = 1;
-- Under READ COMMITTED: count would change (Non-repeatable / Phantom read).
-- Under REPEATABLE READ: snapshot isolation prevents seeing the new row!
-- COMMIT;

