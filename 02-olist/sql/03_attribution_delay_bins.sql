#四段式第 2 段 —— 归因
#1.先看分布，再切箱子
#为什么不能直接分箱：delay_days 有长尾（最长迟到近 200 天）。
#如果按等宽切箱，最右边会出现“一箱只有 3 单”的噪音箱，差评率 100%/0% 乱跳；而左边“提前 20 天”会挤掉一大半样本。要先用分布定边界。
-- 1a 分布体检
SELECT COUNT(*)                                                    AS n,
       SUM(delay_days IS NULL)                                     AS null_cnt,
       ROUND(MIN(delay_days), 2)                                   AS min_d,
       ROUND(MAX(delay_days), 2)                                   AS max_d,
       ROUND(AVG(delay_days), 2)                                   AS avg_d,
       ROUND(100 * SUM(delay_days > 0) / COUNT(*), 2)              AS late_pct
FROM order_level
WHERE is_analysis_sample = 1;

#延迟率的口径不一样，这里是天，基线是秒，存在“刚好压在承诺日午夜之后几分钟送达”
#8.06% 来自 delay_days > 0，而 delay_days 被 ROUND(...,2) 保留两位小数——迟到不足 7.2 分钟（0.005 天）的单，四舍五入成 0.00，就不算迟到了
SELECT COUNT(*) AS n_gap,
       ROUND(MIN(delay_days),2) AS min_gap,
       ROUND(MAX(delay_days),2) AS max_gap
FROM order_level
WHERE is_analysis_sample = 1 AND is_late = 1 AND delay_days <= 0;

-- 1b 候选分箱的样本量（切点先粗，后面对迟到区间再细化到天）
SELECT CASE
         WHEN delay_days IS NULL    THEN '0_缺失(先排除)'
         WHEN delay_days <= -15     THEN '1_提前15天以上'
         WHEN delay_days <= -8      THEN '2_提前8~15天'
         WHEN delay_days <= -3      THEN '3_提前3~8天'
         WHEN delay_days <= 0       THEN '4_准时及提前3天内'
         WHEN delay_days <= 3       THEN '5_迟到1~3天'
         WHEN delay_days <= 7       THEN '6_迟到4~7天'
         WHEN delay_days <= 15      THEN '7_迟到8~15天'
         WHEN delay_days <= 30      THEN '8_迟到16~30天'
         ELSE                            '9_迟到30天以上'
       END                                                     AS delay_bin,
       COUNT(*)                                                AS orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)        AS pct
FROM order_level
WHERE is_analysis_sample = 1
GROUP BY delay_bin
ORDER BY delay_bin;

#2.分箱 × 差评率（按 16-1 结果调整切点）
#调整依据：迟到1~3天 有 2,624 单，拆成 1/2/3 天每天约 870 单，够用（拐点大概率就藏这里）；
#迟到16~30(1,016) 和 30+(359) 都 ≥200，保留不合并；左侧三箱各 ≥17,426，保留以便看单调性。
-- 2 延迟分箱 × 满意度（分母：有评分的订单）
SELECT b.bin_ord,
       ELT(b.bin_ord, '提前15天以上','提前8~15天','提前3~8天','准时及提前3天内',
                      '迟到1天','迟到2天','迟到3天','迟到4~7天','迟到8~15天',
                      '迟到16~30天','迟到30天以上')                AS delay_bin,
       COUNT(*)                                                    AS delivered,
       COUNT(b.review_score)                                       AS reviewed,
       ROUND(100*COUNT(b.review_score)/COUNT(*), 2)                AS review_cov_pct,
       SUM(b.review_score <= 2)                                    AS bad_cnt,
       ROUND(100*SUM(b.review_score <= 2)/COUNT(b.review_score),2) AS bad_rate_pct,
       ROUND(100*SUM(b.review_score = 1)/COUNT(b.review_score),2)  AS one_star_pct,
       ROUND(100*SUM(b.review_score = 5)/COUNT(b.review_score),2)  AS five_star_pct,
       ROUND(AVG(b.review_score), 3)                               AS avg_score
