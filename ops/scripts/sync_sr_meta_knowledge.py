# -*- coding: utf-8 -*-
"""Incrementally fill in missing comments and vectorise StarRocks metadata.

Feeds the 数据资产检索 entry of the 数据中台速览 dashboard.  One pass does all of:

    scan information_schema -> diff against the knowledge table
      -> ask an LLM for Chinese comments where the source has none
      -> embed the rows whose search_text changed
      -> upsert the batch into bluetti.ads_sr_meta_knowledge

Comments and vectors land in the same write, so a row is never left with a
comment but no vector.  A table that fails mid-way is skipped whole and picked
up again next run, which makes the job idempotent and safe to re-run.

Runs on the Superset host: it is the only scheduled host with egress to the
embedding API (the DolphinScheduler node has none).  Credentials and endpoints
come from the environment, see sync_sr_meta_knowledge.sh.

Usage:
  sync_sr_meta_knowledge.py plan            # show what would change, no API calls
  sync_sr_meta_knowledge.py apply           # do it
  sync_sr_meta_knowledge.py apply --limit 5 # only the first 5 pending tables
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

CONF = (
    "/opt/superset/superset_config.py"
    if os.path.exists("/opt/superset/superset_config.py")
    else "/mnt/data/superset/superset_config.py"
)
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from sqlalchemy import text  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()

TABLE = "bluetti.ads_sr_meta_knowledge"
TERMS = "bluetti.ads_sr_meta_terms"
DATABASE_ID = 12  # agi: reads SHOW, writes bluetti

# Databases worth describing. information_schema and friends are noise.
SKIP_SCHEMAS = ("information_schema", "_statistics_", "sys", "sys_catalog")
# Scratch tables left behind by ETL. Describing them wastes tokens and they
# pollute search results.
SKIP_TABLE_PREFIXES = ("_tmp_", "tmp_", "temp_", "bak_", "test_")
SKIP_TABLE_SUFFIXES = ("_tmp", "_bak", "_backup", "_old", "_copy")

EMBED_BASE = os.environ.get("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
EMBED_KEY = os.environ.get("EMBED_API_KEY", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1024"))
EMBED_BATCH = int(os.environ.get("EMBED_BATCH", "32"))

# The self-hosted OneAPI gateway has no working channel (503 for every model),
# so both the chat and the embedding call go to SiliconFlow on the same key.
LLM_BASE = os.environ.get("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "Pro/deepseek-ai/DeepSeek-V3")
LLM_WORKERS = int(os.environ.get("LLM_WORKERS", "4"))
BATCH_TABLES = int(os.environ.get("BATCH_TABLES", "25"))

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "60"))
HTTP_RETRY = 3
INSERT_CHUNK = 200  # 1024 floats per row, keep each INSERT statement sane

DDL = """
CREATE TABLE IF NOT EXISTS bluetti.ads_sr_meta_knowledge (
  id             BIGINT,
  obj_type       VARCHAR(16),
  db_name        VARCHAR(64),
  table_name     VARCHAR(256),
  column_name    VARCHAR(256),
  data_type      VARCHAR(64),
  `comment`      VARCHAR(2000),
  comment_source VARCHAR(16),
  confidence     FLOAT,
  search_text    VARCHAR(4000),
  embedding      ARRAY<FLOAT>,
  content_hash   VARCHAR(64),
  updated_at     DATETIME
) PRIMARY KEY (id)
DISTRIBUTED BY HASH(id) BUCKETS 8
PROPERTIES("replication_num"="1")
"""

PROMPT = """你是数据仓库的元数据管理员。下面是 StarRocks 中一张表的结构，\
其中部分对象缺少中文注释。请根据库名、表名、字段名和字段类型推断出简洁准确的中文说明。

要求：
- 每条说明不超过 30 个字，直接描述含义，不要写「该字段表示」之类的废话。
- 看不出含义的，说明写空字符串，置信度给 0。
- confidence 取 0 到 1，表示你对该条推断的把握。
- 只输出 JSON，不要加 markdown 代码块标记。

