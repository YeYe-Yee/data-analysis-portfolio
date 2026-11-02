# Olist 数据集 数据字典

版本 v1.0 ｜ 2026-11-01 ｜ 库 `olist` ｜ 字符集 `utf8mb4`

> 约定：✅ 表示该字段可直接用于指标计算；⚠️ 表示存在已知陷阱，使用前必读；🔑 主键；🔗 外键（逻辑关联，未建物理约束）。

## 1. customers（99,441 行）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| customer_id | VARCHAR(32) | 否 | 🔑 主键。⚠️ **每单唯一**，与 orders 严格 1:1，不能用来识别人、不能算复购 |
| customer_unique_id | VARCHAR(32) | 否 | ✅ 真人唯一标识（96,096 个）。复购率、留存、LTV 必须用此字段 |
| customer_zip_code_prefix | VARCHAR(5) | 否 | 🔗 邮编前 5 位。⚠️ 必须保持 VARCHAR 以保留前导零（`00979`）；JOIN 目标为 `geolocation_zip` |
| customer_city | VARCHAR(50) | 否 | 城市名，全部小写且去重音（`sao paulo`），不可直接展示给业务方 |
| customer_state | CHAR(2) | 否 | 巴西州缩写，共 27 个取值（SP/RJ/MG/RS/PR/SC/BA/DF/ES/GO/PE/CE/PA/MT/MA/MS/PB/PI/RN/AL/SE/TO/RO/AM/AC/AP/RR） |

## 2. orders（99,441 行）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| order_id | VARCHAR(32) | 否 | 🔑 主键，全表唯一 |
| customer_id | VARCHAR(32) | 否 | 🔗 → customers，无孤儿记录 |
| order_status | VARCHAR(15) | 否 | ✅ 8 种取值：delivered 97.02%、shipped 1.11%、canceled 0.63%、unavailable 0.61%、invoiced 0.32%、processing 0.30%、created 5 单、approved 2 单。⚠️ 分析延迟只能取 delivered |
| order_purchase_timestamp | DATETIME | 否 | ✅ 下单时间，全项目**主时间轴**。范围 2016-09-04 ~ 2018-10-17 |
| order_approved_at | DATETIME | **是** | 支付审批通过。⚠️ 缺失 160 行（0.16%）；**1,359 行晚于揽收时间**（业务真实倒置） |
| order_delivered_carrier_date | DATETIME | **是** | 交承运商揽收。⚠️ 缺失 1,783 行（1.79%） |
| order_delivered_customer_date | DATETIME | **是** | ✅ 送达客户，**延迟计算终点**。⚠️ 缺失 2,965 行（2.98%）；有 8 单状态=delivered 但此字段为空 |
| order_estimated_delivery_date | DATETIME | 否 | ✅ 承诺送达日，**零缺失**。延迟 = 实际送达 − 此日期，正值=延误 |

## 3. order_items（112,650 行，1.142 行/单）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| order_id | VARCHAR(32) | 否 | 🔑🔗 复合主键之一 → orders |
| order_item_id | INT | 否 | 🔑 复合主键之一，同单内序号 1..n。⚠️ 它不是全局自增 ID |
| product_id | VARCHAR(32) | 否 | 🔗 → products |
| seller_id | VARCHAR(32) | 否 | 🔗 → sellers。⚠️ 一单可含多个卖家，按卖家汇总时订单会被重复计数 |
| shipping_limit_date | DATETIME | 否 | 卖家承诺发货截止时间 |
| price | DECIMAL(10,2) | 否 | ✅ 该行商品单价。可 SUM，但**不可当作订单金额**（一单多行会重复） |
| freight_value | DECIMAL(10,2) | 否 | ✅ **行级运费**（该行商品对应的运费），非订单级、非按金额分摊。已用 6 条查询验证：同单同 SKU 多行运费 100% 相同（7,088 组）；单件运费在 1~6 件区间稳定于 18~20 BRL，不随件数下降；订单运费随件数线性增长（1 件 20.37 → 6 件 116.81）；`SUM(price)+SUM(freight)` 与支付额对账差额集中在 0。**结论：`SUM(freight_value)` 即订单实付运费，不存在重复计费。** ⚠️ 383 行（0.34%）为 0（卖家包邮），包邮时同 SKU 各行同时为 0 |

