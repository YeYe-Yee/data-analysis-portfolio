#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Olist 巴西电商「物流延迟 -> 差评 -> 复购」项目 · 评论文本挖掘

回答三个问题：
    1. 差评用户在骂什么？（物流 / 商品质量 / 服务，各自的份额）
    2. 差评中的「物流提及率」是否随延迟天数上升？——这是对第 2 段归因的反向验证
    3. 文本样本存在多强的自选偏差？（写不写评论与评分高度相关，必须量化）

方法：葡萄牙语关键词/正则多标签分类。**不做情感极性打分**——本项目没有
标注语料，任何"情感分"都无法验证，因此只做"提及与否"这种可人工抽检的判断。

数据来源：本机 MySQL 库 `olist`
输出：控制台表格 + images/charts/c06_review_topics.png、c07_topic_by_delay.png

用法：
    export MYSQL_PWD='你的密码'
    python3 scripts/review_mining.py            # 跑全部统计 + 出图
    python3 scripts/review_mining.py --samples  # 额外打印每类抽检样本（人工验准）

依赖：matplotlib, pymysql（标准库完成文本处理，无需 pandas）
"""

import argparse
import collections
import getpass
import logging
import os
import random
import re
import unicodedata
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymysql

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

# ---------------------------------------------------------------- 全局样式

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

C_MAIN = "#2E4A7D"
C_ACC = "#E07B39"
C_BAD = "#C0392B"
C_GRAY = "#8A94A6"
C_LIGHT = "#D8DEE9"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "images", "charts")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- 关键词表
#
# 设计原则：
#   1. 全部用「词干 + \w*」而非完整词形，葡语动词变位多（atrasou/atrasado/atraso）
#   2. 匹配前先做 accent folding（atrasado / atrasádo 同形），并对小写化后的文本
#      去掉所有非字母数字字符，避免 "não" 被标点切断
#   3. 多标签：一条评论可同时提到物流和质量，不做强行互斥（互斥版本单独算）

PATTERNS = {
    # 物流 / 时效 / 收不到货
    "LOG": r"\b(nao recebi|nao chegou|nao foi entregue|nao veio|nao obtive|"
           r"ainda nao|ainda estou|ainda aguardo|estou aguardando|aguardando|esperando|"
           r"atras\w*|demor\w*|prazo|entreg\w*|receb\w*|chegou|chegar\w*|chegada|"
           r"correio\w*|rastre\w*|transportadora\w*|frete|extrav\w*|enviad\w*|postad\w*|"
           r"remetid\w*|logistica|encomenda\w*|aguard\w*|pontualidade|"
           r"nunca cheg\w*)\b",
    # 商品本身：质量、损坏、错发、缺件
    "QUAL": r"\b(defeit\w*|quebrad\w*|danific\w*|avariad\w*|riscad\w*|arranh\w*|manchad\w*|"
            r"mofad\w*|ferrugem|enferrujad\w*|amarelad\w*|suj[oa]|trincad\w*|rachad\w*|"
            r"incomplet\w*|faltand\w*|faltou|faltam|errad\w*|diferente|outro produto|"
            r"nao funciona\w*|nao liga|qualidade|fragil|embalage\w*|embalad\w*|"
            r"tamanho|dimens\w*|usado|recondicionad\w*|falsificad\w*|original|"
            r"amassad\w*|rasgad\w*|descostur\w*|detonad\w*|violad\w*|lacre|incorret\w*|"
            r"(enviaram|mandaram|trouxe) outro|so recebi|recebi apenas|recebi somente|"
            r"recebemos apenas|apenas um dos|metade do|somente um|somente uma|"
            r"recebi outro|recebi uma outra|molhad\w*|"
            r"veio (com )?(defeit\w*|problem\w*|risc\w*|manch\w*|quebrad\w*|"
            r"faltand\w*|peca\w*|errad\w*|diferente|outro\w*))\b",
    # 服务：客服、退款、退换、卖家、平台
    "SERV": r"\b(atendiment\w*|suporte|resposta|respond\w*|contato|reembols\w*|estorn\w*|"
            r"devoluc\w*|devolv\w*|troc\w*|cancel\w*|vendedor\w*|lojas?|nota fiscal|"
            r"empresa|sac|protocolo)\b",
    # 正向表达（用于对照：好评里提到物流通常是"送得快"）
    "POS": r"\b(recomendo|otim\w*|excelente|perfeit\w*|adorei|amei|gostei|satisfeit\w*|"
           r"parabens|maravilh\w*|lind\w*|top|super|rapid\w*|agil|confiavel|bom|boa)\b",
}

# 「物流抱怨」——比 LOG 更窄：只保留明确的负面表述，排除 "entrega"/"recebi"/"chegou"
# 这类中性词。LOG 做「提及率」，LOGN 做「抱怨率」，后者才是结论要用的口径。
PATTERNS["LOGN"] = (
    r"\b(nao receb\w*|nao cheg\w*|nao foi entregue|nao veio|nao obtive|nao entregue|"
    r"nao enviad\w*|nao enviar\w*|nunca cheg\w*|nao cumpr\w*|"
    r"n recebi|nao receb\w* entrega|quero meu produto|"
    r"ainda nao|ainda n |ainda estou|ainda aguardo|aguardando|esperando|"
    r"atras\w*|demor\w*|fora do prazo|passou do prazo|descumpr\w*|extrav\w*)\b"
)

# 「明确说没收到」——比 LOGN 更窄，用于区分"晚到"与"压根没到"
NOT_RECEIVED = (
    r"\b(nao receb\w*|nao cheg\w*|nao foi entregue|nao veio|"
    r"ainda nao receb\w*|ainda nao cheg\w*|ainda estou aguardando|"
    r"estou aguardando|aguardando|esperando|extrav\w*)\b"
)

RE_ = {k: re.compile(v) for k, v in PATTERNS.items()}
RE_NR = re.compile(NOT_RECEIVED)


def norm(s):
    """小写 + 去重音 + 去标点，使 'Não recebi!' 与 'nao recebi' 同形。"""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify(t):
    """返回多标签命中字典 + 是否明确未收到。"""
    h = {k: bool(RE_[k].search(t)) for k in RE_}
    h["NR"] = bool(RE_NR.search(t))
    return h


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


def query(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


# 每个订单取「最新一条评价」（与 order_level 的口径一致：814 行 review_id 重复 +
# 93 单多条评价，必须先去重，否则订单数会被放大）
SQL_REVIEWS = """
SELECT r.order_id, r.review_score, r.review_comment_message AS msg,
       CASE WHEN CAST(r.review_creation_date AS CHAR) LIKE '0000-00-00%'
            THEN NULL ELSE r.review_creation_date END AS review_creation_date,
       r.review_answer_timestamp,
       o.delay_days, o.is_late, o.delivered_ts, o.is_analysis_sample
