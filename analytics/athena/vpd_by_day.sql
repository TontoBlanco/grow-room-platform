-- analytics/athena/vpd_by_day.sql
-- Daily VPD summary. The 0.8-1.2 kPa band is the veg default and stays
-- fixed so this query remains comparable. Shipped rows may also include
-- `stage` (seedling, veg, flower, late_flower). Older objects leave it
-- null. This query does not select stage.
-- Stage-aware daily history is analytics/athena/history_by_day.sql
-- and the Grow-room History dashboard.
SELECT dt,
       count(*)                                                        AS samples,
       round(avg(vpd_kpa), 2)                                          AS avg_vpd,
       round(min(vpd_kpa), 2)                                          AS min_vpd,
       round(max(vpd_kpa), 2)                                          AS max_vpd,
       round(100.0 * count_if(vpd_kpa BETWEEN 0.8 AND 1.2) / count(*), 1) AS pct_in_band,
       round(avg(temperature_c), 1)                                    AS avg_temp_c,
       round(avg(humidity_percent), 1)                                 AS avg_rh
FROM grow_room_telemetry.readings
WHERE dt >= date_format(current_date - interval '14' day, '%Y-%m-%d')
  AND source = 'homeassistant'
GROUP BY dt
ORDER BY dt;
