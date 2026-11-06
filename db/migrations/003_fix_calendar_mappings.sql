-- Migration 003: Real 2024-2026 F1 Calendar Alignment & Track Integrity
-- Aligns 2024 calendar to the official 24-round FIA Formula 1 World Championship schedule.
-- Inserts Imola (Autodromo Enzo e Dino Ferrari) into tracks.
-- Corrects track_id and race_date mappings so OpenF1 / FastF1 telemetry maps to authentic tracks.

BEGIN;

-- 1. Ensure Imola exists in tracks
INSERT INTO tracks (track_id, name, slug, country_id, laps, pit_loss_s, deg_factor, overtake_penalty_s)
VALUES (25, 'Autodromo Enzo e Dino Ferrari (Imola)', 'imola', 15, 63, 21.0, 1.0, 2.0)
ON CONFLICT (track_id) DO UPDATE SET
    name = EXCLUDED.name,
    slug = EXCLUDED.slug,
    laps = EXCLUDED.laps,
    country_id = EXCLUDED.country_id;

-- 2. Clean up any duplicate Lusail / Yas Marina from old rounds 21/22 if present
-- Align 2024 24-round calendar
UPDATE races SET track_id = 4,  race_date = '2024-03-02' WHERE season = 2024 AND round_no = 1;
UPDATE races SET track_id = 5,  race_date = '2024-03-09' WHERE season = 2024 AND round_no = 2;
UPDATE races SET track_id = 1,  race_date = '2024-03-24' WHERE season = 2024 AND round_no = 3;
UPDATE races SET track_id = 3,  race_date = '2024-04-07' WHERE season = 2024 AND round_no = 4;
UPDATE races SET track_id = 2,  race_date = '2024-04-21' WHERE season = 2024 AND round_no = 5; -- Shanghai
UPDATE races SET track_id = 6,  race_date = '2024-05-05' WHERE season = 2024 AND round_no = 6; -- Miami
UPDATE races SET track_id = 25, race_date = '2024-05-19' WHERE season = 2024 AND round_no = 7; -- Imola
UPDATE races SET track_id = 8,  race_date = '2024-05-26' WHERE season = 2024 AND round_no = 8; -- Monaco
UPDATE races SET track_id = 7,  race_date = '2024-06-09' WHERE season = 2024 AND round_no = 9; -- Montreal
UPDATE races SET track_id = 9,  race_date = '2024-06-23' WHERE season = 2024 AND round_no = 10; -- Barcelona
UPDATE races SET track_id = 10, race_date = '2024-06-30' WHERE season = 2024 AND round_no = 11; -- Red Bull Ring
UPDATE races SET track_id = 11, race_date = '2024-07-07' WHERE season = 2024 AND round_no = 12; -- Silverstone
UPDATE races SET track_id = 13, race_date = '2024-07-21' WHERE season = 2024 AND round_no = 13; -- Hungaroring
UPDATE races SET track_id = 12, race_date = '2024-07-28' WHERE season = 2024 AND round_no = 14; -- Spa-Francorchamps
UPDATE races SET track_id = 14, race_date = '2024-08-25' WHERE season = 2024 AND round_no = 15; -- Zandvoort
UPDATE races SET track_id = 15, race_date = '2024-09-01' WHERE season = 2024 AND round_no = 16; -- Monza
UPDATE races SET track_id = 17, race_date = '2024-09-15' WHERE season = 2024 AND round_no = 17; -- Baku
UPDATE races SET track_id = 18, race_date = '2024-09-22' WHERE season = 2024 AND round_no = 18; -- Singapore
UPDATE races SET track_id = 19, race_date = '2024-10-20' WHERE season = 2024 AND round_no = 19; -- COTA
UPDATE races SET track_id = 20, race_date = '2024-10-27' WHERE season = 2024 AND round_no = 20; -- Mexico City
UPDATE races SET track_id = 21, race_date = '2024-11-03' WHERE season = 2024 AND round_no = 21; -- Interlagos
UPDATE races SET track_id = 22, race_date = '2024-11-24' WHERE season = 2024 AND round_no = 22; -- Las Vegas
UPDATE races SET track_id = 23, race_date = '2024-12-01' WHERE season = 2024 AND round_no = 23; -- Lusail
UPDATE races SET track_id = 24, race_date = '2024-12-08' WHERE season = 2024 AND round_no = 24; -- Yas Marina

-- 3. Ensure 2026 calendar has authentic tracks
-- Round 6: Miami (track 6, 2026-05-03), Round 8: Monaco (track 8, 2026-06-07)
UPDATE races SET track_id = 6, race_date = '2026-05-03' WHERE season = 2026 AND round_no = 6;
UPDATE races SET track_id = 8, race_date = '2026-06-07' WHERE season = 2026 AND round_no = 8;

-- 4. Refresh materialized view
REFRESH MATERIALIZED VIEW mv_driver_championship;

COMMIT;

