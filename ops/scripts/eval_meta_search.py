# -*- coding: utf-8 -*-
"""Measure 数据资产检索 retrieval quality on a fixed labelled query set.

Changing what gets embedded and how tables are scored is a quality change, not
a feature toggle, so it needs a number before and after rather than a glance at
a few results. This harness builds its own SQL instead of calling the search
endpoint, so the same ruler applies across code changes; it only borrows the
module's engine and embedding settings.

Relevance is declared as a regex per query -- that is the labelling, and it is
meant to be read and argued with. Column queries are scored by hits@5 over the
best reachable number of hits, because several concepts have fewer than five
relevant columns in the whole warehouse and plain precision@5 would cap them
below 1.0 no matter how good the ranking is. Table queries are scored by
whether the expected table lands in the top 5, and at what rank.

Full per-query results go to a JSON file; stdout stays a compact ASCII report,
because the jump-host terminal mangles long UTF-8 lines.

Usage (on the Superset host):
    eval_meta_search.py --tag before [--scoring max|combo] [--keyword single|tokens]
"""
import argparse
import json
import os
import re
import sys

os.environ.setdefault("SUPERSET_CONFIG_PATH",
                      "/mnt/data/superset/superset_config.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/mnt/data/superset")

import meta_search as ms  # noqa: E402
from superset.app import create_app  # noqa: E402

TABLE = "bluetti.ads_sr_meta_knowledge"
# Bound to the module so the harness always measures the weights in force.
W_VEC, W_KW, COMBO = ms.W_VEC, ms.W_KW, ms.COMBO
TOP_N = 5

# q      the query as a user would type it
# col    regex marking a column as relevant, matched against "name | comment"
# tbl    regex marking a table as relevant, matched against "db.table"
# Queries are grouped by what they exercise; a query may carry both labels.
CASES = [
    # --- 字段语义：用近义说法去找，不是原样抄注释 ---
    {"q": "退款金额", "col": r"(?i)refund.*amount|actualrefund|退款.*(金额|总额|小计)"},
    {"q": "下单时间", "col": r"(?i)order_?(time|date)|下单时间|订单时间"},
    {"q": "会话ID", "col": r"(?i)session_?id|会话\s*id"},
    {"q": "设备序列号", "col": r"(?i)device_?sn|\bsn\b|设备\s*sn|序列号|设备编号"},
    {"q": "优惠券金额", "col": r"(?i)coupon|优惠券|折扣"},
    {"q": "运费", "col": r"(?i)shipping|freight|运费|配送费|物流费"},
    {"q": "币种", "col": r"(?i)currency|币种|货币"},
    {"q": "创建时间", "col": r"(?i)cre_?time|create[_d]?_?(time|at)|创建时间|新增时间"},
    {"q": "更新时间", "col": r"(?i)mod_?time|updat(e|ed)_?(time|at)|更新时间|修改时间"},
    {"q": "用户邮箱", "col": r"(?i)e?mail|邮箱|邮件地址"},
    {"q": "订单状态", "col": r"(?i)order.*(status|state)|订单状态"},
    {"q": "手机号", "col": r"(?i)phone|mobile|tel\b|手机|电话"},
    {"q": "售后单号", "col": r"(?i)rma_?no|售后单号"},
    {"q": "剩余电量", "col": r"(?i)soc|电量|剩余电量"},
    {"q": "固件版本", "col": r"(?i)firmware|固件版本"},
    {"q": "物流单号", "col": r"(?i)tracking|物流单号|快递单号|运单号"},
    {"q": "收货地址", "col": r"(?i)address|收货地址|收件地址"},

    # --- 标识符片段：中文向量对这类词天然弱，靠关键词那一路兜底 ---
    {"q": "session_id", "col": r"(?i)session_?id"},
    {"q": "device_sn", "col": r"(?i)device_?sn"},
    {"q": "refundAmount", "col": r"(?i)refund.?amount"},
    {"q": "order_no", "col": r"(?i)order_?no|orderno|订单编号|订单号"},

    # --- 同时限定表和字段：验证组合式打分有没有把两半证据合起来 ---
    {"q": "order_refund 退款金额",
     "col": r"(?i)refund.*amount|actualrefund|退款.*(金额|总额|小计)",
     "tbl": r"(?i)order_refund"},
    {"q": "chat_session 会话ID",
     "col": r"(?i)session_?id|会话\s*id",
     "tbl": r"(?i)chat_session"},
    {"q": "iot 设备SN",
     "col": r"(?i)device_?sn|设备\s*sn",
     "tbl": r"(?i)iot"},

    # --- 纯表级：确认改动没有把原来的表检索弄坏 ---
    {"q": "客服会话", "tbl": r"(?i)cs_chat|chat_session|customerservice"},
    {"q": "客服首次响应时长", "tbl": r"(?i)response_latency|first_?resp"},
    {"q": "会话转人工", "tbl": r"(?i)handoff|transfer|livechat|cs_chat"},
    {"q": "电池包数据", "tbl": r"(?i)pack|battery|b500"},
    {"q": "每日活跃设备", "tbl": r"(?i)active_?dev"},
]


