#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Olist 项目 · 文本统计的**离线复算**（不连 MySQL，只用 data/ 下的原始 CSV）

用途：给没有 MySQL 环境的人一条验证路径——不需要建库、不需要密码，
      只要 9 个原始 CSV 就能重算「评论文本挖掘」这一段的核心数字。

    python3 scripts/verify_text_offline.py

与 review_mining.py 的关系：
    - 共用同一套词表与分类逻辑（直接 `from review_mining import classify, norm`），
      因此不存在"两个版本的口径漂移"问题；
    - 两者的差别只在取数方式：本脚本在 Python 侧复刻了 SQL 的
      `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY review_answer_timestamp DESC)`。

关于 ±1 的差异（不是 bug，是并列排序）：
    MySQL 侧的订单级去重得到 98,672 条评价，本脚本得到 98,673 条。
    原因是极少数订单有多条评价、且 `review_answer_timestamp` 完全相同，
    SQL 的 ROW_NUMBER() 在并列时取哪一行由执行计划决定，而本脚本用 review_id 兜底排序。
    这 1 条的差别会把「迟到 3~6 天」与「迟到 7 天以上」两箱各挪动 1 单
    （745/1,761 vs 746/1,760），**合并口径的准时 vs 迟到对比完全不变**
    （25.24% vs 67.18%，+41.94pp，z=38.35）。
    报告与指标登记表以 MySQL 侧为准。

输出与 report/analysis_report.md 第 6 章逐项对应，便于逐行核对。
"""

import collections
import csv
import os
import sys
import unicodedata
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from review_mining import classify, norm, pct  # noqa: E402  复用同一套词表

DATA = os.path.join(HERE, "..", "data")


def dpad(s, width, right=False):
    """按显示宽度对齐（中文字符占 2 列），否则中英混排的表格会错位。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    pad = " " * max(0, width - w)
    return pad + s if right else s + pad


