#四段式第 3 段——复购
#1.定义与可算性体检（三条查询）
-- ① 复购率复核：两种口径必核对
-- 口径A：只算送达单（与基线 3.00% 一致）
SELECT COUNT(*)                  AS persons,
       SUM(oc >= 2)              AS repeat_persons,
       ROUND(100*SUM(oc >= 2)/COUNT(*), 2) AS repeat_rate
FROM (SELECT customer_unique_id, COUNT(*) AS oc
      FROM order_level
      WHERE is_analysis_sample = 1
      GROUP BY customer_unique_id) t;
-- 口径B：全部订单都算（"再次下单"这个行为发生了，不管最终是否送达）
SELECT COUNT(*)                  AS persons,
       SUM(oc >= 2)              AS repeat_persons,
       ROUND(100*SUM(oc >= 2)/COUNT(*), 2) AS repeat_rate
FROM (SELECT c.customer_unique_id, COUNT(*) AS oc
      FROM orders o
      JOIN customers c ON o.customer_id = c.customer_id
      GROUP BY c.customer_unique_id) t;

-- ② 复购间隔：决定观察窗该留多长
-- 第1单 → 第2单 的间隔分布（用送达单，避免取消单拉长时间）
WITH per AS (
  SELECT customer_unique_id, purchase_ts,
         ROW_NUMBER() OVER (PARTITION BY customer_unique_id ORDER BY purchase_ts) AS rn
  FROM order_level
  WHERE is_analysis_sample = 1
)
SELECT COUNT(*)                              AS repeat_pairs,
       ROUND(AVG(gap_days), 0)               AS avg_gap,
       ROUND(MIN(gap_days), 0)               AS min_gap,
       ROUND(MAX(gap_days), 0)               AS max_gap,
       ROUND(100*AVG(gap_days <= 30), 1)     AS pct_within_30d,
       ROUND(100*AVG(gap_days <= 90), 1)     AS pct_within_90d,
       ROUND(100*AVG(gap_days <= 180), 1)    AS pct_within_180d
FROM (SELECT a.customer_unique_id,
             TIMESTAMPDIFF(DAY, a.purchase_ts, b.purchase_ts) AS gap_days
      FROM per a
      JOIN per b ON a.customer_unique_id = b.customer_unique_id AND b.rn = 2
      WHERE a.rn = 1) t;

#min_gap = 0 是个信号：有客户同一天下两单，这很可能是同一笔购物车被不同卖家拆单，不是真复购。跑一下：
SELECT SUM(gap_days = 0) AS same_day,
       SUM(gap_days <= 1) AS within_1d,
       SUM(gap_days <= 3) AS within_3d,
       COUNT(*) AS pairs
FROM (SELECT TIMESTAMPDIFF(DAY, a.purchase_ts, b.purchase_ts) AS gap_days
      FROM (SELECT customer_unique_id, purchase_ts,
                   ROW_NUMBER() OVER (PARTITION BY customer_unique_id ORDER BY purchase_ts) rn
            FROM order_level WHERE is_analysis_sample=1) a
      JOIN (SELECT customer_unique_id, purchase_ts,
                   ROW_NUMBER() OVER (PARTITION BY customer_unique_id ORDER BY purchase_ts) rn
            FROM order_level WHERE is_analysis_sample=1) b
        ON a.customer_unique_id=b.customer_unique_id AND a.rn=1 AND b.rn=2) t;


-- ③ cohort 表：把右删失的证据摆出来
-- 按首单月份看复购率（这张表就是"为什么必须截断"的证据）
SELECT DATE_FORMAT(first_ts, '%Y-%m')     AS cohort_ym,
       COUNT(*)                           AS persons,
       ROUND(100*SUM(oc >= 2)/COUNT(*), 2) AS repeat_rate
FROM (SELECT customer_unique_id,
             MIN(purchase_ts) AS first_ts,
             COUNT(*)         AS oc
      FROM order_level
      WHERE is_analysis_sample = 1
      GROUP BY customer_unique_id) t
GROUP BY cohort_ym
ORDER BY cohort_ym;

#2：建第 3 段唯一底表
#先取一个日期（复购只能发生在这个时点之前）
SELECT MIN(order_purchase_timestamp) AS min_ts,
       MAX(order_purchase_timestamp) AS max_ts