def kw_expr(query, mode):
    """The keyword half, either as it was before the change or as it is now.

    `single` reproduces the old one-LIKE-per-query behaviour so a baseline
    taken earlier stays comparable; `tokens` defers to the module, so the
    harness cannot drift from what the page actually runs.
    """
    if mode == "tokens":
        return ms.kw_expr(query)
    return ("CASE WHEN LOWER(search_text) LIKE LOWER(%s) THEN 1 ELSE 0 END"
            % ms.like_literal(query))


def row_score(query, keyword):
    vector = ms.embed(query)
    vec = ("COALESCE(cosine_similarity(embedding, %s), 0)" % vector
           if vector else "0")
    return "%s * (%s) + %s * (%s)" % (W_VEC, vec, W_KW, kw_expr(query, keyword))


def relevant_columns(pattern):
    """How many columns the label matches warehouse-wide.

    `refundAmount` has exactly two, so a top-5 holding both is a perfect
    answer; dividing by 5 would score it 0.40 and hide any later improvement.
    StarRocks REGEXP is RE2, which accepts the same (?i) and \\b this file uses.
    """
    rows = ms._rows("""
        SELECT COUNT(*) AS n FROM {t}
        WHERE obj_type = 'column'
          AND concat(column_name, ' | ', coalesce(`comment`, '')) REGEXP {p}
    """.format(t=TABLE, p=ms.sql_str(pattern)))
    return int(rows[0]["n"]) if rows else 0


def top_columns(query, keyword):
    rs = row_score(query, keyword)
    sql = """
        SELECT db_name, table_name, column_name, `comment`,
               ROUND({rs}, 4) AS s
        FROM {t}
        WHERE obj_type = 'column'
        ORDER BY {rs} DESC
        LIMIT {n}
    """.format(rs=rs, t=TABLE, n=TOP_N)
    return ms._rows(sql)


