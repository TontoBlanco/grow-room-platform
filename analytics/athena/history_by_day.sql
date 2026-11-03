-- analytics/athena/history_by_day.sql
-- Console form of the Grow-room History dashboard.
-- Grafana sends the same statements with the two date literals replaced by
-- the time-picker macros ${__from:date:YYYY-MM-DD} and ${__to:date:YYYY-MM-DD}
-- (dashboard timezone is UTC, matching the dt= partition ship_readings writes).
--
-- Both forms compare the partition column dt to constants. Athena can skip
-- every other day. Do not wrap dt in a function.
--
-- Stage bands (null-safe):
--   flower, flowering, bloom -> 1.2 to 1.5 kPa
--   null, blank, veg, and anything else -> 0.8 to 1.2 kPa (veg)
--
-- Cost: Athena on-demand is $5 per TB scanned in us-west-2. A day of
-- ship_readings.py (one reading a minute, batches of 10) is a few hundred
-- KB of JSON. Thirty days is on the order of 10-20 MB, well under a cent
-- per query. The workgroup bytes_scanned_cutoff_per_query is 1 GiB, about
-- half a cent, and then Athena cancels the query. Six panels on the
-- dashboard are six such queries. Leave the board's auto-refresh off.

-- Daily avg/min/max VPD, temperature, and RH, plus the stage band.
SELECT dt,
       count(*) AS samples,
       round(avg(vpd_kpa), 3) AS avg_vpd,
       round(min(vpd_kpa), 3) AS min_vpd,
       round(max(vpd_kpa), 3) AS max_vpd,
       round(avg(temperature_c), 2) AS avg_temp_c,
       round(min(temperature_c), 2) AS min_temp_c,
       round(max(temperature_c), 2) AS max_temp_c,
       round(avg(humidity_percent), 1) AS avg_rh,
       round(min(humidity_percent), 1) AS min_rh,
       round(max(humidity_percent), 1) AS max_rh,
       round(
         100.0 * count_if(
           vpd_kpa BETWEEN
             CASE
               WHEN lower(trim(coalesce(stage, ''))) IN ('flower', 'flowering', 'bloom') THEN 1.2
               ELSE 0.8
             END
             AND
             CASE
               WHEN lower(trim(coalesce(stage, ''))) IN ('flower', 'flowering', 'bloom') THEN 1.5
               ELSE 1.2
             END
         ) / count(*),
         1
       ) AS pct_in_band
FROM grow_room_telemetry.readings
WHERE dt >= date_format(current_date - interval '30' day, '%Y-%m-%d')
  AND dt <= date_format(current_date, '%Y-%m-%d')
GROUP BY dt
ORDER BY dt;

-- Readings per source per day. Null and blank source count as unknown.
SELECT dt,
       coalesce(nullif(trim(source), ''), 'unknown') AS source,
       count(*) AS samples
FROM grow_room_telemetry.readings
WHERE dt >= date_format(current_date - interval '30' day, '%Y-%m-%d')
  AND dt <= date_format(current_date, '%Y-%m-%d')
GROUP BY dt, coalesce(nullif(trim(source), ''), 'unknown')
ORDER BY dt, source;
