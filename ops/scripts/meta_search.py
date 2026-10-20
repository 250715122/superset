# -*- coding: utf-8 -*-
"""数据资产检索 — a search page over bluetti.ads_sr_meta_knowledge.

Registered as a Flask-AppBuilder view rather than a bare Blueprint so that it
gets real Superset permissions (`can_index on MetaSearch` and friends) which
show up in the role editor and can be granted like any other.

The knowledge table is filled by sync_sr_meta_knowledge.py.  This module only
reads it, plus writes back the one field a reviewer can change: a comment they
confirm or correct, which is marked `human` and from then on is never
overwritten by the inference job.

Wire it up from superset_config.py:

    def FLASK_APP_MUTATOR(app):
        ...
        import meta_search
        meta_search.register(app)
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from functools import lru_cache

from flask import jsonify, render_template, request
from flask_appbuilder import BaseView, expose
from flask_appbuilder.security.decorators import has_access, has_access_api

logger = logging.getLogger(__name__)

TABLE = "bluetti.ads_sr_meta_knowledge"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Scoring. Vector similarity carries most of the weight; the keyword hit is
# what rescues queries typed as an identifier fragment (dwd_cs_sess), where
# embeddings of Chinese prose and English abbreviations line up poorly.
W_VEC = 0.7
W_KW = 0.3
# A table is as good as its best evidence, plus a little for having a second
# kind: a table whose own comment matches *and* which holds a matching column
# should outrank one that only does either, without a column-only match being
# pushed below a mediocre table-only one, which is what averaging would do.
COMBO = 0.15
# Column evidence is discounted before it competes with table evidence. A
# column embeds as a handful of words, a table as a name plus a comment plus
# every column name it has, and a short query is simply closer to short text,
# so the two similarities are not on one scale. Without this a table full of
# plausible-sounding columns outranks the table whose own comment says exactly
# what the query asked for.
COL_WEIGHT = 0.8
COLUMN_HIT = 0.45  # below this a column is noise, as a chip or as a result
MIN_SCORE = 0.3    # below this a table is noise
KW_ONLY_FLOOR = 0.01  # keyword-only mode: anything the text literally contains
HIT_CHIPS = 6      # matched columns shown on a table row; the rest are counted
MAX_TOKENS = 6
MAX_GRAMS = 8      # character pairs tried when keyword search is on its own
MAX_ROWS = 50
MAX_QUERY_LEN = 200


def _load_env():
    """Read the key file the sync job also uses, without clobbering real env."""
    path = os.path.join(BASE_DIR, ".meta_kb_env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

EMBED_BASE = os.environ.get("EMBED_BASE_URL", "https://agi-newapi.bluetti.com/v1")
EMBED_KEY = os.environ.get("EMBED_API_KEY", "")
# Must stay the model the stored vectors were built with, or scores are noise.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
EMBED_TIMEOUT = float(os.environ.get("EMBED_TIMEOUT", "3"))
DATABASE_ID = int(os.environ.get("META_KB_DATABASE_ID", "12"))


# ---------------------------------------------------------------- SQL safety

def sql_str(value):
    """A single-quoted SQL literal. User input never reaches SQL any other way."""
    return "'%s'" % str(value).replace("\\", "\\\\").replace("'", "\\'")


def like_literal(value):
    """A LIKE pattern with the wildcards in the user's text neutralised."""
    escaped = (str(value).replace("\\", "\\\\").replace("'", "\\'")
               .replace("%", "\\%").replace("_", "\\_"))
    return "'%%%s%%'" % escaped


_BIND_COLON = re.compile(r":(?=\w)")


def _statement(sql):
    """A statement whose colons cannot be mistaken for bind parameters.

    Everything user-supplied is an inlined literal by the time it gets here,
    but text() reads the `:30` in a search for 超时:30 as a placeholder and
    refuses the request. Escaping the colons leaves text() doing the one thing
    that is wanted from it, doubling the `%` that LIKE patterns are made of,
    which the driver would otherwise take for a format string. The backslashes
    do not survive into the value MySQL sees.
    """
    from sqlalchemy import text

    return text(_BIND_COLON.sub(r"\\:", sql))


