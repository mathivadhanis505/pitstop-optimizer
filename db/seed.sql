INSERT INTO countries (name) VALUES
 ('Australia'),('China'),('Japan'),('Bahrain'),('Saudi Arabia'),('USA'),('Canada'),
 ('Monaco'),('Spain'),('Austria'),('UK'),('Belgium'),('Hungary'),('Netherlands'),
 ('Italy'),('Azerbaijan'),('Singapore'),('Mexico'),('Brazil'),('Qatar'),('UAE');

-- compound_id: 1 SOFT, 2 MEDIUM, 3 HARD, 4 INTER, 5 WET
INSERT INTO compounds (name, hardness_rank, colour_hex, is_wet) VALUES
 ('SOFT',    1, '#E10600', FALSE),
 ('MEDIUM',  2, '#FFD100', FALSE),
 ('HARD',    3, '#FFFFFF', FALSE),
 ('INTER',   0, '#43B02A', TRUE),
 ('WET',    -1, '#0067AD', TRUE);

INSERT INTO weather_conditions (name, description, min_stops, requires_two_compounds) VALUES
 ('DRY',  'Dry track',                  1, TRUE),
 ('DAMP', 'Light rain or drying track', 0, FALSE),
 ('WET',  'Heavy rain',                 0, FALSE);

-- all numbers are rough estimates
INSERT INTO compound_weather (compound_id, weather_id, pace_offset_s, deg_per_lap_s, base_life_laps)
SELECT c.compound_id, w.weather_id, v.pace, v.deg, v.life
FROM (VALUES
 ('SOFT',   'DRY',  -0.8, 0.09, 18),
 ('MEDIUM', 'DRY',  -0.4, 0.05, 30),
 ('HARD',   'DRY',   0.0, 0.03, 42),
 ('MEDIUM', 'DAMP',  4.0, 0.10, 25),
 ('INTER',  'DAMP',  0.0, 0.04, 40),
 ('INTER',  'WET',   3.0, 0.06, 30),
 ('WET',    'WET',   0.0, 0.03, 45)
) AS v(comp, wx, pace, deg, life)
JOIN compounds c ON c.name = v.comp
JOIN weather_conditions w ON w.name = v.wx;

INSERT INTO tracks (name, slug, country_id, laps, pit_loss_s, deg_factor, overtake_penalty_s)
SELECT v.name, v.slug, c.country_id, v.laps, v.pit, v.deg, v.ot
FROM (VALUES
 (1,  'Albert Park (Melbourne)',             'albert-park',   'Australia',    58, 19, 0.9, 4),
 (2,  'Shanghai International Circuit',      'shanghai',      'China',        56, 22, 1.1, 0),
 (3,  'Suzuka',                              'suzuka',        'Japan',        53, 22, 1.2, 4),
 (4,  'Miami International Autodrome',       'miami',         'USA',          57, 20, 1.0, 2),
 (5,  'Circuit Gilles-Villeneuve (Montreal)','montreal',      'Canada',       70, 17, 0.9, 6),
 (6,  'Circuit de Monaco',                   'monaco',        'Monaco',       78, 19, 0.7, 20),
 (7,  'Circuit de Barcelona-Catalunya',      'barcelona',     'Spain',        66, 21, 1.3, 4),
 (8,  'Red Bull Ring',                       'red-bull-ring', 'Austria',      71, 19, 1.0, 0),
 (9,  'Silverstone',                         'silverstone',   'UK',           52, 20, 1.3, 0),
 (10, 'Spa-Francorchamps',                   'spa',           'Belgium',      44, 18, 1.0, 0),
 (11, 'Hungaroring',                         'hungaroring',   'Hungary',      70, 20, 1.1, 5),
 (12, 'Zandvoort',                           'zandvoort',     'Netherlands',  72, 18, 1.1, 5),
 (13, 'Monza',                               'monza',         'Italy',        53, 24, 0.8, 0),
 (14, 'Madring (Madrid)',                    'madring',       'Spain',        56, 20, 1.0, 4),
 (15, 'Baku City Circuit',                   'baku',          'Azerbaijan',   51, 20, 0.8, 0),
 (16, 'Marina Bay (Singapore)',              'singapore',     'Singapore',    62, 26, 0.9, 8),
 (17, 'Circuit of the Americas',             'cota',          'USA',          56, 20, 1.1, 0),
 (18, 'Autodromo Hermanos Rodriguez',        'mexico-city',   'Mexico',       71, 22, 0.9, 2),
 (19, 'Interlagos',                          'interlagos',    'Brazil',       71, 20, 1.1, 0),
 (20, 'Las Vegas Street Circuit',            'las-vegas',     'USA',          50, 20, 0.8, 0),
 (21, 'Lusail',                              'lusail',        'Qatar',        57, 25, 1.4, 3),
 (22, 'Yas Marina',                          'yas-marina',    'UAE',          58, 21, 0.9, 3),
 (23, 'Bahrain International Circuit',       'bahrain',       'Bahrain',      57, 22, 1.3, 2),
 (24, 'Jeddah Street Circuit',               'jeddah',        'Saudi Arabia', 50, 20, 1.0, 2)
) AS v(ord, name, slug, country, laps, pit, deg, ot)
JOIN countries c ON c.name = v.country
ORDER BY v.ord;