FROM orders;

DROP TABLE IF EXISTS customer_level;

CREATE TABLE customer_level AS
SELECT t.customer_unique_id,
       t.first_ts,
       t.first_status,
       t.first_state,
       ROUND(TIMESTAMPDIFF(HOUR, t.first_ts, t.first_delivered_ts)/24.0, 2)              AS first_delivery_days,
       ROUND(TIMESTAMPDIFF(HOUR, t.first_estimated_ts, t.first_delivered_ts)/24.0, 2)    AS first_delay_days,
       CASE WHEN t.first_delivered_ts > t.first_estimated_ts THEN 1 ELSE 0 END           AS first_is_late,
       t.first_review_score,
       t.orders_all,
       t.orders_delivered,
       CASE WHEN t.orders_delivered >= 2 THEN 1 ELSE 0 END                               AS repeat_flag,
       DATEDIFF('2018-10-17', t.first_ts)                                                AS followup_days,
       CASE WHEN t.first_ts <= '2018-02-28 23:59:59' THEN 1 ELSE 0 END                   AS in_cohort,
       DATEDIFF(t.second_ts, t.first_ts)                    							 AS gap_to_second,
	   CASE WHEN t.orders_delivered >= 2 AND DATEDIFF(t.second_ts, t.first_ts) >= 1 THEN 1 ELSE 0 END       AS repeat_strict
FROM (
  SELECT x.customer_unique_id,
         MIN(x.purchase_ts)                                   AS first_ts,
         MAX(CASE WHEN x.rn = 1 THEN x.order_status END)      AS first_status,
         MAX(CASE WHEN x.rn = 1 THEN x.state END)             AS first_state,
         MAX(CASE WHEN x.rn = 1 THEN x.delivered_ts END)      AS first_delivered_ts,
         MAX(CASE WHEN x.rn = 1 THEN x.estimated_ts END)      AS first_estimated_ts,
         MAX(CASE WHEN x.rn = 1 THEN x.review_score END)      AS first_review_score,
         COUNT(*)                                             AS orders_all,
         SUM(x.delivered_ts IS NOT NULL)                      AS orders_delivered,
         MAX(CASE WHEN x.rn = 2 THEN x.purchase_ts END)        AS second_ts
  FROM (
    SELECT c.customer_unique_id, c.customer_state AS state,
           o.order_status,
           o.order_purchase_timestamp         AS purchase_ts,
           o.order_delivered_customer_date    AS delivered_ts,
           o.order_estimated_delivery_date    AS estimated_ts,
           r.review_score,
           ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id
                              ORDER BY o.order_purchase_timestamp) AS rn
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    LEFT JOIN (SELECT order_id, review_score FROM
                 (SELECT order_id, review_score,
                         ROW_NUMBER() OVER (PARTITION BY order_id
				  ORDER BY review_answer_timestamp DESC) rn2
                  FROM order_reviews) z WHERE rn2 = 1) r
           ON r.order_id = o.order_id
  ) x
  GROUP BY x.customer_unique_id
) t;

ALTER TABLE customer_level ADD PRIMARY KEY (customer_unique_id);
CREATE INDEX idx_cl_cohort ON customer_level (in_cohort, repeat_flag);

#校验
SELECT SUM(repeat_flag)                                       AS rep_loose,
       SUM(repeat_strict)                                     AS rep_strict,
       ROUND(100*AVG(repeat_flag),2)                          AS rate_loose,
       ROUND(100*AVG(repeat_strict),2)                        AS rate_strict,
       SUM(repeat_flag = 1 AND repeat_strict = 0)             AS killed_same_day
FROM customer_level;

-- ⚠️ 以下这条用 `repeat_flag`（宽松口径，含同日拆单），已被 `repeat_strict` 取代，
--    保留仅为复现"口径修正前后"的对比，不要拿它下结论。
SELECT first_is_late,
       COUNT(*)                          AS persons,
       SUM(repeat_flag)                  AS repeat_persons,
       ROUND(100*AVG(repeat_flag), 2)    AS repeat_rate
FROM customer_level
WHERE in_cohort = 1 AND first_status = 'delivered' AND first_delay_days IS NOT NULL
GROUP BY first_is_late;