def ts(s):
    """CSV 时间戳 -> datetime；空值与 MySQL 零日期（0000-00-00）都返回 None。"""
    s = (s or "").strip()
    if not s or s.startswith("0000-00-00"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def load():
    # 评价表：每单取 review_answer_timestamp 最新一条（并列时按 review_id 兜底，保证可复现）
    latest = {}
    with open(os.path.join(DATA, "olist_order_reviews_dataset.csv"), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (ts(row["review_answer_timestamp"]) or datetime.min, row["review_id"])
            cur = latest.get(row["order_id"])
            if cur is None or key > cur[0]:
                latest[row["order_id"]] = (key, row)

    # 订单表：延迟天数与「是否在分析样本内」
    # 与 sql/01 对齐：delay_days = (送达 - 承诺) / 24h，保留 2 位；
    # is_analysis_sample = order_status='delivered' 且送达时间非空
    orders = {}
    with open(os.path.join(DATA, "olist_orders_dataset.csv"), encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            dv = ts(row["order_delivered_customer_date"])
            es = ts(row["order_estimated_delivery_date"])
            orders[row["order_id"]] = {
                "dv": dv,
                "delay": round((dv - es).total_seconds() / 86400, 2) if (dv and es) else None,
                "in_sample": 1 if (row["order_status"] == "delivered" and dv) else 0,
            }

    rows = []
    for oid, (_, r) in latest.items():
        o = orders.get(oid, {})
        msg = r["review_comment_message"] or ""
        t = norm(msg) if msg else ""
        rows.append({
            "score": int(r["review_score"]),
            "msg": msg,
            "h": classify(t) if t else {},
            "cr": ts(r["review_creation_date"]),
            "dv": o.get("dv"),
            "delay": o.get("delay"),
            "in_sample": o.get("in_sample", 0),
        })
    return rows


def main():
    rows = load()
    txt = [r for r in rows if r["msg"]]          # 纳入标准 = 正文非空，与 SQL <> '' 一致
    bad = [r for r in txt if r["score"] <= 2]   # 差评 = 1~2 星

    print("=" * 78)
    print("一、语料与自选偏差（对应报告 6.1）")
    print("=" * 78)
    print(f"  订单级去重评价 {len(rows):,}   有正文 {len(txt):,} ({pct(len(txt), len(rows)):.2f}%)"
          f"   差评文本 {len(bad):,}")
    cov = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        cov[r["score"]][1] += 1
        if r["msg"]:
            cov[r["score"]][0] += 1
    for s in sorted(cov):
        a, b = cov[s]
        print(f"    {s}★  订单 {b:>7,d}  有正文 {a:>7,d}  覆盖率 {pct(a, b):>6.2f}%")
    n_bad_all = sum(1 for r in rows if r["score"] <= 2)
    r_txt, r_all = pct(len(bad), len(txt)), pct(n_bad_all, len(rows))
    print(f"  有正文组差评率 {r_txt:.2f}%   全样本 {r_all:.2f}%   → {r_txt / r_all:.1f} 倍"
          f"（自选偏差：不能推断整体构成）")

    print("\n" + "=" * 78)
    print("二、差评文本的互斥归类（对应报告 6.2，n=%s）" % f"{len(bad):,}")
    print("=" * 78)
    combo = collections.Counter()
    for r in bad:
        keys = [k for k in ("LOGN", "QUAL", "SERV") if r["h"].get(k)]
        combo["0_未识别" if not keys else ("1_仅" + keys[0] if len(keys) == 1 else "+".join(keys))] += 1
    label = {"1_仅LOGN": "仅物流（抱怨）", "1_仅QUAL": "仅商品质量", "1_仅SERV": "仅服务/退款",
             "LOGN+SERV": "物流+服务", "QUAL+SERV": "质量+服务", "LOGN+QUAL": "物流+质量",
             "LOGN+QUAL+SERV": "三者都提", "0_未识别": "未识别"}
    for k in ["1_仅LOGN", "1_仅QUAL", "1_仅SERV", "LOGN+SERV", "QUAL+SERV",
              "LOGN+QUAL", "LOGN+QUAL+SERV", "0_未识别"]:
        print(f"  {dpad(label[k], 18)}{combo[k]:>7,d}  {pct(combo[k], len(bad)):>6.2f}%")
    for k, note in [("LOGN", "含抱怨物流（窄口径，结论用这个）"),
                    ("LOG", "提到物流（宽口径，含「送得快」等）"),
                    ("QUAL", "含商品质量")]:
        n = sum(1 for r in bad if r["h"].get(k))
        print(f"  {dpad(note, 40)}{n:>7,d}  {pct(n, len(bad)):>6.2f}%")

    print("\n" + "=" * 78)
    print("三、延迟 × 文本主题（对应报告 6.3，反向验证）")
    print("=" * 78)
    bins = [("准时或提前", lambda d: d <= 0), ("迟到不足1天", lambda d: 0 < d < 1),
            ("迟到满1-2天", lambda d: 1 <= d < 3), ("迟到满3-6天", lambda d: 3 <= d < 7),
            ("迟到7天以上", lambda d: d >= 7)]
    ba = [r for r in bad if r["in_sample"] == 1 and r["delay"] is not None]
    print(f"  分母（差评 + 有正文 + 有送达时间）：{len(ba):,}")
    print(f"  {dpad('分箱', 14)}{dpad('n', 9, True)}{dpad('抱怨物流', 11, True)}"
          f"{dpad('说没收到', 11, True)}{dpad('提质量', 10, True)}")
    for name, fn in bins:
        sub = [r for r in ba if fn(float(r["delay"]))]
        if not sub:
            continue
        k = {t: sum(1 for r in sub if r["h"].get(t)) for t in ("LOGN", "NR", "QUAL")}
        print(f"  {dpad(name, 14)}{len(sub):>9,d}{pct(k['LOGN'], len(sub)):>10.2f}%"
              f"{pct(k['NR'], len(sub)):>10.2f}%{pct(k['QUAL'], len(sub)):>9.2f}%")
    on = [r for r in ba if float(r["delay"]) <= 0]
    la = [r for r in ba if float(r["delay"]) > 0]
    k1 = sum(1 for r in on if r["h"].get("LOGN"))
    k2 = sum(1 for r in la if r["h"].get("LOGN"))
    p1, p2 = k1 / len(on), k2 / len(la)
    pooled = (k1 + k2) / (len(on) + len(la))
    se = (pooled * (1 - pooled) * (1 / len(on) + 1 / len(la))) ** 0.5
    print(f"\n  合并：准时 {pct(k1, len(on)):.2f}%（n={len(on):,}） vs 迟到 "
          f"{pct(k2, len(la)):.2f}%（n={len(la):,}）")
    print(f"  差值 {(p2 - p1) * 100:+.2f}pp，z = {(p2 - p1) / se:.2f}")
    q_on = sum(1 for r in on if r["h"].get("QUAL")) / len(on)
    q_la7 = [r for r in ba if float(r["delay"]) >= 7]
    q_7 = sum(1 for r in q_la7 if r["h"].get("QUAL")) / len(q_la7)
    print(f"  提商品质量：准时 {q_on * 100:.2f}% → 迟到 7 天以上 {q_7 * 100:.2f}%"
          f"（塌缩 {q_on / q_7:.1f} 倍；若延迟只是伪相关，此项应持平）")

    print("\n" + "=" * 78)
    print("四、评价时点偏差（对应报告 6.4）")
    print("=" * 78)
    valid = [r for r in txt if isinstance(r["cr"], datetime) and isinstance(r["dv"], datetime)]
    early = [r for r in valid if r["cr"] < r["dv"]]
    print(f"  可比样本 {len(valid):,}，评价早于送达 {len(early):,} = {pct(len(early), len(valid)):.2f}%")
    nr = [r for r in txt if r["h"].get("NR")]
    nr_e = [r for r in nr if isinstance(r["cr"], datetime) and isinstance(r["dv"], datetime)
            and r["cr"] < r["dv"]]
    print(f"  全部有正文评价中「明确说没收到」{len(nr):,} 条，其中早于送达 "
          f"{len(nr_e):,} = {pct(len(nr_e), len(nr)):.2f}%")
    print(f"  其中属于差评子集的 {sum(1 for r in ba if r['h'].get('NR')):,} 条"
          f"（分母不同，勿与 6.3 表直接相减）")


if __name__ == "__main__":
    main()
