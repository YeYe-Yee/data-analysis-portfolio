#基线指标（四段式第 1 段）
#1.规模与客单

SELECT COUNT(*) AS orders,
       ROUND(SUM(pay_total),2) AS gmv,
       ROUND(SUM(pay_total)/COUNT(*),2) AS aov,
       ROUND(SUM(freight_total),2) AS freight,
       ROUND(SUM(freight_total)/SUM(price_total)*100,2) AS freight_rate_pct
FROM order_level WHERE is_analysis_sample = 1;

#2.时效
SELECT ROUND(AVG(delivery_days),2) AS avg_days,
       ROUND(MAX(delivery_days),1) AS max_days,
       ROUND(AVG(is_late)*100,2) AS late_rate,
       ROUND(AVG(CASE WHEN is_late=1 THEN delay_days END),2) AS avg_late_days,
       ROUND(AVG(CASE WHEN is_late=0 THEN -delay_days END),2) AS avg_early_days
FROM order_level WHERE is_analysis_sample = 1;

-- P90 送达天数（窗口函数）
SELECT ROUND(MAX(CASE WHEN rn = CEIL(0.9*cnt) THEN delivery_days END),2) AS p90_days
FROM (SELECT delivery_days,
             ROW_NUMBER() OVER (ORDER BY delivery_days) rn,
             COUNT(*) OVER () cnt
      FROM order_level WHERE is_analysis_sample = 1) t;

#3.满意度
#由于重复评价可能存在不同的评分，评分是序数，不能取平均，现统一标准
#平均分、差评率（分母为有评分的订单）、评价覆盖率（分母为已送达单）
SELECT ROUND(AVG(review_score),3) AS avg_score,
       ROUND(100*SUM(review_score<=2)/COUNT(review_score),2) AS bad_rate,
       ROUND(100*COUNT(review_score)/COUNT(*),2) AS review_coverage
FROM order_level WHERE is_analysis_sample = 1;

SELECT review_score, COUNT(*) cnt,
       ROUND(100*COUNT(*)/SUM(COUNT(*)) OVER (),2) pct
FROM order_level WHERE is_analysis_sample=1 AND review_score IS NOT NULL
GROUP BY review_score ORDER BY review_score;

#4.复购
SELECT COUNT(*) AS persons,
       SUM(CASE WHEN oc >= 2 THEN 1 ELSE 0 END) AS repeat_persons,
       ROUND(100*SUM(CASE WHEN oc>=2 THEN 1 ELSE 0 END)/COUNT(*),2) AS repeat_rate,
       ROUND(AVG(oc),3) AS orders_per_person
FROM (SELECT customer_unique_id, COUNT(*) oc
      FROM order_level WHERE is_analysis_sample = 1
      GROUP BY customer_unique_id) t;

#5.月度趋势
SELECT DATE_FORMAT(purchase_ts,'%Y-%m') AS ym,
       COUNT(*) AS orders,
       ROUND(SUM(pay_total),2) AS gmv,
       ROUND(AVG(delivery_days),1) AS avg_days,
       ROUND(AVG(is_late)*100,2) AS late_rate,
       ROUND(AVG(review_score),3) AS avg_score
FROM order_level WHERE is_analysis_sample = 1
GROUP BY 1 HAVING orders > 100 ORDER BY 1;

#发现freight_value 为行级运费，SUM(freight_value) 等于订单实际运费，不重复计费。
#按件数看对账差额
-- 核心：按件数看"金额对账差额"
SELECT o.item_cnt,
       COUNT(*)                                                      AS orders,
       ROUND(AVG(o.freight_sum), 2)                                  AS avg_freight_sum,
       ROUND(AVG(o.freight_sum / o.item_cnt), 2)                     AS avg_freight_per_item,
       ROUND(AVG(ABS(o.price_sum + o.freight_sum - p.pay_total)), 2) AS avg_abs_diff,
       ROUND(100 * AVG(ABS(o.price_sum + o.freight_sum - p.pay_total) <= 0.01), 2) AS pct_exact
FROM (SELECT order_id, COUNT(*) item_cnt,
             SUM(price) price_sum, SUM(freight_value) freight_sum
      FROM order_items GROUP BY order_id) o
JOIN (SELECT order_id, SUM(payment_value) pay_total
      FROM order_payments GROUP BY order_id) p ON p.order_id = o.order_id
GROUP BY o.item_cnt
ORDER BY o.item_cnt;
#对账表：差额压在 0 附近、不随件数放大。

#挑 21 件那单 + 两个 3 件单，把“每行多少钱”和“整单付了多少”放同一屏幕上：
SELECT i.order_id, i.order_item_id, i.product_id,
       i.price, i.freight_value,
       SUM(i.price)         OVER (PARTITION BY i.order_id) AS order_price_sum,
       SUM(i.freight_value) OVER (PARTITION BY i.order_id) AS order_freight_sum,
       p.pay_total,
       ROUND(SUM(i.price) OVER (PARTITION BY i.order_id)
           + SUM(i.freight_value) OVER (PARTITION BY i.order_id) - p.pay_total, 2) AS diff
FROM order_items i
JOIN (SELECT order_id, SUM(payment_value) AS pay_total
      FROM order_payments GROUP BY order_id) p ON p.order_id = i.order_id
WHERE i.order_id IN (
        '8272b63d03f5f79c56e9e4120aec44ef',
        (SELECT order_id FROM order_items GROUP BY order_id
         HAVING COUNT(*) = 3 ORDER BY order_id LIMIT 1),
        (SELECT order_id FROM order_items GROUP BY order_id
         HAVING COUNT(*) = 3 ORDER BY order_id DESC LIMIT 1))
ORDER BY i.order_id, i.order_item_id;
#极端案例（21 件：31.80 货值 / 164.37 运费 / 逐笔相加分毫不差）。