INSERT INTO teams (name) VALUES ('Mercedes'), ('Ferrari');

-- DUMMY practice drivers (made up)
INSERT INTO drivers (code, full_name, team_id) VALUES
 ('RUS', 'George Russell',   1),
 ('ANT', 'Kimi Antonelli',   1),
 ('HAM', 'Lewis Hamilton',   2),
 ('LEC', 'Charles Leclerc',  2),
 ('RES', 'Reserve Driver', NULL);

INSERT INTO races (season, round_no, track_id, race_date, status)
SELECT 2026, v.rnd, t.track_id, v.d::date, v.st
FROM (VALUES
 (1,  'Albert Park (Melbourne)',             '2026-03-08', 'completed'),
 (2,  'Shanghai International Circuit',      '2026-03-15', 'completed'),
 (3,  'Suzuka',                              '2026-03-29', 'completed'),
 (4,  'Bahrain International Circuit',       '2026-04-12', 'cancelled'),
 (5,  'Jeddah Street Circuit',               '2026-04-19', 'cancelled'),
 (6,  'Miami International Autodrome',       '2026-05-03', 'completed'),
 (7,  'Circuit Gilles-Villeneuve (Montreal)','2026-05-24', 'completed'),
 (8,  'Circuit de Monaco',                   '2026-06-07', 'completed'),
 (9,  'Circuit de Barcelona-Catalunya',      '2026-06-14', 'completed'),
 (10, 'Red Bull Ring',                       '2026-06-28', 'completed'),
 (11, 'Silverstone',                         '2026-07-05', 'completed'),
 (12, 'Spa-Francorchamps',                   '2026-07-19', 'completed'),
 (13, 'Hungaroring',                         '2026-07-26', 'completed'),
 (14, 'Zandvoort',                           '2026-08-23', 'completed'),
 (15, 'Monza',                               '2026-09-06', 'completed'),
 (16, 'Madring (Madrid)',                    '2026-09-13', 'completed'),
 (17, 'Baku City Circuit',                   '2026-09-26', 'completed'),
 (18, 'Marina Bay (Singapore)',              '2026-10-11', 'completed'),
 (19, 'Circuit of the Americas',             '2026-10-25', 'completed'),
 (20, 'Autodromo Hermanos Rodriguez',        '2026-11-01', 'completed'),
 (21, 'Interlagos',                          '2026-11-08', 'scheduled'),
 (22, 'Las Vegas Street Circuit',            '2026-11-21', 'scheduled'),
 (23, 'Lusail',                              '2026-11-29', 'scheduled'),
 (24, 'Yas Marina',                          '2026-12-06', 'scheduled')
) AS v(rnd, track, d, st)
JOIN tracks t ON t.name = v.track
ORDER BY v.rnd;

-- DUMMY practice results for race_id 15 (Monza). NOT real results. NULL = DNF
INSERT INTO results (race_id, driver_id, grid_pos, finish_pos) VALUES
 (15, 1, 1, 2),
 (15, 2, 2, 1),
 (15, 3, 3, 3),
 (15, 4, 4, NULL);

INSERT INTO stints (race_id, driver_id, stint_no, compound_id, start_lap, end_lap) VALUES
 (15, 2, 1, 2,  1, 26),
 (15, 2, 2, 3, 27, 53),
 (15, 1, 1, 2,  1, 22),
 (15, 1, 2, 3, 23, 53),
 (15, 3, 1, 1,  1, 15),
 (15, 3, 2, 2, 16, 36),
 (15, 3, 3, 3, 37, 53),
 (15, 4, 1, 2,  1, 12);