FROM (
  SELECT review_score,
         CASE WHEN delay_days <= -15 THEN 1
              WHEN delay_days <= -8  THEN 2
              WHEN delay_days <= -3  THEN 3
              WHEN delay_days <= 0   THEN 4
              WHEN delay_days <= 1   THEN 5
              WHEN delay_days <= 2   THEN 6
              WHEN delay_days <= 3   THEN 7
              WHEN delay_days <= 7   THEN 8
              WHEN delay_days <= 15  THEN 9
              WHEN delay_days <= 30  THEN 10
              ELSE 11 END AS bin_ord
  FROM order_level
  WHERE is_analysis_sample = 1
    AND delay_days IS NOT NULL
) b
GROUP BY b.bin_ord
ORDER BY b.bin_ord;

#3.迟到逐日曲线（把拐点钉到“第几天”）
#为什么必须拆：迟到4~7天 合并后是 61.59%，但里面有 4 天、7 天两种完全不同的体验——第 4 天可能只有 45%，第 7 天可能已经 70%。
#不拆开，报告里“3 天”这个阈值就说不圆。同时给“逐日增量 Δpp”，用来自动定位最陡的一格。
-- 3 迟到逐日曲线 + 逐日增量（拐点定位）
SELECT y.delay_bin,
       y.delivered,
       y.bad_rate_pct,
       ROUND(y.bad_rate_pct - LAG(y.bad_rate_pct) OVER (ORDER BY y.day_n), 2) AS delta_pp,
       y.one_star_pct,
       y.avg_score
FROM (
  SELECT t.day_n,
         CASE WHEN t.day_n = 0  THEN '迟到不足1天'
              WHEN t.day_n <= 15 THEN CONCAT('迟到满 ', t.day_n, ' 天')
              WHEN t.day_n = 16  THEN '迟到 16~30 天'
              ELSE '迟到 30 天以上' END                                 AS delay_bin,
         COUNT(*)                                                       AS delivered,
         ROUND(100*SUM(t.review_score<=2)/COUNT(t.review_score),2)       AS bad_rate_pct,
         ROUND(100*SUM(t.review_score=1)/COUNT(t.review_score),2)        AS one_star_pct,
         ROUND(AVG(t.review_score),3)                                   AS avg_score
  FROM (
    -- ⚠️ 边界必须用 `delay_days < 16`，不能写 `<= 15`
    -- 写成 `<= 15` 时，(15, 16) 这 150 单会掉进 "16~30" 箱，导致 "满15天" 只剩 9 单（恰好等于 15.00 的单）
    -- 实测：<=15 版 → 满15天 9 单 / 16~30 天 1,016 单；<16 版 → 满15天 159 单 / 16~30 天 866 单
    SELECT review_score,
           CASE WHEN delay_days < 16 THEN FLOOR(delay_days)
                WHEN delay_days <= 30 THEN 16
                ELSE 17 END AS day_n
    FROM order_level
    WHERE is_analysis_sample = 1 AND delay_days > 0
  ) t
  GROUP BY t.day_n
) y
ORDER BY y.day_n;

#4.按月重跑，确认“3 天悬崖”不是某个月的偶然
#要防的核心混淆是 2018-03（延误率 21.36%、评分 3.813 全年最低）——如果 3 天悬崖只在崩盘月出现，那结论就是“爆仓期的特殊现象”，不是普遍规律。
-- 4a 按月稳健性：3 天悬崖每月都在吗
SELECT DATE_FORMAT(purchase_ts,'%Y-%m')                              AS ym,
       COUNT(*)                                                      AS delivered,
       ROUND(100*SUM(CASE WHEN delay_days<=0 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days<=0 THEN review_score IS NOT NULL END), 2) AS bad_ontime,
       SUM(CASE WHEN delay_days>0 AND delay_days<1 THEN review_score IS NOT NULL END) AS n_lt1,
       ROUND(100*SUM(CASE WHEN delay_days>0 AND delay_days<1 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days>0 AND delay_days<1 THEN review_score IS NOT NULL END), 2) AS bad_lt1,
       SUM(CASE WHEN delay_days>=1 AND delay_days<3 THEN review_score IS NOT NULL END) AS n_1_2,
       ROUND(100*SUM(CASE WHEN delay_days>=1 AND delay_days<3 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days>=1 AND delay_days<3 THEN review_score IS NOT NULL END), 2) AS bad_1_2,
       SUM(CASE WHEN delay_days>=3 AND delay_days<7 THEN review_score IS NOT NULL END) AS n_3_6,
       ROUND(100*SUM(CASE WHEN delay_days>=3 AND delay_days<7 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days>=3 AND delay_days<7 THEN review_score IS NOT NULL END), 2) AS bad_3_6
