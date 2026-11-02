#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Olist 巴西电商「物流延迟 -> 差评 -> 复购」项目 · 正文图表生成脚本

数据来源：本机 MySQL 库 `olist`（由 sql/01~04 构建）
输出目录：images/charts/c01~c05.png（150 dpi，白底，可直接放进报告）

用法：
    export MYSQL_PWD='你的密码'
    python3 scripts/plot_charts.py

环境变量（除密码外均有默认值）：
    MYSQL_HOST  MYSQL_PORT  MYSQL_USER  MYSQL_DB  MYSQL_PWD
密码不写进代码，未提供时交互输入。

依赖：matplotlib>=3.5, pymysql, numpy  （见 scripts/requirements.txt）
"""

import getpass
import logging
import os
import sys
from math import sqrt

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymysql

# PingFang SC 没有真正的 bold 字重，matplotlib 会刷 findfont 警告，静音
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

# ---------------------------------------------------------------- 全局样式

# 中文显示（macOS 优先 PingFang，其次 Hiragino / Arial Unicode）
plt.rcParams["font.sans-serif"] = [
    "PingFang SC", "Hiragino Sans GB", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"
]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"
plt.rcParams["axes.edgecolor"] = "#B0B7C3"
plt.rcParams["axes.linewidth"] = 0.8
plt.rcParams["xtick.color"] = "#4A5568"
plt.rcParams["ytick.color"] = "#4A5568"
plt.rcParams["text.color"] = "#2D3748"
plt.rcParams["axes.labelcolor"] = "#2D3748"

C_MAIN = "#2E4A7D"    # 主色（深蓝）
C_ACC = "#E07B39"     # 强调色（橙）
C_BAD = "#C0392B"     # 警示色（红）
C_GRAY = "#8A94A6"
C_LIGHT = "#D8DEE9"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "images", "charts")
os.makedirs(OUT, exist_ok=True)

SRC_NOTE = "数据源：Olist 巴西电商公开数据集 | 分析样本 96,470 单送达订单（2017-01 ~ 2018-08）"


# ---------------------------------------------------------------- 数据访问

def connect():
    pwd = os.environ.get("MYSQL_PWD") or getpass.getpass("MySQL 密码: ")
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=pwd,
        database=os.environ.get("MYSQL_DB", "olist"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _as_float(row):
    """MySQL 的 SUM/AVG 返回 Decimal，统一转 float，避免出现 Decimal 与 float 混合运算报错。"""
    from decimal import Decimal
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def query(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return [_as_float(r) for r in cur.fetchall()]


# ---------------------------------------------------------------- 绘图辅助

def style_ax(ax, ygrid=True):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if ygrid:
        ax.yaxis.grid(True, color=C_LIGHT, linewidth=0.7, zorder=0)
        ax.set_axisbelow(True)


def footer(fig, note=SRC_NOTE, dy=0.005):
    """页脚注。x 轴标签有旋转的图要传 dy=-0.08，否则会压住刻度文字。"""
    fig.text(0.01, dy, note, fontsize=7.5, color=C_GRAY, ha="left", va="bottom")


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.28, facecolor="white")
    plt.close(fig)
    print(f"  saved -> images/charts/{name}")


# ---------------------------------------------------------------- c01 延迟曲线

def chart_delay_curve(conn):
    rows = query(conn, """
        SELECT CASE WHEN delay_days < 16 THEN FLOOR(delay_days)
                    WHEN delay_days <= 30 THEN 16 ELSE 17 END AS day_n,
               COUNT(*)                                  AS delivered,
               COUNT(review_score)                       AS reviewed,
               SUM(review_score <= 2)                    AS bad,
               SUM(review_score = 1)                     AS one,
               SUM(review_score = 5)                     AS five,
               AVG(review_score)                         AS avg_score
        FROM order_level
        WHERE is_analysis_sample = 1 AND delay_days > 0
        GROUP BY day_n ORDER BY day_n
    """)
    base = query(conn, """
        SELECT COUNT(review_score) AS reviewed, SUM(review_score <= 2) AS bad
        FROM order_level WHERE is_analysis_sample = 1 AND delay_days <= 0
    """)[0]
    ontime_bad = 100.0 * base["bad"] / base["reviewed"]

    d = {r["day_n"]: r for r in rows}
    # x 轴：0~15 天等距，16~30 / >30 用更大间隔提示量级断裂
    xs, bad_pct, one_pct, labels = [], [], [], []
    for k in range(0, 16):
        if k not in d:
            continue
        xs.append(k)
        bad_pct.append(100.0 * d[k]["bad"] / d[k]["reviewed"])
        one_pct.append(100.0 * d[k]["one"] / d[k]["reviewed"])
        labels.append("≤1天" if k == 0 else f"{k}")
    for k, x, lab in ((16, 17.6, "16~30"), (17, 19.6, ">30")):
        xs.append(x)
        bad_pct.append(100.0 * d[k]["bad"] / d[k]["reviewed"])
        one_pct.append(100.0 * d[k]["one"] / d[k]["reviewed"])
        labels.append(lab)

    fig, ax = plt.subplots(figsize=(10.2, 5.6))
    style_ax(ax)

    ax.axhline(ontime_bad, color=C_GRAY, ls="--", lw=1.1, zorder=1)
    ax.text(20.3, ontime_bad + 2.4, f"全部准时/提前均值 {ontime_bad:.2f}%",
            fontsize=9, color=C_GRAY, ha="right")

    ax.plot(xs, bad_pct, "-o", color=C_BAD, lw=2.2, ms=5.5, label="差评率（1~2 星）", zorder=3)
    ax.plot(xs, one_pct, "-s", color=C_MAIN, lw=1.6, ms=4.5, alpha=0.85,
            label="一星率", zorder=3)

    # 逐点标注：位置微调过，避免压在折线或标记上
    label_off = {0: (-2, 8, "center", "bottom"), 1: (0, 7, "center", "bottom"),
                 2: (0, 7, "center", "bottom"), 3: (-7, 1, "right", "center"),
                 4: (0, 7, "center", "bottom"), 6: (0, 7, "center", "bottom"),
                 16: (0, -9, "center", "top")}
    for x, y in zip(xs, bad_pct):
        if x in label_off:
            dx, dy, ha, va = label_off[x]
            ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(dx, dy),
                        ha=ha, va=va, fontsize=8.6, color=C_BAD, fontweight="bold", zorder=5)

    ax.axvline(3, color=C_ACC, ls=":", lw=1.6, zorder=2)
    ax.annotate("迟到满 3 天\n差评率 50.4%（一天内 +16.1pp）",
                xy=(3, bad_pct[3]), xytext=(6.0, 26),
                fontsize=9.5, color=C_ACC, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=C_ACC, lw=1.2,
                                connectionstyle="arc3,rad=-0.25"))

    ax.annotate("双峰：一星 64.0% / 五星 13.2%\n（长尾幸存者，非“延迟越久越不气”）",
                xy=(19.6, bad_pct[-1]), xytext=(12.4, 92),
                fontsize=8.6, color=C_GRAY, ha="left",
                arrowprops=dict(arrowstyle="->", color=C_GRAY, lw=1.0,
                                connectionstyle="arc3,rad=0.25"))
    # 提示右侧两格是区间聚合，不是单日
    ax.axvline(15.9, color=C_LIGHT, lw=1.2, zorder=2)

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_xlabel("迟到天数（超过承诺送达日的天数）", fontsize=10.5, labelpad=8)
    ax.set_ylabel("差评率 / 一星率（%）", fontsize=10.5)
    ax.set_ylim(0, 100)
    ax.set_xlim(-0.6, 20.6)
    ax.set_title("延迟越久，差评率越高 —— 断点在“迟到满 3 天”",
                 fontsize=14.5, fontweight="bold", pad=26, loc="left")
    ax.text(0, 1.035, "按迟到天数分箱，分母为该箱内有评分的订单；右侧两格为区间聚合",
            transform=ax.transAxes, fontsize=9.5, color=C_GRAY)
    ax.legend(loc="upper left", frameon=False, fontsize=9.5)
    footer(fig)
    save(fig, "c01_delay_curve.png")
    return {"ontime_bad": ontime_bad, "d3": bad_pct[3], "d2": bad_pct[2],
            "d30plus": bad_pct[-1], "n_total": sum(r["delivered"] for r in rows)}


# ---------------------------------------------------------------- c02 州散点

def chart_state_scatter(conn):
    rows = query(conn, """
        SELECT customer_state AS st,
               COUNT(*)       AS delivered,
               ROUND(AVG(delivery_days), 1) AS avg_days,
               SUM(delay_days >= 3 AND delay_days < 7) AS n_3_6,
               100 * SUM(delay_days > 0) / COUNT(*)    AS late_pct,
               100 * SUM(CASE WHEN delay_days <= 0 THEN review_score <= 2 END)
                   / SUM(CASE WHEN delay_days <= 0 THEN review_score IS NOT NULL END) AS bad_ontime,
               100 * SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score <= 2 END)
                   / SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score IS NOT NULL END) AS bad_3_6
        FROM order_level
        WHERE is_analysis_sample = 1 AND delay_days IS NOT NULL
        GROUP BY customer_state
    """)
    nat = query(conn, """
        SELECT 100 * SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score <= 2 END)
                   / SUM(CASE WHEN delay_days >= 3 AND delay_days < 7 THEN review_score IS NOT NULL END) AS bad_3_6
        FROM order_level WHERE is_analysis_sample = 1 AND delay_days IS NOT NULL
    """)[0]["bad_3_6"]

    sel = [r for r in rows if r["n_3_6"] and r["n_3_6"] >= 30]
    sel.sort(key=lambda r: r["late_pct"])
    x = np.array([r["late_pct"] for r in sel], dtype=float)
    y = np.array([r["bad_3_6"] for r in sel], dtype=float)
    s = np.array([r["delivered"] for r in sel], dtype=float)
    r_pearson = float(np.corrcoef(x, y)[0, 1])

    fig, ax = plt.subplots(figsize=(9.6, 5.8))
    style_ax(ax)
    ax.grid(True, axis="x", color=C_LIGHT, linewidth=0.7, zorder=0)

    bubble = 30 + 900 * (s / s.max())
    ax.scatter(x, y, s=bubble, color=C_MAIN, alpha=0.55, edgecolor=C_MAIN, linewidth=1.2, zorder=3)

    ax.axhline(nat, color=C_ACC, ls="--", lw=1.3, zorder=2)
    ax.text(17.6, nat - 2.6, f"全国加权 {nat:.1f}%", fontsize=9, color=C_ACC, ha="left")

    # 标签按气泡半径外推，避免压在气泡上；大样本州直接写在气泡内
    for r, si in zip(sel, bubble):
        rad_pt = float(np.sqrt(si / np.pi))
        if r["delivered"] >= 8000:
            ax.annotate(r["st"], (r["late_pct"], r["bad_3_6"]), ha="center", va="center",
                        fontsize=9.6, color="white", fontweight="bold", zorder=5)
        else:
            ax.annotate(r["st"], (r["late_pct"], r["bad_3_6"]),
                        xytext=(0, rad_pt + 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9.2,
                        color=C_BAD if r["st"] == "RJ" else "#2D3748",
                        fontweight="bold" if r["st"] == "RJ" else "normal", zorder=5)

    ax.set_xlabel("该州延误率（%，迟到订单 / 全部送达订单）", fontsize=10.5, labelpad=8)
    ax.set_ylabel("“迟到 3~6 天”订单的差评率（%）", fontsize=10.5)
    ax.set_title("迟到 3~6 天的伤害是全国性的，与当地物流快慢无关",
                 fontsize=14.5, fontweight="bold", pad=30, loc="left")
    ax.text(0, 1.045,
            f"气泡大小 = 该州送达订单量；仅含“迟到 3~6 天”订单 ≥30 单的 12 个州；"
            f"延误率与差评率相关系数 r = {r_pearson:+.2f}",
            transform=ax.transAxes, fontsize=9.3, color=C_GRAY)

    ax.text(0.985, 0.03, "RJ：延误率非最高，但伤害全国最高\n→ 都会区用户对延误零容忍",
            transform=ax.transAxes, fontsize=9, color=C_BAD, ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.45", fc="#FDF2F0", ec=C_BAD, lw=0.8))

    ax.set_ylim(50, 88)
    ax.set_xlim(3.4, 26.2)
    footer(fig, "数据源：Olist 公开数据集 | 12 州覆盖 89,289 / 96,470 = 92.6% 样本")
    save(fig, "c02_state_scatter.png")
    return {"states": len(sel), "r": r_pearson, "nat": nat,
            "bad_min": float(y.min()), "bad_max": float(y.max()),
            "late_min": float(x.min()), "late_max": float(x.max())}


# ---------------------------------------------------------------- c03 月度趋势

def chart_month_trend(conn):
    rows = query(conn, """
        SELECT DATE_FORMAT(purchase_ts, '%Y-%m') AS ym,
               COUNT(*)                          AS n,
               100 * AVG(is_late)                AS late_pct,
               AVG(review_score)                 AS avg_score
        FROM order_level
        WHERE is_analysis_sample = 1
        GROUP BY ym HAVING n > 500 ORDER BY ym
    """)
    ym = [r["ym"] for r in rows]
    late = [float(r["late_pct"]) for r in rows]
    score = [float(r["avg_score"]) for r in rows]
    xi = np.arange(len(ym))

    fig, ax = plt.subplots(figsize=(10.4, 5.4))
    style_ax(ax)

    bars = ax.bar(xi, late, width=0.66, color=C_MAIN, alpha=0.82, zorder=3, label="延误率（%，左轴）")
    peak = int(np.argmax(late))
    bars[peak].set_color(C_BAD)
    ax.axhline(np.mean(late), color=C_MAIN, ls=":", lw=1.1, zorder=2)
    ax.text(0.3, np.mean(late) + 0.9, f"月度均值 {np.mean(late):.1f}%",
            fontsize=8.8, color=C_MAIN, ha="left")

    ax.set_ylabel("延误率（%）", fontsize=10.5, color=C_MAIN)
    ax.set_ylim(0, max(late) * 1.55)
    ax.tick_params(axis="y", colors=C_MAIN)

    ax2 = ax.twinx()
    ax2.plot(xi, score, "-o", color=C_ACC, lw=2.2, ms=5, zorder=4, label="平均评分（右轴）")
    ax2.set_ylabel("平均评分", fontsize=10.5, color=C_ACC)
    ax2.tick_params(axis="y", colors=C_ACC)
    ax2.set_ylim(3.6, 4.5)
    for side in ("top", "left"):
        ax2.spines[side].set_visible(False)

    ax.annotate(f"{late[peak]:.2f}%", xy=(peak, late[peak]), xytext=(0, 7),
                textcoords="offset points", ha="center", fontsize=9.5,
                color=C_BAD, fontweight="bold", zorder=6)
    ax.text(0.42, 0.955,
            f"{ym[peak]}：延误率 {late[peak]:.2f}%（全年最高），平均分 {score[peak]:.3f}（全年最低）",
            transform=ax.transAxes, fontsize=9.2, color=C_BAD, va="top",
            bbox=dict(boxstyle="round,pad=0.4", fc="#FDF2F0", ec=C_BAD, lw=0.8))

    ax.set_xticks(xi)
    ax.set_xticklabels(ym, rotation=45, ha="right", fontsize=8.6)
    ax.set_title("2018-03 是最严重的履约崩盘月：延误率 21.36%、评分 3.813（均为全年最值）",
                 fontsize=13.6, fontweight="bold", pad=26, loc="left")
    ax.text(0, 1.035, "仅含月订单量 >500 的 20 个月；2016 年与 2018-09 之后因数据残缺已裁剪",
            transform=ax.transAxes, fontsize=9.3, color=C_GRAY)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False, fontsize=9.2)
    footer(fig, dy=-0.085)
    save(fig, "c03_month_trend.png")
    return {"peak": ym[peak], "peak_late": late[peak], "peak_score": score[peak],
            "months": len(ym), "avg_late": float(np.mean(late))}


# ---------------------------------------------------------------- c04 复购对比

def chart_repeat(conn):
    over = query(conn, """
        SELECT first_is_late, COUNT(*) AS persons, SUM(repeat_strict) AS reps
        FROM customer_level
        WHERE in_cohort = 1 AND first_status = 'delivered' AND first_delay_days IS NOT NULL
        GROUP BY first_is_late ORDER BY first_is_late
    """)
    cells = query(conn, """
        SELECT first_is_late,
               CASE WHEN first_review_score <= 2 THEN '差评'
                    WHEN first_review_score >= 4 THEN '好评' ELSE '中评' END AS rv,
               COUNT(*) AS persons, SUM(repeat_strict) AS reps
        FROM customer_level
        WHERE in_cohort = 1 AND first_status = 'delivered' AND first_delay_days IS NOT NULL
        GROUP BY first_is_late, rv
    """)

    o = {r["first_is_late"]: r for r in over}
    n_late, x_late = o[1]["persons"], o[1]["reps"]
    n_ont, x_ont = o[0]["persons"], o[0]["reps"]
    p_late, p_ont = x_late / n_late, x_ont / n_ont
    p_pool = (x_late + x_ont) / (n_late + n_ont)
    se_pool = sqrt(p_pool * (1 - p_pool) * (1 / n_late + 1 / n_ont))
    diff = (p_ont - p_late) * 100
    z = (p_ont - p_late) / se_pool
    ci_lo, ci_hi = (p_ont - p_late - 1.96 * se_pool) * 100, (p_ont - p_late + 1.96 * se_pool) * 100
    mde = 2.8 * se_pool * 100

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 5.0),
                                   gridspec_kw={"width_ratios": [1, 1.55], "wspace": 0.32})

    # 左：两组对比 + 个体 95% CI
    style_ax(ax1)
    vals = [p_ont * 100, p_late * 100]
    errs = [1.96 * sqrt(p * (1 - p) / n) * 100 for p, n in ((p_ont, n_ont), (p_late, n_late))]
    bars = ax1.bar([0, 1], vals, width=0.52, color=[C_MAIN, C_BAD], alpha=0.88, zorder=3)
    ax1.errorbar([0, 1], vals, yerr=errs, fmt="none", ecolor="#2D3748", capsize=6, lw=1.2, zorder=4)
    for b, v, n, e in zip(bars, vals, (n_ont, n_late), errs):
        ax1.text(b.get_x() + b.get_width() / 2, v + e + 0.12, f"{v:.2f}%",
                 ha="center", fontsize=11.5, fontweight="bold", color="#2D3748")
        ax1.text(b.get_x() + b.get_width() / 2, 0.08, f"n = {n:,}",
                 ha="center", fontsize=8.8, color="white")
    ax1.set_xticks([0, 1])
    ax1.set_xticklabels(["首单准时", "首单延迟"], fontsize=10.5)
    ax1.set_ylabel("复购率（%）", fontsize=10.5)
    ax1.set_ylim(0, 3.9)
    ax1.set_title("首单延迟 → 复购率 −30.8%", fontsize=12, fontweight="bold", pad=10, loc="left")
    ax1.text(0.5, 3.62, f"Δ = −{diff:.2f}pp   z = {z:.2f}   p < 0.001",
             ha="center", fontsize=10, color=C_BAD, fontweight="bold")
    ax1.text(0.5, 3.35, f"95% CI [{ci_lo:.2f}, {ci_hi:.2f}]pp", ha="center", fontsize=9, color=C_GRAY)

    # 右：延迟 × 评分 六格
    style_ax(ax2)
    order = ["好评", "中评", "差评"]
    get = {(r["first_is_late"], r["rv"]): r for r in cells}
    w = 0.36
    for i, (flag, color, label) in enumerate(((0, C_MAIN, "首单准时"), (1, C_BAD, "首单延迟"))):
        hs, ns = [], []
        for rv in order:
            r = get.get((flag, rv))
            hs.append(100.0 * r["reps"] / r["persons"] if r else 0)
            ns.append(r["persons"] if r else 0)
        pos = np.arange(len(order)) + (i - 0.5) * w
        ax2.bar(pos, hs, width=w, color=color, alpha=0.86, zorder=3, label=label)
        for p, h, n in zip(pos, hs, ns):
            ax2.text(p, h + 0.05, f"{h:.2f}%", ha="center", fontsize=9, color="#2D3748")
            ax2.text(p, 0.07, f"{n:,}", ha="center", fontsize=7.6, color="white")
    ax2.set_xticks(np.arange(len(order)))
    ax2.set_xticklabels(["首单好评 (4~5★)", "首单中评 (3★)", "首单差评 (1~2★)"], fontsize=10)
    ax2.set_ylabel("复购率（%）", fontsize=10.5)
    ax2.set_ylim(0, 3.9)
    ax2.set_title("延迟有独立效应：晚到但满意 ≈ 准时但不满意",
                  fontsize=12, fontweight="bold", pad=10, loc="left")
    ax2.legend(loc="upper right", frameon=False, fontsize=9.5)
    fig.text(0.545, -0.055,
             "注：“迟到 + 好评”2.12% ≈ “准时 + 差评”2.29%（差 0.17pp，z = 0.36，不显著）",
             fontsize=8.5, color=C_GRAY, ha="left", va="top")

    fig.suptitle("复购段：延迟使复购率显著下降，且不能被“满意度”解释",
                 fontsize=14.5, fontweight="bold", x=0.005, ha="left", y=1.045)
    footer(fig, "数据源：Olist 公开数据集 | cohort = 首单 ≤2018-02-28 且首单送达；复购 = 第二笔送达单间隔 ≥1 天")
    save(fig, "c04_repeat_compare.png")
    return {"p_ont": p_ont * 100, "p_late": p_late * 100, "diff": -diff, "z": z,
            "ci": (ci_lo, ci_hi), "mde": mde, "n_ont": n_ont, "n_late": n_late}


# ---------------------------------------------------------------- c05 cohort 删失

def chart_cohort(conn):
    rows = query(conn, """
        SELECT DATE_FORMAT(first_ts, '%Y-%m') AS ym,
               COUNT(*)                       AS persons,
               100 * AVG(repeat_strict)       AS rate
        FROM customer_level
        GROUP BY ym HAVING persons >= 200 ORDER BY ym
    """)
    ym = [r["ym"] for r in rows]
    rate = [float(r["rate"]) for r in rows]
    persons = [r["persons"] for r in rows]
    xi = np.arange(len(ym))
    cut = len([m for m in ym if m <= "2018-02"])

    fig, ax = plt.subplots(figsize=(10.2, 5.2))
    style_ax(ax)

    ax.bar(xi, persons, width=0.62, color=C_LIGHT, alpha=0.75, zorder=2, label="该月首单客户数（左轴）")
    ax.set_ylabel("首单客户数", fontsize=10.5, color=C_GRAY)
    ax.tick_params(axis="y", colors=C_GRAY)
    ax.set_ylim(0, max(persons) * 1.18)

    ax2 = ax.twinx()
    ax2.axvspan(cut - 0.5, len(ym) - 0.5, color="#FDECEA", zorder=1)
    ax2.plot(xi, rate, "-o", color=C_MAIN, lw=2.3, ms=5.5, zorder=4, label="该月 cohort 复购率（右轴）")
    ax2.axvline(cut - 0.5, color=C_BAD, ls="--", lw=1.3, zorder=3)
    ax2.set_ylabel("复购率（%）", fontsize=10.5, color=C_MAIN)
    ax2.tick_params(axis="y", colors=C_MAIN)
    ax2.set_ylim(0, 6.2)
    for side in ("top", "left"):
        ax2.spines[side].set_visible(False)

    ax2.text(cut - 0.55, 5.85, "纳入分析的 cohort 边界 2018-02-28 →",
             fontsize=8.8, color=C_BAD, ha="right", va="top")
    ax2.text(cut + 2.3, 4.15, "观察窗不足 180 天\n（右删失，不用于组间对比）",
             fontsize=8.8, color=C_BAD, ha="center", va="center", linespacing=1.5)

    ax2.annotate(f"{ym[-1]}\n{rate[-1]:.2f}%", xy=(len(ym) - 1, rate[-1]),
                 xytext=(9, 2), textcoords="offset points",
                 fontsize=8.8, color=C_BAD, ha="left", va="center")
    ax.set_xlim(-0.9, len(ym) + 1.1)

    ax.set_xticks(xi)
    ax.set_xticklabels(ym, rotation=45, ha="right", fontsize=8.6)
    ax.set_title("按首单月份看复购率：2018 年那条下滑是“删失”，不是“体验变差”",
                 fontsize=14.2, fontweight="bold", pad=26, loc="left")
    ax.text(0, 1.035, "复购 = 第二笔送达单间隔 ≥1 天；只用观察窗 ≥231 天的 cohort（首单 ≤2018-02-28）做组间对比",
            transform=ax.transAxes, fontsize=9.3, color=C_GRAY)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False, fontsize=9.2)
    footer(fig, dy=-0.085)
    save(fig, "c05_cohort_censor.png")
    return {"first": (ym[0], rate[0]), "last": (ym[-1], rate[-1]),
            "cohort_max": ym[cut - 1], "months": len(ym)}


# ---------------------------------------------------------------- 主流程

def main():
    conn = connect()
    print("已连接 MySQL，开始生成图表 ...\n")

    r1 = chart_delay_curve(conn)
    print(f"  c01 校验：准时基线 {r1['ontime_bad']:.2f}% | 满2天 {r1['d2']:.2f}% | "
          f"满3天 {r1['d3']:.2f}% | >30天 {r1['d30plus']:.2f}% | 迟到总数 {r1['n_total']:,}")

    r2 = chart_state_scatter(conn)
    print(f"  c02 校验：{r2['states']} 州 | 相关系数 r={r2['r']:+.3f} | 全国 {r2['nat']:.2f}% | "
          f"州值域 {r2['bad_min']:.2f}~{r2['bad_max']:.2f}% | 延误率 {r2['late_min']:.2f}~{r2['late_max']:.2f}%")

    r3 = chart_month_trend(conn)
    print(f"  c03 校验：{r3['months']} 个月 | 峰值 {r3['peak']} 延误 {r3['peak_late']:.2f}% "
          f"评分 {r3['peak_score']:.3f} | 月均延误 {r3['avg_late']:.2f}%")

    r4 = chart_repeat(conn)
    print(f"  c04 校验：准时 {r4['p_ont']:.2f}% (n={r4['n_ont']:,}) vs 迟到 {r4['p_late']:.2f}% "
          f"(n={r4['n_late']:,}) | Δ={r4['diff']:.2f}pp | z={r4['z']:.2f} | "
          f"CI [{r4['ci'][0]:.2f}, {r4['ci'][1]:.2f}] | MDE {r4['mde']:.2f}pp")

    r5 = chart_cohort(conn)
    print(f"  c05 校验：{r5['months']} 个 cohort | 首月 {r5['first'][0]} {r5['first'][1]:.2f}% | "
          f"末月 {r5['last'][0]} {r5['last'][1]:.2f}% | cohort 截止 {r5['cohort_max']}")

    conn.close()
    print(f"\n全部完成，输出目录：{OUT}")


if __name__ == "__main__":
    try:
        main()
    except pymysql.err.OperationalError as e:
        print(f"数据库连接失败：{e}\n请检查 MYSQL_PWD / MYSQL_USER / MYSQL_DB", file=sys.stderr)
        sys.exit(1)