## 4. order_payments（103,886 行，1.045 笔/单）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| order_id | VARCHAR(32) | 否 | 🔑🔗 复合主键之一 |
| payment_sequential | INT | 否 | 🔑 复合主键之一，同一单的支付序号（多卡/多方式时 >1） |
| payment_type | VARCHAR(20) | 否 | ✅ credit_card / boleto / voucher / debit_card / not_defined |
| payment_installments | INT | 否 | 分期数，1 = 一次性付清。⚠️ 存在 0 值（异常） |
| payment_value | DECIMAL(10,2) | 否 | ✅ 该笔支付金额。全表合计 16,008,872.12，比商品+运费口径高 1.04% |

## 5. order_reviews（99,223 行）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| review_id | VARCHAR(32) | 否 | ⚠️ **非唯一，重复 814 行（0.82%）**&#8203;，不可作主键；JOIN 前须按 order_id 去重或取最新 |
| order_id | VARCHAR(32) | 否 | 🔗 → orders，无孤儿记录。约 99.2% 的订单有评价 |
| review_score | TINYINT | 否 | ✅ 1~5 分，**满意度核心指标**。⚠️ 不可加，只能取均值或分布；差评定义为 ≤2 |
| review_comment_title | VARCHAR(100) | **是** | 评论标题，大量为空，且含换行/特殊符号 |
| review_comment_message | TEXT | **是** | 评论正文，**仅 41.32% 非空**（订单级去重后 40,774 / 98,672），最长 208 字符；含约 5,496 个内嵌换行，任何按行处理的方式都会出错。⚠️ **不可用于判送达**：11.27% 的评价写在送达之前（见 D-19） |
| review_creation_date | DATETIME | 否 | 问卷发出时间，时间部分基本为 00:00:00（仅精确到日） |
| review_answer_timestamp | DATETIME | 否 | 问卷回答时间，精确到秒。回复时长 = 此字段 − creation_date |

## 6. products（32,951 行）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| product_id | VARCHAR(32) | 否 | 🔑 主键 |
| product_category_name | VARCHAR(50) | **是** | 🔗 → category_translation。⚠️ 610 行为空（1.85%）；另有 2 个品类无翻译，共影响 623 个商品 |
| product_name_lenght | INT | **是** | ⚠️ **原始字段名拼写错误**（length → lenght），保留原样，勿"修正"以免破坏可复现性 |
| product_description_lenght | INT | **是** | ⚠️ 同上拼写错误 |
| product_photos_qty | INT | **是** | 商品图片数量，可用于"图片数 → 转化"分析 |
| product_weight_g | INT | **是** | 重量（克）。⚠️ 存在 0 值，计算运费相关性时需剔除 |
| product_length_cm | INT | **是** | 长度（厘米） |
| product_height_cm | INT | **是** | 高度（厘米） |
| product_width_cm | INT | **是** | 宽度（厘米） |

## 7. sellers（3,095 行）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| seller_id | VARCHAR(32) | 否 | 🔑 主键 |
| seller_zip_code_prefix | VARCHAR(5) | 否 | 🔗 → geolocation_zip。⚠️ 7 个卖家（0.23%）无匹配坐标 |
| seller_city | VARCHAR(50) | 否 | 城市名，小写去重音 |
| seller_state | CHAR(2) | 否 | 州缩写，取值域同 customers |

## 8. category_translation（71 行）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| product_category_name | VARCHAR(50) | 否 | 🔑 主键，葡语品类名 |
| product_category_name_english | VARCHAR(50) | 否 | 英文品类名。⚠️ 未覆盖 `portateis_cozinha_e_preparadores_de_alimentos`（10 商品）与 `pc_gamer`（3 商品），需在视图 `v_products` 中补映射 |

## 9. geolocation_zip（19,010 行，派生表）