#① 严格定义的两行表
SELECT first_is_late,
       COUNT(*)                          AS persons,
       SUM(repeat_strict)                AS repeat_persons,
       ROUND(100*AVG(repeat_strict), 2)  AS repeat_rate
FROM customer_level
WHERE in_cohort = 1 AND first_status = 'delivered' AND first_delay_days IS NOT NULL
GROUP BY first_is_late;

#四格表（延迟 × 评分）
SELECT first_is_late,
       CASE WHEN first_review_score <= 2 THEN '1_差评(1-2)'
            WHEN first_review_score >= 4 THEN '2_好评(4-5)'
            ELSE '3_中评(3)' END          AS rv,
       COUNT(*)                           AS persons,
       ROUND(100*AVG(repeat_strict), 2)   AS repeat_rate
FROM customer_level
WHERE in_cohort = 1 AND first_status = 'delivered'
  AND first_delay_days IS NOT NULL
GROUP BY first_is_late, rv
ORDER BY first_is_late, rv;

-- 3：一条稳健性检验（做完就收口）
#最大的混淆是地区——延迟集中在偏远州，而偏远州复购本来就低。按 SP / 非 SP 二分会暴露这个问题：
SELECT CASE WHEN first_state = 'SP' THEN '1_SP' ELSE '2_非SP' END AS region,
       first_is_late,
       COUNT(*)                            AS persons,
       SUM(repeat_strict)                  AS repeat_persons,
       ROUND(100*AVG(repeat_strict), 2)    AS repeat_rate
FROM customer_level
WHERE in_cohort = 1 AND first_status = 'delivered'
  AND first_delay_days IS NOT NULL AND first_state IS NOT NULL
GROUP BY region, first_is_late
ORDER BY region, first_is_late;

#4：显著性检验与统计功效（MDE）
#⚠️ MySQL 除法陷阱：`1/n` 只保留 div_precision_increment(默认 4) 位小数，
#   1/4263 会变成 0.0002，SE 被低估、z 被高估（实测 3.78 vs 正确 3.34）。
#   所有除法必须 `CAST(x AS DOUBLE)` 或写成 `1e0/n`。
WITH g AS (
  SELECT SUM(first_is_late = 1)                       AS n1,
         SUM(first_is_late = 1 AND repeat_strict = 1) AS x1,
         SUM(first_is_late = 0)                       AS n2,
         SUM(first_is_late = 0 AND repeat_strict = 1) AS x2
  FROM customer_level
  WHERE in_cohort = 1 AND first_status = 'delivered' AND first_delay_days IS NOT NULL
),
s AS (
  SELECT CAST(x1 AS DOUBLE)/n1 AS p1,
         CAST(x2 AS DOUBLE)/n2 AS p2,
         CAST(x1 + x2 AS DOUBLE)/(n1 + n2) AS pp,
         n1, n2,
         SQRT( (CAST(x1 + x2 AS DOUBLE)/(n1 + n2))
               * (1 - CAST(x1 + x2 AS DOUBLE)/(n1 + n2))
               * (1e0/n1 + 1e0/n2) )      AS se
  FROM g
)
SELECT ROUND(100*p1, 2)                 AS late_rate_pct,
       ROUND(100*p2, 2)                 AS ontime_rate_pct,
       ROUND(100*(p2 - p1), 2)          AS diff_pp,
       ROUND(100*se, 3)                 AS se_pp,
       ROUND((p2 - p1)/se, 2)           AS z,
       ROUND(100*(p2 - p1 - 1.96*se), 2) AS ci_low_pp,
       ROUND(100*(p2 - p1 + 1.96*se), 2) AS ci_high_pp,
       ROUND(100*(p2 - p1)/p2, 1)       AS rel_diff_pct,
       ROUND(100*2.8*se, 2)             AS mde_pp,
       ROUND(2.8*se/p2*100, 1)          AS mde_rel_pct
FROM s;
-- 预期：1.97 / 2.85 / 0.88 / 0.262 / 3.34 / 0.36 / 1.39 / 30.8 / 0.73 / 25.8
-- 解读：相对降幅 30.8%；z=3.34 (p≈0.0008) 显著；MDE=0.73pp，即只有大于 26% 的相对差异才能被检出