def top_tables(query, keyword, scoring, col_weight):
    rs = row_score(query, keyword)
    t, c = "COALESCE(t, 0)", "%s * COALESCE(c, 0)" % col_weight
    combined = ("GREATEST(%s, %s)" % (t, c) if scoring == "max"
                else "GREATEST({t}, {c}) + {k} * LEAST({t}, {c})"
                     .format(t=t, c=c, k=COMBO))
    sql = """
        SELECT db_name, table_name, ROUND({combined}, 4) AS score
        FROM (
          SELECT db_name, table_name,
                 MAX(CASE WHEN obj_type = 'table'  THEN rs END) AS t,
                 MAX(CASE WHEN obj_type = 'column' THEN rs END) AS c
          FROM (SELECT db_name, table_name, obj_type, {rs} AS rs FROM {t}) r
          GROUP BY db_name, table_name
        ) g
        ORDER BY {combined} DESC
        LIMIT {n}
    """.format(combined=combined, rs=rs, t=TABLE, n=TOP_N)
    return ms._rows(sql)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scoring", choices=["max", "combo"], default="max")
    ap.add_argument("--keyword", choices=["single", "tokens"], default="single")
    ap.add_argument("--col-weight", type=float, default=ms.COL_WEIGHT)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--out", default="/mnt/data/superset/backups")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        out = {"config": {"scoring": args.scoring, "keyword": args.keyword,
                          "W_VEC": W_VEC, "W_KW": W_KW, "COMBO": COMBO,
                          "COL_WEIGHT": args.col_weight},
               "cases": []}
        col_p, col_n, tbl_hit, tbl_n, ranks = 0.0, 0, 0, 0, []

        for case in CASES:
            entry = {"q": case["q"]}

            if case.get("col"):
                pattern = re.compile(case["col"])
                rows = top_columns(case["q"], args.keyword)
                marks, shown = [], []
                for r in rows:
                    text = "%s | %s" % (r["column_name"], r["comment"] or "")
                    ok = bool(pattern.search(text))
                    marks.append(ok)
                    shown.append({"c": "%s.%s" % (r["table_name"],
                                                  r["column_name"]),
                                  "cmt": r["comment"], "s": float(r["s"]),
                                  "ok": ok})
                ideal = min(TOP_N, relevant_columns(case["col"])) or 1
                entry["columns"] = shown
                entry["relevant_n"] = ideal
                entry["hits"] = sum(marks)
                entry["score"] = round(sum(marks) / float(ideal), 3)
                col_p += entry["score"]
                col_n += 1

            if case.get("tbl"):
                pattern = re.compile(case["tbl"])
                rows = top_tables(case["q"], args.keyword, args.scoring,
                                  args.col_weight)
                rank, shown = 0, []
                for i, r in enumerate(rows, 1):
                    name = "%s.%s" % (r["db_name"], r["table_name"])
                    ok = bool(pattern.search(name))
                    if ok and not rank:
                        rank = i
                    shown.append({"t": name, "s": float(r["score"]), "ok": ok})
                entry["tables"] = shown
                entry["rank"] = rank
                tbl_n += 1
                if rank:
                    tbl_hit += 1
                    ranks.append(rank)

            out["cases"].append(entry)

        out["summary"] = {
            "column_queries": col_n,
            "column_score": round(col_p / (col_n or 1), 4),
            "table_queries": tbl_n,
            "table_hit_at_5": tbl_hit,
            "table_mean_rank": round(sum(ranks) / float(len(ranks) or 1), 2),
        }

    path = os.path.join(args.out, "eval_%s_%s_%s_w%s.json"
                        % (args.tag, args.scoring, args.keyword,
                           args.col_weight))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1, sort_keys=True)

    # ASCII only, one short line per query: the detail lives in the file.
    print("EVAL tag=%s scoring=%s keyword=%s col_weight=%s"
          % (args.tag, args.scoring, args.keyword, args.col_weight))
    print("%-6s %-18s %s" % ("case", "metric", "top5"))
    for i, case in enumerate(CASES):
        entry = out["cases"][i]
        label = "q%02d" % (i + 1)
        if "score" in entry:
            flags = "".join("X" if c["ok"] else "." for c in entry["columns"])
            print("%-6s col %.2f (%d/%d) %s" % (label, entry["score"],
                                                entry["hits"],
                                                entry["relevant_n"], flags))
        if "rank" in entry:
            flags = "".join("X" if t["ok"] else "." for t in entry["tables"])
            print("%-6s tbl rank %-2d     %s" % (label, entry["rank"], flags))
    s = out["summary"]
    print("SUMMARY col=%.4f over %d | tbl_hit@5=%d/%d mean_rank=%.2f"
          % (s["column_score"], s["column_queries"],
             s["table_hit_at_5"], s["table_queries"], s["table_mean_rank"]))
    print("DETAIL %s" % path)


main()
