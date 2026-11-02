#订单级宽表
DROP TABLE IF EXISTS order_level;
#1.建宽表
CREATE TABLE order_level (
  order_id            VARCHAR(32) PRIMARY KEY,
  customer_unique_id  VARCHAR(32),
  customer_state      CHAR(2),
  order_status        VARCHAR(15),
  purchase_ts         DATETIME,
  approve_ts          DATETIME,
  carrier_ts          DATETIME,
  delivered_ts        DATETIME,
  estimated_ts        DATETIME,
  item_cnt            INT,
  seller_cnt          INT,
  price_total         DECIMAL(12,2),
  freight_total       DECIMAL(12,2),
  pay_total           DECIMAL(12,2),
  review_score        DECIMAL(3,2),
  review_cnt          INT,
  delivery_days       DECIMAL(8,2),
  delay_days          DECIMAL(8,2),
  is_late             TINYINT,
  is_analysis_sample  TINYINT,
  KEY idx_purchase (purchase_ts),
  KEY idx_state (customer_state),
  KEY idx_sample (is_analysis_sample)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

#order_reviews里review_answer_timestamp存在一个0日期
#处置：把零日期清成 NULL（不删行）
SET SQL_SAFE_UPDATES = 0;
UPDATE order_reviews
SET review_answer_timestamp = NULL
WHERE CAST(review_answer_timestamp AS CHAR) IN
      ('0000-00-00 00:00:00', '0000-00-00');
SET SQL_SAFE_UPDATES = 1;

INSERT INTO order_level
SELECT
  o.order_id,
  c.customer_unique_id,
  c.customer_state,
  o.order_status,
  o.order_purchase_timestamp,
  o.order_approved_at,
  o.order_delivered_carrier_date,
  o.order_delivered_customer_date,
  o.order_estimated_delivery_date,
  COALESCE(i.item_cnt, 0),
  COALESCE(i.seller_cnt, 0),
  COALESCE(i.price_total, 0),
  COALESCE(i.freight_total, 0),
  COALESCE(p.pay_total, 0),
  r.review_score,
  COALESCE(r.review_cnt, 0),
  ROUND(TIMESTAMPDIFF(HOUR, o.order_purchase_timestamp, o.order_delivered_customer_date) / 24.0, 2),
  ROUND(TIMESTAMPDIFF(HOUR, o.order_estimated_delivery_date, o.order_delivered_customer_date) / 24.0, 2),
  CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END,
  CASE WHEN o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL THEN 1 ELSE 0 END
FROM orders o
LEFT JOIN customers c ON o.customer_id = c.customer_id
LEFT JOIN (SELECT order_id, COUNT(*) item_cnt, COUNT(DISTINCT seller_id) seller_cnt,
                  SUM(price) price_total, SUM(freight_value) freight_total
           FROM order_items GROUP BY order_id) i ON o.order_id = i.order_id
LEFT JOIN (SELECT order_id, SUM(payment_value) pay_total
           FROM order_payments GROUP BY order_id) p ON o.order_id = p.order_id
LEFT JOIN (SELECT order_id, review_score, review_cnt   #对于多评论订单，分数去最近一次
		   FROM (SELECT order_id,review_score,
				 ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY review_answer_timestamp DESC) AS rn,
				 COUNT(*)     OVER (PARTITION BY order_id) AS review_cnt
				 FROM order_reviews) t WHERE rn = 1
		  ) r ON o.order_id = r.order_id;

#2.验证
-- 1） 行数与样本量（预期：99,441 / 96,470 / 1.142 / 1.006）
SELECT COUNT(*) AS rows_cnt,
       SUM(is_analysis_sample) AS sample_cnt,
       ROUND(AVG(item_cnt),3) AS avg_items,
       ROUND(AVG(seller_cnt),3) AS avg_sellers
FROM order_level;
-- 2） 金额对账（预期：16,008,872.12 / 13,591,643.70 / 2,251,909.54）
SELECT ROUND(SUM(pay_total),2) AS gmv_total,
       ROUND(SUM(price_total),2) AS price_total,
       ROUND(SUM(freight_total),2) AS freight_total
FROM order_level;
-- 3） 抽样看 1 单多商品的长什么样（看 item_cnt=5 的单，确认 price_total 是不是 5 行之和，pay_total 是否只算一次。）
SELECT order_id, item_cnt, seller_cnt, price_total, freight_total, pay_total
FROM order_level ORDER BY item_cnt DESC LIMIT 5;
-- 4） 延误率的量级体检（预期：延误率在 5%~10% 之间，min_delay 应该是负数（提前送达，几十天）。）
SELECT SUM(is_late) AS late_cnt,
       ROUND(100*SUM(is_late)/SUM(is_analysis_sample), 2) AS late_rate,
       ROUND(MIN(delay_days),1) AS min_delay,
       ROUND(MAX(delay_days),1) AS max_delay
FROM order_level WHERE is_analysis_sample = 1;
-- 验证0时期消除
SELECT COUNT(*) AS left_zero
FROM order_reviews
WHERE CAST(review_answer_timestamp AS CHAR) = '0000-00-00 00:00:00';