由原始 `geolocation`（1,000,163 行、无主键、52.6 行/邮编）聚合而成，已剔除 42 行巴西境外坐标。

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| zip_code_prefix | VARCHAR(5) | 否 | 🔑 主键，邮编前 5 位 |
| lat | DECIMAL(11,8) | 是 | 该邮编下有效坐标的纬度均值。范围 −33.69 ~ 4.48 |
| lng | DECIMAL(11,8) | 是 | 经度均值。范围 −72.92 ~ −34.80 |
| city | VARCHAR(50) | 是 | 取该邮编下 MIN(city)，同一邮编存在多城市名时仅保留一个 |
| state | CHAR(2) | 是 | 取 MIN(state) |
| n_points | INT | 否 | 聚合前该邮编的坐标点数，均值 52.6。⚠️ 可用于评估坐标可信度（点数越少越可疑） |

## 10. order_level（订单级宽表，99,441 行 · 派生）

由 `orders` + `customers` + `order_items` + `order_payments` + `order_reviews` 聚合而成，是第 1、2 段的唯一底表。
所有一对多表**先 `GROUP BY order_id` 再 JOIN**，避免 1.142×（商品）/1.006×（评价）双膨胀。

| 字段 | 类型 | 说明 |
|---|---|---|
| order_id | VARCHAR(32) | 🔑 主键 |
| customer_unique_id | VARCHAR(32) | 真人标识，来自 customers |
| customer_state | CHAR(2) | 收货州 |
| order_status | VARCHAR(15) | 订单状态 |
| purchase_ts / approve_ts / carrier_ts / delivered_ts / estimated_ts | DATETIME | 五个时间戳，`delivered_ts`、`estimated_ts` 均可能为空 |
| item_cnt / seller_cnt | INT | 商品行数 / 卖家数；**775 单无商品行**（`item_cnt=0`），其中多为 canceled/unavailable |
| price_total / freight_total / pay_total | DECIMAL(12,2) | 商品额、运费、支付额。`pay_total` 来自 payments，**与 price+freight 并非恒等**（voucher、分期导致少数订单有差额）；4 单无支付记录（`pay_total=0`） |
| review_score | DECIMAL(3,2) | ⚠️ 多评价订单取 `review_answer_timestamp` **最新一条**（不取平均，评分为序数） |
| review_cnt | INT | 该订单的评价条数（>1 说明有重复评价） |
| delivery_days | DECIMAL(8,2) | 下单 → 送达，`TIMESTAMPDIFF(HOUR)/24.0`，保留两位小数 |
| delay_days | DECIMAL(8,2) | 送达 − 承诺日，**正=迟到**，负=提前，平均 −11.16 天 |
| is_late | TINYINT | 秒级比较 `delivered_ts > estimated_ts`，用于**延误率**（8.11%） |
| is_analysis_sample | TINYINT | 1 = `delivered` 且 `delivered_ts` 非空，**n = 96,470**。物理保留全量，用标记筛选 |

> ⚠️ 延误率两个口径：`is_late` 8.11%（7,826 单）/ `delay_days>0` 8.06%（7,773 单），差 53 单来自 `delay_days` 四舍五入到 2 位小数（迟到不足 7.2 分钟被抹平）。**报告延误率用 `is_late`，分箱分析用 `delay_days`，须注明。**

## 11. customer_level（客户级宽表，96,096 行 · 派生）

由 `orders` + `customers` + `order_reviews` 按 `customer_unique_id` 聚合，是第 3 段（复购）的唯一底表。