FROM order_level
WHERE is_analysis_sample = 1 AND delay_days IS NOT NULL
GROUP BY ym
HAVING delivered > 500
ORDER BY ym;

#这一步不只是稳健性检验，它直接产出建议段的落点：哪些州“延误率高 × 悬崖伤害大”，就是物流资源该投的地方。
-- 4b-1 按州：延误率、悬崖形状、可投放优先级
SELECT customer_state                                                     AS st,
       COUNT(*)                                                           AS delivered,
       ROUND(100*SUM(delay_days > 0)/COUNT(*), 2)                         AS late_pct,
       ROUND(AVG(delivery_days), 1)                                       AS avg_days,
       ROUND(100*SUM(CASE WHEN delay_days<=0 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days<=0 THEN review_score IS NOT NULL END), 2) AS bad_ontime,
       ROUND(100*SUM(CASE WHEN delay_days>=1 AND delay_days<3 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days>=1 AND delay_days<3 THEN review_score IS NOT NULL END), 2) AS bad_1_2,
       ROUND(100*SUM(CASE WHEN delay_days>=3 AND delay_days<7 THEN review_score<=2 END)
                 / SUM(CASE WHEN delay_days>=3 AND delay_days<7 THEN review_score IS NOT NULL END), 2) AS bad_3_6,
       SUM(CASE WHEN delay_days>=3 AND delay_days<7 THEN review_score IS NOT NULL END) AS n_3_6
FROM order_level
WHERE is_analysis_sample = 1 AND delay_days IS NOT NULL
GROUP BY customer_state
HAVING n_3_6 >= 50
ORDER BY late_pct DESC;
-- 4b-2：去掉门槛，看全部 27 州
-- 4b-2 全部州（不设门槛）+ 跳档验证
SELECT customer_state                                                       AS st,
       COUNT(*)                                                             AS delivered,
       ROUND(100*SUM(delay_days > 0)/COUNT(*), 2)                           AS late_pct,
       ROUND(AVG(delivery_days), 1)                                         AS avg_days,
       ROUND(100*SUM(delay_days >= 3 AND delay_days < 7)/COUNT(*), 2)       AS pct_3_6,
       SUM(delay_days >= 3 AND delay_days < 7)                              AS n_3_6,
       SUM(delay_days >= 7)                                                 AS n_ge7,
       ROUND(100*SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score <= 2 END)
                 / SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score IS NOT NULL END), 2) AS bad_3_6,
       ROUND(100*SUM(CASE WHEN delay_days >= 7 THEN review_score <= 2 END)
                 / SUM(CASE WHEN delay_days >= 7 THEN review_score IS NOT NULL END), 2) AS bad_ge7
FROM order_level
WHERE is_analysis_sample = 1 AND delay_days IS NOT NULL
GROUP BY customer_state
ORDER BY late_pct DESC;

