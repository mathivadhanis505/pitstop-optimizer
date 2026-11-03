DROP FUNCTION IF EXISTS plan_strategies(INT, INT);

CREATE FUNCTION plan_strategies(p_track INT, p_weather INT)
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
cw AS (   -- tyres allowed in this weather, with their numbers
    SELECT c.compound_id, c.name, c.hardness_rank,
           x.pace_offset_s, x.deg_per_lap_s, x.base_life_laps
    FROM compound_weather x
    JOIN compounds c ON c.compound_id = x.compound_id
    WHERE x.weather_id = p_weather
),
combo AS (  -- recursive: build every tyre sequence, 1 to 4 stints
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
valid_combo AS (  -- apply the weather's rules
    SELECT f.stops, f.ids
    FROM full_combo f CROSS JOIN wx
    WHERE f.stops >= wx.min_stops
      AND ( NOT wx.requires_two_compounds
            OR (SELECT COUNT(DISTINCT d.cid) FROM unnest(f.ids) AS d(cid)) >= 2 )
),
stint_calc AS (  -- one row per stint, even split of the race distance
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
scored AS (      -- one row per strategy
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