库名：{db}
表名：{table}
表的现有注释：{table_comment}
字段（序号 | 字段名 | 类型 | 现有注释）：
{columns}

输出格式：
{{"table": {{"comment": "...", "confidence": 0.8}},
  "columns": [{{"name": "字段名", "comment": "...", "confidence": 0.8}}]}}"""


def log(fmt, *a):
    print("META_KB|%s|%s" % (datetime.now().strftime("%H:%M:%S"), fmt % a),
          flush=True)


def http_json(url, key, payload):
    """POST json, retrying on transient failures. Raises on final failure."""
    last = None
    for attempt in range(HTTP_RETRY):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer %s" % key,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            body = ex.read().decode("utf-8", "ignore")[:200]
            last = "HTTP %s %s" % (ex.code, body)
            if ex.code < 500 and ex.code != 429:
                break  # a bad request will not get better by retrying
        except Exception as ex:  # noqa: BLE001
            last = "%s: %s" % (type(ex).__name__, ex)
        time.sleep(2 ** attempt)
    raise RuntimeError(last)


# --------------------------------------------------------------------------
# read side


def is_placeholder_comment(comment):
    """StarRocks stores the engine or table kind in table_comment when the
    table has no real comment (OLAP, VIEW, MATERIALIZED_VIEW, HIVE, ...).
    Anything in caps with no CJK and no lowercase is one of those, not prose.
    """
    c = comment.strip()
    return bool(c) and len(c) <= 24 and c.replace("_", "").isalpha() \
        and c.isascii() and c.isupper()


def fetch_metadata(conn):
    """Every table and column worth describing, grouped by table."""
    skip = ", ".join("'%s'" % s for s in SKIP_SCHEMAS)
    tables = conn.execute(text("""
        SELECT table_schema, table_name, table_type, COALESCE(table_comment, '')
        FROM information_schema.tables
        WHERE table_schema NOT IN (%s)
    """ % skip)).fetchall()
    columns = conn.execute(text("""
        SELECT table_schema, table_name, ordinal_position, column_name,
               data_type, COALESCE(column_comment, '')
        FROM information_schema.columns
        WHERE table_schema NOT IN (%s)
        ORDER BY table_schema, table_name, ordinal_position
    """ % skip)).fetchall()

    by_table = {}
    for schema, name, ttype, comment in tables:
        low = name.lower()
        if (low.startswith(SKIP_TABLE_PREFIXES)
                or low.endswith(SKIP_TABLE_SUFFIXES)):
            continue
        if is_placeholder_comment(comment):
            comment = ""
        by_table[(schema, name)] = {
            "db": schema, "table": name, "type": ttype,
            "comment": comment, "columns": [],
        }
    for schema, name, pos, col, dtype, comment in columns:
        entry = by_table.get((schema, name))
        if entry is not None:
            entry["columns"].append(
                {"pos": pos, "name": col, "type": dtype, "comment": comment})
    return by_table


def fetch_known(conn):
    """content_hash and comment_source of what is already in the knowledge table."""
    rows = conn.execute(text(
        "SELECT id, content_hash, comment_source, `comment` FROM %s" % TABLE
    )).fetchall()
    return {r[0]: {"hash": r[1], "source": r[2], "comment": r[3]} for r in rows}


# --------------------------------------------------------------------------
# derive


def row_id(db, table, column):
    """Stable 63-bit id so re-runs update rather than duplicate."""
    key = "%s\x1f%s\x1f%s" % (db, table, column or "")
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:15], 16)


def build_search_text(db, table, column, dtype, comment, siblings):
    """What gets embedded and keyword-matched.

    Includes sibling column names so a table-level query like 会话留存 can hit a
    table through its columns even when the table comment is thin.
    """
    parts = ["%s.%s" % (db, table)]
    if column:
        parts.append(column)
        if dtype:
            parts.append(dtype)
    if comment:
        parts.append(comment)
    if siblings:
        parts.append(" ".join(siblings))
    return " | ".join(parts)[:4000]


def plan_rows(meta):
    """Flatten metadata into prospective knowledge rows carrying the native
    comment. Blanks are filled later from the knowledge table or the LLM."""
    rows = []
    for (db, tname), t in sorted(meta.items()):
        cols = t["columns"]
        sibling_names = [c["name"] for c in cols][:60]

        rows.append({
            "id": row_id(db, tname, None), "obj_type": "table",
            "db": db, "table": tname, "column": "", "data_type": "",
            "comment": t["comment"],
            "source": "native" if t["comment"] else "",
            "confidence": 1.0 if t["comment"] else 0.0,
            "siblings": sibling_names,
        })
        for c in cols:
            rows.append({
                "id": row_id(db, tname, c["name"]), "obj_type": "column",
                "db": db, "table": tname, "column": c["name"],
                "data_type": c["type"], "comment": c["comment"],
                "source": "native" if c["comment"] else "",
                "confidence": 1.0 if c["comment"] else 0.0,
                "siblings": [],
            })
    return rows


def merge_known_comment(row, known):
    """Fill a row's comment from the knowledge table when the source has none.

    Precedence is human > whatever was stored before > native-only blank.  A
    human-confirmed comment is kept but still flows through the normal hash
    and embedding path, so editing one in the UI does re-vectorise it.
    """
    if row["comment"]:
        return
    prev = known.get(row["id"]) or {}
    if prev.get("comment"):
        row["comment"] = prev["comment"]
        row["source"] = prev.get("source") or "llm"
        row["confidence"] = 1.0 if prev.get("source") == "human" else 0.0


def tables_needing_llm(rows, known):
    """Tables that still have an undescribed object.

    A blank is only worth an LLM call when neither the source nor the
    knowledge table can describe it.  Checking the knowledge table is what
    makes the daily run incremental: comments are never written back to
    StarRocks, so `information_schema` stays blank forever and judging by it
    alone would re-infer all 1200 tables every night.
    """
    need = set()
    for r in rows:
        if r["comment"]:
            continue
        if (known.get(r["id"]) or {}).get("comment"):
            continue
        need.add((r["db"], r["table"]))
    return sorted(need)


def infer_comments(meta, db, tname):
    """Ask the LLM for the missing comments of one table. Returns a dict."""
    t = meta[(db, tname)]
    listing = "\n".join(
        "%d | %s | %s | %s" % (c["pos"], c["name"], c["type"], c["comment"] or "(空)")
        for c in t["columns"]
    )
    prompt = PROMPT.format(db=db, table=tname,
                           table_comment=t["comment"] or "(空)",
                           columns=listing)
    out = http_json("%s/chat/completions" % LLM_BASE, LLM_KEY, {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    })
    content = out["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(content)


def embed_texts(texts):
    """Embed a list of strings, preserving order."""
    vectors = []
    for i in range(0, len(texts), EMBED_BATCH):
        chunk = texts[i:i + EMBED_BATCH]
        out = http_json("%s/embeddings" % EMBED_BASE, EMBED_KEY,
                        {"model": EMBED_MODEL, "input": chunk})
        data = sorted(out["data"], key=lambda d: d["index"])
        if len(data) != len(chunk):
            raise RuntimeError("embedding count mismatch: got %d want %d"
                               % (len(data), len(chunk)))
        for d in data:
            vec = d["embedding"]
            if len(vec) != EMBED_DIM:
                raise RuntimeError("unexpected embedding dim %d (want %d), "
                                   "model changed?" % (len(vec), EMBED_DIM))
            vectors.append(vec)
    return vectors


# --------------------------------------------------------------------------
# write side


def rss_mb():
    """Resident size, logged per batch so a memory regression is visible."""
    try:
        with open("/proc/self/status", "r") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return -1


def sql_str(value):
    return "'%s'" % str(value).replace("\\", "\\\\").replace("'", "\\'")


def upsert(conn, rows):
    """Write rows in chunks. PRIMARY KEY tables treat INSERT as upsert."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    written = 0
    for i in range(0, len(rows), INSERT_CHUNK):
        values = []
        for r in rows[i:i + INSERT_CHUNK]:
            vec = "[%s]" % ",".join("%.6f" % f for f in r["embedding"])
            values.append("(%d,%s,%s,%s,%s,%s,%s,%s,%.3f,%s,%s,%s,%s)" % (
                r["id"], sql_str(r["obj_type"]), sql_str(r["db"]),
                sql_str(r["table"]), sql_str(r["column"]), sql_str(r["data_type"]),
                sql_str(r["comment"]), sql_str(r["source"]), r["confidence"],
                sql_str(r["search_text"]), vec, sql_str(r["content_hash"]),
                sql_str(now),
            ))
        conn.execute(text(
            "INSERT INTO %s (id, obj_type, db_name, table_name, column_name, "
            "data_type, `comment`, comment_source, confidence, search_text, "
            "embedding, content_hash, updated_at) VALUES %s"
            % (TABLE, ",".join(values))
        ))
        written += len(values)
    return written


