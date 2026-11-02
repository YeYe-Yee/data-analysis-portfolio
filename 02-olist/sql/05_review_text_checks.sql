-- =============================================================================
-- 05_review_text_checks.sql  ·  第 3.5 段：评论文本分析（SQL 侧可复现部分）
-- =============================================================================
-- 说明：
--   文本「分类」由 scripts/review_mining.py 完成（葡语关键词匹配，见脚本 PATTERNS）。
--   本文件只放**不依赖分类**、纯 SQL 就能复现的体检与偏差检验，用于给报告中的
--   「文本样本自选偏差」「评价时点偏差」两条结论提供独立证据。
--
--   两侧口径必须逐位对齐，否则报告里的分子分母会打架：
--     · 评价去重：每单取 review_answer_timestamp 最新一条（与 order_level 一致）
--     · 纳入标准：review_comment_message <> ''（不做 strip、不剔纯符号）
--   本文件跑出的 98,672 / 40,774 / 41.32% 应与脚本首屏打印完全一致。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. 语料规模：订单级去重后多少条评价，其中多少有正文
-- 预期：orders = 98,672  has_msg = 40,774  pct = 41.32
-- -----------------------------------------------------------------------------
WITH latest AS (
    SELECT order_id, review_score, review_comment_message,
           ROW_NUMBER() OVER (PARTITION BY order_id
                              ORDER BY review_answer_timestamp DESC) AS rn
    FROM order_reviews
)
SELECT COUNT(*)                                        AS orders,
       SUM(review_comment_message <> '')                AS has_msg,
       ROUND(100 * SUM(review_comment_message <> '') / COUNT(*), 2) AS msg_pct
FROM latest
WHERE rn = 1;

-- -----------------------------------------------------------------------------
-- 2. 自选偏差：写不写正文，跟评分强相关（分母=该评分档全部订单）
-- 预期：1★ 76.62% → 5★ 35.87%，U 型；1★ 覆盖率高出一倍以上
-- -----------------------------------------------------------------------------
WITH latest AS (
    SELECT order_id, review_score, review_comment_message,
           ROW_NUMBER() OVER (PARTITION BY order_id
                              ORDER BY review_answer_timestamp DESC) AS rn
    FROM order_reviews
)
SELECT review_score,
       COUNT(*)                                          AS orders,
       SUM(review_comment_message <> '')                  AS has_msg,
       ROUND(100 * SUM(review_comment_message <> '') / COUNT(*), 2) AS cover_pct
FROM latest
WHERE rn = 1
GROUP BY review_score
ORDER BY review_score;

-- -----------------------------------------------------------------------------
-- 3. 自选偏差的后果：文本样本的差评率是全样本的 1.8 倍
-- 预期：有文本 40,774 / 26.58%，无文本 57,898 / 6.31%，全样本 14.69%
-- 结论：文本只能用来做「组间对比」，不能用来推断「整体差评的原因构成」
-- -----------------------------------------------------------------------------
WITH latest AS (
    SELECT order_id, review_score, review_comment_message,
           ROW_NUMBER() OVER (PARTITION BY order_id
                              ORDER BY review_answer_timestamp DESC) AS rn
    FROM order_reviews
)
SELECT CASE WHEN review_comment_message <> '' THEN '1_有正文' ELSE '2_无正文' END AS grp,
       COUNT(*)                                          AS orders,
       SUM(review_score <= 2)                             AS bad_cnt,
       ROUND(100 * SUM(review_score <= 2) / COUNT(*), 2)  AS bad_pct,
       ROUND(AVG(review_score), 3)                        AS avg_score
FROM latest
WHERE rn = 1
GROUP BY grp
ORDER BY grp;

-- -----------------------------------------------------------------------------
-- 4. 评价时点：11.27% 的评价写在「送达之前」
--    这批记录解释了两件事：
--      (a) 送达订单的差评里为什么还有人写「没收到」——评价时确实还没收到；
--      (b) 为什么不能用「评价里的物流抱怨」直接推断「最终没送达」。
-- 预期：comparable = 38,902  early = 4,385  early_pct = 11.27
-- -----------------------------------------------------------------------------
WITH latest AS (
    SELECT order_id, review_score, review_comment_message, review_creation_date,
           ROW_NUMBER() OVER (PARTITION BY order_id
                              ORDER BY review_answer_timestamp DESC) AS rn
    FROM order_reviews
)
SELECT COUNT(*)                                                     AS comparable,
       SUM(l.review_creation_date < o.order_delivered_customer_date) AS early,
       ROUND(100 * SUM(l.review_creation_date < o.order_delivered_customer_date)
             / COUNT(*), 2)                                         AS early_pct
FROM latest l
JOIN orders o ON o.order_id = l.order_id
WHERE l.rn = 1
  AND l.review_comment_message <> ''
  AND o.order_delivered_customer_date IS NOT NULL
  AND l.review_creation_date IS NOT NULL
  AND CAST(l.review_creation_date AS CHAR) NOT LIKE '0000-00-00%';   -- 零日期 1 行

-- -----------------------------------------------------------------------------
-- 5. 对照锚点：分析样本内的差评总数与其中「有正文」的条数
--    文本侧第 4 节的分箱分母就是这个 9,234；若两处对不上，说明某一步 JOIN 炸了。
-- 预期：bad_with_delay = 12,272，bad_with_text = 9,234（评价覆盖率 75.24%）
-- -----------------------------------------------------------------------------
WITH latest AS (
    SELECT order_id, review_score, review_comment_message,
           ROW_NUMBER() OVER (PARTITION BY order_id
                              ORDER BY review_answer_timestamp DESC) AS rn
    FROM order_reviews
)
SELECT COUNT(*)                                              AS bad_with_delay,
       SUM(l.review_comment_message <> '')                    AS bad_with_text
FROM latest l
JOIN order_level o ON o.order_id = l.order_id
WHERE l.rn = 1
  AND l.review_score <= 2
  AND o.is_analysis_sample = 1
  AND o.delay_days IS NOT NULL;