# ------------------------------------------------------------------- scoring

_TOKEN_SPLIT = re.compile(r"[\s,，、/\\|;；:：]+")


def _like(value):
    return "CASE WHEN LOWER(search_text) LIKE LOWER(%s) THEN 1 ELSE 0 END" \
           % like_literal(value)


def _share(whole, parts):
    """A contiguous hit on the whole query, or else how much of it was found."""
    return "GREATEST(%s, (%s) / %d.0)" % (
        whole, " + ".join(_like(p) for p in parts), len(parts))


def kw_expr(query, vector_available=True):
    """The keyword half of the score: 1 for a whole-query hit, else the share
    of the query that hit.

    People type `order_refund 退款金额`, naming a table and a field in one
    breath. No single search_text contains that whole string, so matching it as
    one LIKE scores zero and the keyword half stops helping exactly where it is
    needed most. Scoring per word lets each half contribute what it can, while
    a contiguous match of the whole query still wins outright.

    With the embedding service down the keyword half is all there is, and a
    Chinese phrase offers no spaces to split on, so it falls back to character
    pairs. That stays out of the normal path, where it would only add noise to
    a score the vector half already answers.
    """
    whole = _like(query)
    tokens = [t for t in _TOKEN_SPLIT.split(query.strip()) if t][:MAX_TOKENS]
    if len(tokens) > 1:
        return _share(whole, tokens)
    if vector_available or len(query) < 4:
        return whole
    return _share(whole, [query[i:i + 2]
                          for i in range(len(query) - 1)][:MAX_GRAMS])


# ----------------------------------------------------------------- typography

_FONT_FACE_RE = re.compile(r"@font-face\{[^}]*\}")
_URL_RE = re.compile(r"url\(([^)'\"]+)\)")
# Inter ships no CJK glyphs, so only the Latin subsets are worth inlining;
# Chinese falls through to PingFang SC / Microsoft YaHei either way. Limiting
# the weights too keeps this at a few rules instead of the bundle's ~50.
# The basic-latin subset is written in wildcard form (u+00??), not as a range,
# so matching on "u+0000-00ff" silently drops every ASCII glyph.
_LATIN_PREFIXES = ("u+00??", "u+0100-02ba")
_KEEP_WEIGHTS = ("400", "500", "600")


@lru_cache(maxsize=1)
def inter_font_css():
    """Superset's own Inter @font-face rules, for use in a standalone page.

    This page renders outside the React app — and inside an iframe when it is
    embedded in a dashboard — so it inherits none of Superset's stylesheets.
    Lifting the rules out of the built bundle at runtime keeps the typography
    matching across upgrades, where the asset hashes change.
    """
    import superset

    assets = os.path.join(os.path.dirname(superset.__file__), "static", "assets")
    kept = []
    try:
        names = [n for n in os.listdir(assets) if n.endswith(".css")]
    except OSError as ex:  # noqa: BLE001
        logger.warning("meta_search: no static assets, Inter unavailable: %s", ex)
        return ""

    for name in names:
        try:
            with open(os.path.join(assets, name), "r", encoding="utf-8") as handle:
                css = handle.read()
        except OSError:
            continue
        if "Inter" not in css:
            continue
        for block in _FONT_FACE_RE.findall(css):
            flat = block.replace(" ", "").lower()
            if "font-family:inter" not in flat:
                continue
            weight = re.search(r"font-weight:(\d+)", flat)
            if weight and weight.group(1) not in _KEEP_WEIGHTS:
                continue
            ranges = re.search(r"unicode-range:([^;}]*)", flat)
            if ranges and not ranges.group(1).startswith(_LATIN_PREFIXES):
                continue
            kept.append(_absolutise(block))

    logger.info("meta_search: inlined %d Inter font-face rules", len(kept))
    return "\n".join(sorted(set(kept)))