FROM (
    SELECT order_id, review_score, review_comment_message,
           review_creation_date, review_answer_timestamp,
           ROW_NUMBER() OVER (PARTITION BY order_id
                              ORDER BY review_answer_timestamp DESC) AS rn
    FROM order_reviews
) r
LEFT JOIN order_level o ON o.order_id = r.order_id
WHERE r.rn = 1
"""


# ---------------------------------------------------------------- 工具

def pct(a, b):
    return 100.0 * a / b if b else float("nan")


def bar_row(label, vals, width=7):
    return f"  {label:<14s}" + "".join(f"{v:>{width}.2f}" for v in vals)


def wilson(k, n, z=1.96):
    """Wilson 区间：小样本比例比正态近似稳，报告里的 CI 用这个。"""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - r) / d * 100, (c + r) / d * 100)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true", help="打印每类抽检样本")
    ap.add_argument("--n-sample", type=int, default=6, help="每类抽检条数")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    conn = connect()
    rows = query(conn, SQL_REVIEWS)
    conn.close()

    # ---- 打标签
    for r in rows:
        r["t"] = norm(r["msg"]) if r["msg"] else ""
        r["h"] = classify(r["t"]) if r["t"] else {}
    # 纳入标准 = 正文非空（与 SQL 的 `review_comment_message <> ''` 完全一致）。
    # 其中约 180 条是纯符号/纯数字/纯空白正文，分类时必然落进「未识别」，不单独剔除，
    # 以保证 Python 与 SQL 两侧的样本量能逐位对上。
    txt = [r for r in rows if r["msg"]]

    print("=" * 78)
    print("一、语料体检：文本覆盖率与自选偏差")
    print("=" * 78)

    n_all = len(rows)
    n_txt = len(txt)
    print(f"  订单级评价（去重后）      {n_all:,}")
    print(f"  正文非空                  {n_txt:,}  ({pct(n_txt, n_all):.2f}%)")

    by_score = collections.defaultdict(lambda: [0, 0])  # score -> [有文本, 总数]
    for r in rows:
        s = int(r["review_score"])
        by_score[s][1] += 1
        if r["msg"]:
            by_score[s][0] += 1
    print("\n  「是否写正文」按评分分布（自选偏差的大小）：")
    print(f"  {'评分':<6s}{'订单数':>9s}{'有文本':>9s}{'覆盖率':>9s}   文本内占比")
    for s in sorted(by_score):
        a, b = by_score[s]
        print(f"  {s:<6d}{b:>9,d}{a:>9,d}{pct(a, b):>8.2f}%   {pct(a, n_txt):>7.2f}%")

    n_bad_txt = sum(1 for r in txt if int(r["review_score"]) <= 2)
    n_good_txt = sum(1 for r in txt if int(r["review_score"]) >= 4)
    print(f"\n  有文本组：差评率 {pct(n_bad_txt, n_txt):.2f}%  好评率 {pct(n_good_txt, n_txt):.2f}%")
    n_bad_all = sum(1 for r in rows if int(r["review_score"]) <= 2)
    print(f"  全样本　：差评率 {pct(n_bad_all, n_all):.2f}%  "
          f"→ 文本样本的差评率是全样本的 {pct(n_bad_txt, n_txt) / pct(n_bad_all, n_all):.1f} 倍")

    # ---- 二、主题命中率
    print("\n" + "=" * 78)
    print("二、四大主题命中率（多标签，分母=该评分档有正文的条数）")
    print("=" * 78)
    cnt = collections.defaultdict(collections.Counter)
    for r in txt:
        s = int(r["review_score"])
        cnt["_n"][s] += 1
        for k, v in r["h"].items():
            if v:
                cnt[k][s] += v
    scores = [1, 2, 3, 4, 5]
    print(bar_row("评分", scores, 9))
    print(bar_row("n", [cnt["_n"][s] for s in scores], 9))
    for k, name in [("LOG", "物流(提及)"), ("LOGN", "物流(抱怨)"), ("QUAL", "商品质量"),
                    ("SERV", "服务/退款"), ("NR", "明确未收到"), ("POS", "正向表达")]:
        print(bar_row(name, [pct(cnt[k][s], cnt["_n"][s]) for s in scores], 9))

    # ---- 三、差评的主题构成（互斥）
    print("\n" + "=" * 78)
    print("三、差评（1~2 星）文本到底是什么问题（互斥归类）")
    print("=" * 78)
    bad = [r for r in txt if int(r["review_score"]) <= 2]
    # 互斥归类用 LOGN（明确抱怨）而非 LOG（含 "chegou"/"recebi" 这类中性提及）——
    # 否则 "Chegou sujo e com a tinta grudenta"（质量抱怨）会被算进物流。
    combo = collections.Counter()
    for r in bad:
        h = r["h"]
        keys = [k for k in ("LOGN", "QUAL", "SERV") if h.get(k)]
        if not keys:
            combo["0_未识别"] += 1
        elif len(keys) == 1:
            combo[f"1_仅{keys[0]}"] += 1
        else:
            combo["+".join(keys)] += 1
    order = ["1_仅LOGN", "1_仅QUAL", "1_仅SERV", "LOGN+QUAL", "LOGN+SERV", "QUAL+SERV",
             "LOGN+QUAL+SERV", "0_未识别"]
    label = {"1_仅LOGN": "仅物流（抱怨）", "1_仅QUAL": "仅商品质量", "1_仅SERV": "仅服务/退款",
             "LOGN+QUAL": "物流+质量", "LOGN+SERV": "物流+服务", "QUAL+SERV": "质量+服务",
             "LOGN+QUAL+SERV": "三者都提", "0_未识别": "未识别（多为纯情绪/漏召）"}
    for k in order:
        if combo[k]:
            print(f"  {label[k]:<24s}{combo[k]:>7,d}  {pct(combo[k], len(bad)):>6.2f}%")
    n_logn_any = sum(1 for r in bad if r["h"].get("LOGN"))
    n_log_any = sum(1 for r in bad if r["h"].get("LOG"))
    n_qual_any = sum(1 for r in bad if r["h"].get("QUAL"))
    print(f"\n  （含重叠·窄口径）抱怨物流 {n_logn_any:,} = {pct(n_logn_any, len(bad)):.2f}%"
          f" ｜提到质量 {n_qual_any:,} = {pct(n_qual_any, len(bad)):.2f}%")
    print(f"  （含重叠·宽口径）提到物流 {n_log_any:,} = {pct(n_log_any, len(bad)):.2f}%")

    # ---- 四、延迟分箱 × 物流提及率
    print("\n" + "=" * 78)
    print("四、反向验证：延迟越久，差评里的「物流提及率」是否越高")
    print("=" * 78)
    bins = [
        ("准时或提前", lambda d: d is not None and d <= 0),
        ("迟到不足1天", lambda d: d is not None and 0 < d < 1),
        ("迟到满1-2天", lambda d: d is not None and 1 <= d < 3),
        ("迟到满3-6天", lambda d: d is not None and 3 <= d < 7),
        ("迟到7天以上", lambda d: d is not None and d >= 7),
    ]
    # 差评子集（分母=有正文的差评）
    bad_analysis = [r for r in bad if r["is_analysis_sample"] == 1 and r["delay_days"] is not None]
    print(f"  差评且有正文且在分析样本内：{len(bad_analysis):,}")
    print(f"\n  {'延迟分箱':<14s}{'差评数':>8s}{'物流抱怨%':>10s}{'95%CI(%)':>16s}"
          f"{'明确未收到%':>12s}{'提质量%':>9s}")
    tab = []
    for name, fn in bins:
        sub = [r for r in bad_analysis if fn(float(r["delay_days"]))]
        if not sub:
            continue
        k_log = sum(1 for r in sub if r["h"].get("LOGN"))
        k_nr = sum(1 for r in sub if r["h"].get("NR"))
        k_ql = sum(1 for r in sub if r["h"].get("QUAL"))
        lo, hi = wilson(k_log, len(sub))
        print(f"  {name:<14s}{len(sub):>8,d}{pct(k_log, len(sub)):>9.2f}%"
              f"{lo:>9.1f}~{hi:<6.1f}{pct(k_nr, len(sub)):>11.2f}%"
              f"{pct(k_ql, len(sub)):>8.2f}%")
        tab.append((name, len(sub), pct(k_log, len(sub)), pct(k_nr, len(sub)), lo, hi))

    # 准时 vs 迟到（合并）的两比例 z 检验
    n_on = [r for r in bad_analysis if float(r["delay_days"]) <= 0]
    n_late = [r for r in bad_analysis if float(r["delay_days"]) > 0]
    if n_on and n_late:
        k1 = sum(1 for r in n_on if r["h"].get("LOGN"))
        k2 = sum(1 for r in n_late if r["h"].get("LOGN"))
        p1, p2 = k1 / len(n_on), k2 / len(n_late)
        pp = (k1 + k2) / (len(n_on) + len(n_late))
        se = (pp * (1 - pp) * (1 / len(n_on) + 1 / len(n_late))) ** 0.5
        z = (p2 - p1) / se if se else float("nan")
        print(f"\n  合并对比：准时 {pct(k1, len(n_on)):.2f}%（n={len(n_on):,}） vs "
              f"迟到 {pct(k2, len(n_late)):.2f}%（n={len(n_late):,}）")
        print(f"  差值 {pct(k2, len(n_late)) - pct(k1, len(n_on)):+.2f}pp，z = {z:.2f}"
              f"{'（显著）' if abs(z) > 1.96 else '（不显著）'}")

    # ---- 五、评价时点偏差：有多少评价写在「送达之前」
    print("\n" + "=" * 78)
    print("五、评价时点偏差（解释为什么送达订单里仍有人说「没收到」）")
    print("=" * 78)
    early = 0
    valid = 0
    for r in txt:
        cr, dv = r["review_creation_date"], r["delivered_ts"]
        if not isinstance(cr, datetime) or not isinstance(dv, datetime):
            continue  # 零日期（1 行）已在 SQL 里置 NULL，这里再兜一层
        valid += 1
        if cr < dv:
            early += 1
    print(f"  可比样本 {valid:,}，评价创建早于送达的 {early:,} = {pct(early, valid):.2f}%")
    nr_all = [r for r in txt if r["h"].get("NR")]
    nr_early = sum(1 for r in nr_all
                   if isinstance(r["review_creation_date"], datetime)
                   and isinstance(r["delivered_ts"], datetime)
                   and r["review_creation_date"] < r["delivered_ts"])
    print(f"  在「明确未收到」的 {len(nr_all):,} 条中，评价早于送达的 "
          f"{nr_early:,} = {pct(nr_early, len(nr_all)):.2f}%")

    # ---- 抽检
    if args.samples:
        random.seed(args.seed)
        k = args.n_sample
        print("\n" + "=" * 78)
        print(f"六、人工抽检样本（每类 {k} 条，用于验准）")
        print("=" * 78)
        for key, name in [("LOGN", "物流抱怨"), ("QUAL", "质量"), ("SERV", "服务")]:
            pool = [r for r in bad if r["h"].get(key)]
            print(f"\n[{name}] n={len(pool):,}")
            for r in random.sample(pool, min(k, len(pool))):
                print("   *", re.sub(r"\s+", " ", r["msg"])[:130])
        pool = [r for r in bad if not any(r["h"].get(key) for key in ("LOGN", "QUAL", "SERV"))]
        print(f"\n[未识别] n={len(pool):,}")
        for r in random.sample(pool, min(k, len(pool))):
            print("   *", re.sub(r"\s+", " ", r["msg"])[:130])

    # ---- 图
    plot_topics(cnt, combo, label, order, len(bad))
    plot_by_delay(tab, n_bad_txt)
    print("\n图表已输出：images/charts/c06_review_topics.png、c07_topic_by_delay.png")


# ---------------------------------------------------------------- 绘图

def plot_topics(cnt, combo, label, order, n_bad):
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.6),
                             gridspec_kw={"width_ratios": [1.15, 1]})
    fig.suptitle("差评文本在骂什么：物流是第一大来源，且评分越低占比越高",
                 fontsize=15, fontweight="bold", x=0.012, ha="left", y=0.975)

    # 左：各评分档的主题命中率（物流拆成「提及」与「明确抱怨」两档，不做叠线以免压柱）
    ax = axes[0]
    scores = [1, 2, 3, 4, 5]
    xs = range(len(scores))
    w = 0.20
    series = [("LOG", "物流（提及）", "#E8A79F"),
              ("LOGN", "物流（明确抱怨）", C_BAD),
              ("QUAL", "商品质量", C_ACC),
              ("SERV", "服务/退款", C_MAIN)]
    for i, (k, name, color) in enumerate(series):
        vals = [pct(cnt[k][s], cnt["_n"][s]) for s in scores]
        ax.bar([x + (i - 1.5) * w for x in xs], vals, width=w, color=color,
               alpha=0.9, label=name, zorder=3)
        for x, v in zip(xs, vals):
            if v >= 4:
                # 相邻柱同高时标签会挤在一起，奇偶交错抬高
                dy = 1.2 if i % 2 == 0 else 5.4
                ax.text(x + (i - 1.5) * w, v + dy, f"{v:.0f}", ha="center",
                        fontsize=7.6, color=color, fontweight="bold")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([f"{s} 星" for s in scores])
    ax.set_ylabel("该评分档中提到该主题的比例（%）")
    ax.set_ylim(0, 92)
    ax.grid(axis="y", color=C_LIGHT, lw=0.7, alpha=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=1)
    ax.set_title("① 主题提及率随评分的变化（分母=该档有正文的评论）",
                 fontsize=10.5, loc="left", pad=8)

    # 右：差评互斥构成
    ax2 = axes[1]
    items = [(label[k], combo[k]) for k in order if combo[k]]
    items.sort(key=lambda t: t[1])
    ys = range(len(items))
    vals = [pct(v, n_bad) for _, v in items]
    colors = []
    for name, _ in items:
        colors.append(C_BAD if "物流" in name and "质量" not in name and "服务" not in name
                      else ("#8FA8CC" if name.startswith("未识别") else C_MAIN))
    ax2.barh(list(ys), vals, color=colors, alpha=0.9, zorder=3, height=0.62)
    for y, v, (name, n) in zip(ys, vals, items):
        ax2.text(v + 0.7, y, f"{v:.1f}%  ({n:,})", va="center", fontsize=8.4,
                 color="#2D3748")
    ax2.set_yticks(list(ys))
    ax2.set_yticklabels([n for n, _ in items], fontsize=9)
    ax2.set_xlim(0, max(vals) * 1.32)
    ax2.set_xlabel("占全部差评文本的比例（%）")
    ax2.grid(axis="x", color=C_LIGHT, lw=0.7, alpha=0.8, zorder=0)
    ax2.set_axisbelow(True)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    ax2.set_title(f"② 差评文本的主题构成（互斥归类，n={n_bad:,}）",
                  fontsize=10.5, loc="left", pad=8)

    fig.text(0.012, 0.012,
             "注：关键词多标签分类，非情感模型；一条评论可同时命中多个主题。"
             "巴西葡语语料，已做去重音处理。",
             fontsize=7.6, color=C_GRAY)
    fig.tight_layout(rect=[0, 0.03, 1, 0.93])
    fig.savefig(os.path.join(OUT, "c06_review_topics.png"), dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_by_delay(tab, n_bad_txt):
    fig, ax = plt.subplots(figsize=(11.2, 5.8))
    fig.suptitle("延迟越久，差评里的「物流」属性越强——第 2 段归因的文本侧证据",
                 fontsize=15, fontweight="bold", x=0.012, ha="left", y=0.975)

    names = [t[0] for t in tab]
    log_v = [t[2] for t in tab]
    nr_v = [t[3] for t in tab]
    ns = [t[1] for t in tab]
    xs = range(len(names))

    ax.bar(xs, log_v, width=0.56, color=C_BAD, alpha=0.85, zorder=3,
           label="明确抱怨物流（%）")
    ax.plot(xs, nr_v, "-o", color=C_MAIN, lw=2.0, ms=6, zorder=4,
            label="其中明确说「没收到」（%）")
    for x, v, n in zip(xs, log_v, ns):
        ax.text(x, v + 1.6, f"{v:.1f}%", ha="center", fontsize=9.2,
                color=C_BAD, fontweight="bold")
    for x, v in zip(xs, nr_v):
        ax.text(x, v + 2.0, f"{v:.1f}%", ha="center", fontsize=8.4, color=C_MAIN,
                bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85))
    for x, n in zip(xs, ns):
        ax.text(x, 2.0, f"n={n:,}", ha="center", fontsize=7.8, color="white")

    ax.set_xticks(list(xs))
    ax.set_xticklabels(names, fontsize=10)
    ax.set_ylabel("占该箱差评文本的比例（%）")
    ax.set_ylim(0, 92)
    ax.grid(axis="y", color=C_LIGHT, lw=0.7, alpha=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    # 图例横排放在坐标区上方，避免压住最右侧的柱子
    ax.legend(frameon=False, fontsize=9.5, ncol=2, loc="lower center",
              bbox_to_anchor=(0.5, 1.005))

    ax.annotate("准时订单的差评里，\n只有约四分之一在抱怨物流",
                xy=(0, log_v[0]), xytext=(0.12, 40),
                fontsize=8.8, color=C_GRAY,
                arrowprops=dict(arrowstyle="->", color=C_GRAY, lw=1.0,
                                connectionstyle="arc3,rad=0.2"))
    ax.annotate("迟到 3 天以上：\n三分之二在骂物流",
                xy=(3.94, log_v[-1] - 1.5), xytext=(2.35, 80),
                fontsize=9.2, color=C_BAD, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.2,
                                connectionstyle="arc3,rad=-0.18"))

    fig.text(0.012, 0.012,
             f"分母：分析样本内、有正文的差评（1~2 星）共 {n_bad_txt:,} 条"
             "；文本样本存在自选偏差，仅用于组间对比，不代表全部订单。",
             fontsize=7.6, color=C_GRAY)
    fig.tight_layout(rect=[0, 0.03, 1, 0.93])
    fig.savefig(os.path.join(OUT, "c07_topic_by_delay.png"), dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