| 字段 | 类型 | 说明 |
|---|---|---|
| customer_unique_id | VARCHAR(32) | 🔑 主键 |
| first_ts / first_status / first_state | — | **首单**（按 `purchase_ts` 最早）的时间、状态、收货州 |
| first_delivery_days / first_delay_days / first_is_late | — | 首单的送达时长、延迟天数、是否迟到 |
| first_review_score | BIGINT | 首单评分（多评价取最新一条） |
| orders_all / orders_delivered | BIGINT | 全部订单数 / 送达订单数 |
| repeat_flag | INT | 宽松复购：`orders_delivered >= 2`（2,801 人，2.91%） |
| repeat_strict | INT | ✅ **严格复购（报告采用）**：`orders_delivered >= 2` 且 `gap_to_second >= 1` 天（1,967 人，**2.05%**） |
| gap_to_second | INT | 首单 → 第二单的**日历日**间隔（`DATEDIFF`，非 `TIMESTAMPDIFF`） |
| followup_days | INT | 首单距数据末点（2018-10-17）的天数 |
| in_cohort | INT | 1 = 首单 ≤ 2018-02-28，观察窗 ≥ 231 天（55,459 人） |

> ⚠️ 853 个客户的“第二单”与首单在 24 小时内、834 个在同一日历日，属**下单拆单/支付重试**而非真实复购，必须用 `repeat_strict`。详见审计 D-16。

## 12. 文本标签体系（`scripts/review_mining.py`）

非数据库表，而是对 `order_reviews.review_comment_message` 施加的**葡语关键词多标签**，用于回答"差评在骂什么"。分类前统一做小写化 + 去重音 + 去标点（使 `Não recebi!` 与 `nao recebi` 同形）。

| 标签 | 含义 | 典型词根 | 用途 |
|---|---|---|---|
| `LOG` | 物流/时效（提及） | entrega, prazo, chegou, receb*, correio, rastreio, frete | 主题构成（宽口径）|
| `LOGN` | 物流（**明确抱怨**） | nao receb*, nao cheg*, atras*, demor*, aguardando, extravi* | 结论口径（窄口径，排除中性词）|
| `NR` | 明确说"没收到" | nao receb*, nao cheg*, ainda nao, extravi* | 区分"晚到"与"压根没到" |
| `QUAL` | 商品质量/损坏/错发 | defeit*, quebrad*, errad*, faltand*, qualidade, embalage* | 与物流争夺"差评主因" |
| `SERV` | 客服/退款/退换 | atendiment*, reembols*, estorn*, devoluc*, cancel* | 识别"没人管"类抱怨 |
| `POS` | 正向表达 | recomendo, otim*, excelente, rapid*, satisfeit* | 好评对照 |

**两条口径纪律**：①`LOG` 与 `LOGN` 不可混用——前者含"entrega rápida"这类中性/正面提及，后者才是抱怨；②所有"占差评的比例"分母是**该箱有正文的差评**，不是全部差评（文本覆盖率仅 41.32%，见 D-19）。

## 13. 字段级已知陷阱速查

| 陷阱 | 涉及字段 | 后果 |
|---|---|---|
| 1:1 伪关系 | customers.customer_id | 误当客户维度，复购率低估 3.4% |
| 非唯一"主键" | order_reviews.review_id | JOIN 后订单数虚增 |
| 行级金额当订单金额 | order_items.price / freight_value | 重复计费，多商品订单金额翻倍 |
| 不可加指标被 SUM | review_score | 无意义数值 |
| 时间倒置 | approved_at vs carrier_date | 时长出现负数（1,359 行） |
| 前导零丢失 | *_zip_code_prefix | JOIN 大面积失配 |
| 命名拼写错误 | product_name_lenght | 引用时报字段不存在 |
| 内嵌换行 | review_comment_message | 按行解析数据错位 |
| 把文本当"是否送达"的证据 | review_comment_message | 11.27% 的评价写在送达前，"没收到"多为等待焦虑，见 D-19 |
| 同日多单当复购 | 首单→第二单间隔 | 复购率虚高 30%（2.91% vs 2.05%），见 D-16 |
| 分箱边界开闭不清 | `delay_days <= 15` vs `< 16` | (15,16) 的 150 单被并入“16~30”箱，见 D-17 |
| 除法小数位截断 | `1/n`、方差与 SE 计算 | MySQL 默认只保留 4 位小数增量，SE 低估、z 虚高（3.78 vs 3.34），见 D-18 |
| 延误率两种口径 | `is_late` vs `delay_days>0` | 8.11% vs 8.06%，报告须注明用哪个 |