-- 4b-3 正文图：12 个州（3~6 天延迟订单 ≥30 单）
SELECT customer_state                                                       AS st,
       COUNT(*)                                                             AS delivered,
       ROUND(100 * SUM(delay_days > 0) / COUNT(*), 2)                       AS late_pct,
       ROUND(AVG(delivery_days), 1)                                         AS avg_days,
       ROUND(100 * SUM(CASE WHEN delay_days <= 0 THEN review_score <= 2 END)
                 / SUM(CASE WHEN delay_days <= 0 THEN review_score IS NOT NULL END), 2) AS bad_ontime,
       ROUND(100 * SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score <= 2 END)
                 / SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score IS NOT NULL END), 2) AS bad_3_6,
       ROUND(100 * SUM(delay_days >= 3 AND delay_days < 7) / COUNT(*), 2)   AS pct_3_6,
       SUM(delay_days >= 3 AND delay_days < 7)                              AS n_3_6
FROM order_level
WHERE is_analysis_sample = 1
  AND delay_days IS NOT NULL
GROUP BY customer_state
HAVING n_3_6 >= 30
ORDER BY late_pct DESC;


#4c：30 天以上为什么反而“没那么差”（两个假说各测一遍）
-- 4c：迟到 30 天以上为何"没那么差"——承诺失真 vs 退款挽回
SELECT grp,
       COUNT(*)                                                     AS orders,
       ROUND(AVG(t.promise_days), 1)                                AS avg_promise_days,
       ROUND(AVG(t.delivery_days), 1)                               AS avg_delivery_days,
       ROUND(AVG(t.price_total), 1)                                 AS avg_price,
       ROUND(AVG(t.diff), 2)                                        AS avg_diff,
       ROUND(100*SUM(ABS(t.diff) > 0.01)/COUNT(*), 2)               AS pct_mismatch,
       ROUND(100*SUM(t.review_score <= 2)/COUNT(t.review_score), 2)  AS bad_rate,
       ROUND(100*SUM(t.review_score = 5)/COUNT(t.review_score), 2)   AS five_star
FROM (
  SELECT CASE WHEN o.delay_days >= 30 THEN 'B_迟到30天以上' ELSE 'A_迟到16~30天' END AS grp,
         o.review_score, o.delivery_days, o.price_total,
         DATEDIFF(o.estimated_ts, o.purchase_ts)          AS promise_days,
         (o.price_total + o.freight_total - o.pay_total)  AS diff
  FROM order_level o
  WHERE o.is_analysis_sample = 1 AND o.delay_days >= 16
) t
GROUP BY grp;

SELECT SUM(delay_days >= 16)                      AS n_ge16,
       SUM(delay_days >= 16 AND delay_days < 17)  AS n_16_17,
       SUM(delay_days >= 17 AND delay_days < 30)  AS n_17_29,
       SUM(delay_days >= 30)                      AS n_ge30
FROM order_level
WHERE is_analysis_sample = 1;

#时间聚集检验
SELECT DATE_FORMAT(purchase_ts,'%Y-%m') AS ym,
       COUNT(*) AS orders,
       ROUND(100*SUM(review_score <= 2)/COUNT(review_score),2) AS bad_rate,
       ROUND(100*SUM(review_score = 5)/COUNT(review_score),2) AS five_star
FROM order_level
WHERE is_analysis_sample = 1 AND delay_days >= 30
GROUP BY ym
ORDER BY ym;

#5.分箱锚点（每次改动分箱逻辑后必须先跑这条，用无歧义的 SUM(条件) 当基准）
#预期：late_total = 7,773
#      n_le15 = 6,398   (0, 15] —— 注意 <=15 不含 (15,16)
#      n_15_16 = 150    (15, 16) —— 最容易漏掉的一档
#      n_ge16 = 1,225   [16, ∞)
#      n_ge30 = 360     [30, ∞)
#校验：n_le15 + n_15_16 + n_ge16 = 6,398 + 150 + 1,225 = 7,773 ✅
SELECT SUM(delay_days > 0)                                   AS late_total,
       SUM(delay_days > 0 AND delay_days <= 15)              AS n_le15,
       SUM(delay_days > 15 AND delay_days < 16)              AS n_15_16,
       SUM(delay_days >= 16)                                 AS n_ge16,
       SUM(delay_days >= 30)                                 AS n_ge30
FROM order_level
WHERE is_analysis_sample = 1;