def _absolutise(block):
    """Repoint a bundle-relative url() at the path the assets are served from."""
    def fix(match):
        target = match.group(1).strip()
        if target.startswith(("/", "http", "data:")):
            return match.group(0)
        return "url(/static/assets/%s)" % target
    return _URL_RE.sub(fix, block)


# ------------------------------------------------------------------ embedding

_EMBED_CACHE = {}
EMBED_CACHE_MAX = 512


def embed(query):
    """Vector literal for `query`, or None when the service is unreachable.

    Returning None is deliberate: the caller substitutes 0 for the vector
    score, so an embedding outage downgrades search to keyword-only instead of
    failing the page.

    Only successes are cached. Under lru_cache a single three-second timeout
    was remembered as "this query has no vector", leaving that exact phrase on
    keyword-only results for the rest of the worker's life.
    """
    if not EMBED_KEY or not query:
        return None
    cached = _EMBED_CACHE.get(query)
    if cached:
        return cached
    payload = json.dumps({"model": EMBED_MODEL,
                          "input": query[:MAX_QUERY_LEN]}).encode("utf-8")
    req = urllib.request.Request(
        "%s/embeddings" % EMBED_BASE, data=payload,
        headers={"Authorization": "Bearer %s" % EMBED_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT) as resp:
            vector = json.loads(resp.read().decode("utf-8"))["data"][0]["embedding"]
    except Exception as ex:  # noqa: BLE001
        logger.warning("meta_search: embedding failed, keyword-only: %s", ex)
        return None
    literal = "[%s]" % ",".join("%.6f" % f for f in vector)
    if len(_EMBED_CACHE) >= EMBED_CACHE_MAX:
        _EMBED_CACHE.clear()   # a search box does not need a real eviction policy
    _EMBED_CACHE[query] = literal
    return literal


# ----------------------------------------------------------------- data access

def _engine():
    from superset import db
    from superset.models.core import Database

    database = db.session.get(Database, DATABASE_ID)
    if database is None:
        raise RuntimeError("Superset database id %d not found" % DATABASE_ID)
    return database.get_sqla_engine()


def _rows(sql):
    with _engine() as eng, eng.connect() as conn:
        result = conn.execute(_statement(sql))
        keys = list(result.keys())
        return [dict(zip(keys, row)) for row in result.fetchall()]


def row_score(query):
    """Per-row relevance, and whether the vector half is actually available."""
    vector = embed(query)
    vec = ("COALESCE(cosine_similarity(embedding, %s), 0)" % vector
           if vector else "0")
    return ("%s * (%s) + %s * (%s)"
            % (W_VEC, vec, W_KW, kw_expr(query, bool(vector))), bool(vector))


def floor_for(used_vector, normal):
    """The cut-off, lowered when there is no vector half to cut noise out of.

    A perfect keyword hit scores W_KW and nothing more, which is below every
    floor tuned against vector similarity -- so the keyword-only fallback the
    page promises during an embedding outage used to return a banner and an
    empty list. A literal match needs no floor beyond being non-zero: it either
    appears in the text or it does not.
    """
    return normal if used_vector else KW_ONLY_FLOOR


def _ordered_hits(value):
    """Unpack the matched column names, best first.

    GROUP_CONCAT promises no order, so the SQL prefixes each name with its rank
    within the table and the order is restored here rather than relying on a
    dialect-specific `GROUP_CONCAT(... ORDER BY ...)`.
    """
    if not value:
        return []
    ranked = []
    for item in value.split(","):
        rank, _, name = item.partition(":")
        ranked.append((int(rank) if rank.isdigit() else 99, name))
    return [name for _, name in sorted(ranked)]


def search_tables(query):
    score, used_vector = row_score(query)
    combined = ("GREATEST(t_score, {w} * c_score) + "
                "{combo} * LEAST(t_score, {w} * c_score)"
                .format(w=COL_WEIGHT, combo=COMBO))
    sql = """
        WITH scored AS (
          SELECT db_name, table_name, column_name, obj_type, `comment`,
                 comment_source, {score} AS rs
          FROM {table}
        ),
        ranked AS (
          SELECT db_name, table_name, column_name, rs,
                 ROW_NUMBER() OVER (PARTITION BY db_name, table_name
                                    ORDER BY rs DESC) AS rn
          FROM scored WHERE obj_type = 'column'
        ),
        hits AS (
          SELECT db_name, table_name,
                 GROUP_CONCAT(CASE WHEN rn <= {chips} AND rs >= {hit}
                                   THEN concat(CAST(rn AS STRING), ':',
                                               column_name) END) AS hit_columns,
                 COUNT(CASE WHEN rs >= {hit} THEN 1 END) AS hit_n
          FROM ranked GROUP BY db_name, table_name
        ),
        agg AS (
          SELECT db_name, table_name,
                 MAX(CASE WHEN obj_type = 'table' THEN `comment` END) AS table_comment,
                 MAX(CASE WHEN obj_type = 'table' THEN comment_source END) AS table_source,
                 COALESCE(MAX(CASE WHEN obj_type = 'table'  THEN rs END), 0) AS t_score,
                 COALESCE(MAX(CASE WHEN obj_type = 'column' THEN rs END), 0) AS c_score,
                 COUNT(CASE WHEN obj_type = 'column' THEN 1 END) AS column_n
          FROM scored GROUP BY db_name, table_name
        )
        SELECT a.db_name, a.table_name, a.table_comment, a.table_source,
               a.column_n, ROUND({combined}, 3) AS score,
               h.hit_columns, COALESCE(h.hit_n, 0) AS hit_n
        FROM agg a
        LEFT JOIN hits h ON a.db_name = h.db_name AND a.table_name = h.table_name
        WHERE {combined} > {floor}
        ORDER BY score DESC
        LIMIT {limit}
    """.format(score=score, combined=combined, chips=HIT_CHIPS, table=TABLE,
               hit=floor_for(used_vector, COLUMN_HIT),
               floor=floor_for(used_vector, MIN_SCORE), limit=MAX_ROWS)
    rows = _rows(sql)
    for row in rows:
        row["hit_columns"] = _ordered_hits(row["hit_columns"])
    return rows, used_vector


def search_columns(query):
    """Rank individual columns, for when the question is 哪里有这个字段.

    Same per-row score as the table search uses; the difference is that nothing
    is folded up into tables, so a column in a table whose name and comment say
    nothing about the query can still be the top result.
    """
    score, used_vector = row_score(query)
    sql = """
        SELECT id, db_name, table_name, column_name, data_type, `comment`,
               comment_source, ROUND(rs, 3) AS score
        FROM (
          SELECT id, db_name, table_name, column_name, data_type, `comment`,
                 comment_source, {score} AS rs
          FROM {table} WHERE obj_type = 'column'
        ) c
        WHERE rs >= {hit}
        ORDER BY rs DESC
        LIMIT {limit}
    """.format(score=score, table=TABLE, limit=MAX_ROWS,
               hit=floor_for(used_vector, COLUMN_HIT))
    return _rows(sql), used_vector


def table_columns(db_name, table_name):
    sql = """
        SELECT id, column_name, data_type, `comment`, comment_source, confidence
        FROM {table}
        WHERE obj_type = 'column' AND db_name = {db} AND table_name = {tbl}
        ORDER BY column_name
    """.format(table=TABLE, db=sql_str(db_name), tbl=sql_str(table_name))
    return _rows(sql)


def knowledge_stats():
    """Coverage counters for the landing state, before anyone has searched."""
    sql = """
        SELECT COUNT(CASE WHEN obj_type = 'table' THEN 1 END)  AS table_n,
               COUNT(CASE WHEN obj_type = 'column' THEN 1 END) AS column_n,
               COUNT(CASE WHEN comment_source = 'llm' THEN 1 END)   AS pending_n,
               COUNT(CASE WHEN comment_source = 'human' THEN 1 END) AS human_n
        FROM {table}
    """.format(table=TABLE)
    rows = _rows(sql)
    return rows[0] if rows else {}


def confirm_comment(row_id, comment):
    """Mark a comment as human-reviewed.

    Leaves search_text and content_hash alone on purpose: the nightly job
    recomputes both from this comment, notices the hash moved and re-embeds
    the row, so a corrected comment also improves future retrieval.
    """
    sql = """
        UPDATE {table}
        SET `comment` = {comment}, comment_source = 'human',
            confidence = 1.0, updated_at = {now}
        WHERE id = {row_id}
    """.format(table=TABLE, comment=sql_str(comment[:2000]),
               now=sql_str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
               row_id=int(row_id))
    with _engine() as eng, eng.connect() as conn:
        conn.execute(_statement(sql))


# ------------------------------------------------------------------- the view

class MetaSearchView(BaseView):
    route_base = "/meta-search"
    default_view = "index"
    # Keeps the permission label readable in the role editor.
    class_permission_name = "MetaSearch"
    base_permissions = ["can_index", "can_search", "can_columns", "can_confirm",
                        "can_stats"]

    @expose("/")
    @has_access
    def index(self):
        return render_template("meta_search.html", font_css=inter_font_css())

    @expose("/api/stats")
    @has_access_api
    def stats(self):
        try:
            return jsonify(knowledge_stats())
        except Exception as ex:  # noqa: BLE001
            logger.exception("meta_search: stats failed")
            return jsonify({"error": str(ex)[:300]}), 500

    @expose("/api/search")
    @has_access_api
    def search(self):
        """Table results by default, column results with mode=column.

        One endpoint rather than two so the two granularities cannot drift
        apart in the role editor: anyone allowed to search is allowed to search
        either way.
        """
        query = (request.args.get("q") or "").strip()[:MAX_QUERY_LEN]
        mode = "column" if request.args.get("mode") == "column" else "table"
        if not query:
            return jsonify({"q": "", "mode": mode, "vector": False,
                            "results": []})
        try:
            finder = search_columns if mode == "column" else search_tables
            results, used_vector = finder(query)
        except Exception as ex:  # noqa: BLE001
            logger.exception("meta_search: query failed")
            return jsonify({"error": str(ex)[:300]}), 500
        return jsonify({"q": query, "mode": mode, "vector": used_vector,
                        "results": results})

    @expose("/api/columns")
    @has_access_api
    def columns(self):
        db_name = (request.args.get("db") or "").strip()
        table_name = (request.args.get("table") or "").strip()
        if not db_name or not table_name:
            return jsonify({"error": "db and table are required"}), 400
        try:
            return jsonify({"columns": table_columns(db_name, table_name)})
        except Exception as ex:  # noqa: BLE001
            logger.exception("meta_search: columns failed")
            return jsonify({"error": str(ex)[:300]}), 500

    @expose("/api/confirm", methods=["POST"])
    @has_access_api
    def confirm(self):
        payload = request.get_json(silent=True) or {}
        row_id = payload.get("id")
        comment = (payload.get("comment") or "").strip()
        if not isinstance(row_id, int) or not comment:
            return jsonify({"error": "id (int) and comment are required"}), 400
        try:
            confirm_comment(row_id, comment)
        except Exception as ex:  # noqa: BLE001
            logger.exception("meta_search: confirm failed")
            return jsonify({"error": str(ex)[:300]}), 500
        return jsonify({"ok": True})


def register(app):
    """Attach the view. Safe to call twice; the second call is a no-op."""
    from superset import appbuilder

    if any(v.__class__ is MetaSearchView for v in appbuilder.baseviews):
        return
    appbuilder.add_view_no_menu(MetaSearchView)

    # Superset runs FAB with update_perms=False, so add_view_no_menu registers
    # the routes but not the permissions. Without this the view menu never
    # appears in the role editor and the page is ungrantable.
    # Called unconditionally rather than only on first install: a release that
    # adds an endpoint also adds a permission, and skipping when the view menu
    # already exists would leave that one ungrantable. add_permissions_view is
    # itself idempotent per permission.
    try:
        from superset import db, security_manager

        security_manager.add_permissions_view(
            MetaSearchView.base_permissions,
            MetaSearchView.class_permission_name)
        db.session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("meta_search: could not create permissions")

    logger.info("meta_search: registered at /meta-search/")