def prune(conn, live_ids):
    """Drop knowledge rows whose object no longer exists."""
    stale = conn.execute(text("SELECT id FROM %s" % TABLE)).fetchall()
    gone = [r[0] for r in stale if r[0] not in live_ids]
    for i in range(0, len(gone), 500):
        batch = ",".join(str(x) for x in gone[i:i + 500])
        conn.execute(text("DELETE FROM %s WHERE id IN (%s)" % (TABLE, batch)))
    return len(gone)


# --------------------------------------------------------------------------


def run(cmd, limit):
    with app.app_context():
        from superset import db
        from superset.models.core import Database

        database = db.session.get(Database, DATABASE_ID)
        assert database, "database %d missing" % DATABASE_ID

        with database.get_sqla_engine() as eng, eng.connect() as conn:
            # Every insert here is a megabyte of inlined vectors and no two are
            # alike, so the compiled-statement cache would only accumulate SQL
            # that is never reused -- enough to get the process OOM-killed.
            conn = conn.execution_options(compiled_cache=None)
            conn.execute(text(DDL))
            meta = fetch_metadata(conn)
            known = fetch_known(conn)
            rows = plan_rows(meta)
            need_llm = tables_needing_llm(rows, known)
            log("scanned|tables=%d|rows=%d|tables_needing_llm=%d",
                len(meta), len(rows), len(need_llm))

            if limit:
                need_llm = need_llm[:limit]
                keep = set(need_llm)
                rows = [r for r in rows if (r["db"], r["table"]) in keep]
                log("limited|tables=%d|rows=%d", len(need_llm), len(rows))

            if cmd == "plan":
                changed = 0
                for r in rows:
                    merge_known_comment(r, known)
                    st = build_search_text(r["db"], r["table"], r["column"],
                                           r["data_type"], r["comment"],
                                           r.get("siblings"))
                    h = hashlib.sha1(st.encode("utf-8")).hexdigest()
                    if known.get(r["id"], {}).get("hash") != h:
                        changed += 1
                human = sum(1 for v in known.values() if v["source"] == "human")
                log("PLAN|llm_calls=%d|rows_to_embed<=%d|human_confirmed=%d",
                    len(need_llm), changed, human)
                return

            rows_by_table = {}
            for r in rows:
                rows_by_table.setdefault((r["db"], r["table"]), []).append(r)

            # prune only needs the identifiers, so drop the one reference that
            # would otherwise pin every row for the whole run. Each written row
            # carries a 1024-float embedding (~32 kB), which across a full
            # backfill is enough to get the process OOM-killed.
            live_ids = {r["id"] for r in rows}
            del rows

            # Work in batches of tables, each one inferred, embedded and
            # written before the next starts.  A full backfill is over an hour
            # of paid LLM calls; doing all the inference up front would throw
            # every one of them away if the process died near the end.
            order = need_llm + [t for t in sorted(rows_by_table) if t not in set(need_llm)]
            written, llm_bad, embed_bad, skipped = 0, 0, 0, 0

            def infer_one(target):
                db_name, tname = target
                try:
                    return target, infer_comments(meta, db_name, tname)
                except Exception as ex:  # noqa: BLE001
                    log("LLM_FAIL|%s.%s|%s", db_name, tname, ex)
                    return target, None

            need_set = set(need_llm)
            for start in range(0, len(order), BATCH_TABLES):
                batch = order[start:start + BATCH_TABLES]
                todo = [t for t in batch if t in need_set]

                inferred, llm_failed = {}, set()
                if todo:
                    with ThreadPoolExecutor(max_workers=LLM_WORKERS) as pool:
                        for (db_name, tname), out in pool.map(infer_one, todo):
                            if out is None:
                                llm_failed.add((db_name, tname))
                                continue
                            tbl = out.get("table") or {}
                            if tbl.get("comment"):
                                inferred[row_id(db_name, tname, None)] = (
                                    tbl["comment"], float(tbl.get("confidence") or 0))
                            for c in out.get("columns") or []:
                                if c.get("comment"):
                                    inferred[row_id(db_name, tname, c.get("name"))] = (
                                        c["comment"], float(c.get("confidence") or 0))
                llm_bad += len(llm_failed)

                for target in batch:
                    # Popped rather than read: once a table has been written
                    # its rows are dead weight, and holding them is what blew
                    # the memory budget on the first full backfill.
                    candidates = rows_by_table.pop(target, [])
                    # A table whose inference failed is left out entirely: it
                    # keeps no half-described rows and is picked up next run.
                    if target in llm_failed:
                        continue
                    group = []
                    for r in candidates:
                        merge_known_comment(r, known)
                        if not r["comment"] and r["id"] in inferred:
                            r["comment"], r["confidence"] = inferred[r["id"]]
                            r["source"] = "llm"
                        r["search_text"] = build_search_text(
                            r["db"], r["table"], r["column"], r["data_type"],
                            r["comment"], r.get("siblings"))
                        r["content_hash"] = hashlib.sha1(
                            r["search_text"].encode("utf-8")).hexdigest()
                        if known.get(r["id"], {}).get("hash") != r["content_hash"]:
                            group.append(r)
                    if not group:
                        skipped += 1
                        continue
                    try:
                        vectors = embed_texts([r["search_text"] for r in group])
                        for r, v in zip(group, vectors):
                            r["embedding"] = v
                        written += upsert(conn, group)
                    except Exception as ex:  # noqa: BLE001
                        embed_bad += 1
                        log("EMBED_FAIL|%s.%s|%d rows skipped|%s",
                            target[0], target[1], len(group), ex)

                log("batch|%d-%d/%d|written=%d|llm_fail=%d|unchanged_tables=%d|rss=%dMB",
                    start + 1, min(start + BATCH_TABLES, len(order)), len(order),
                    written, llm_bad, skipped, rss_mb())

            failed = llm_bad + embed_bad

            removed = prune(conn, live_ids) if not limit else 0
            log("OK|written=%d|tables_failed=%d|pruned=%d",
                written, failed, removed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "apply"])
    ap.add_argument("--limit", type=int, default=0,
                    help="only process the first N tables that need comments")
    args = ap.parse_args()

    if args.cmd == "apply":
        missing = [n for n, v in (("EMBED_API_KEY", EMBED_KEY),
                                  ("LLM_API_KEY", LLM_KEY)) if not v]
        if missing:
            sys.exit("missing env: %s" % ", ".join(missing))
    run(args.cmd, args.limit)


main()
