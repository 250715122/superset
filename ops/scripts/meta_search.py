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
COLUMN_HIT = 0.5   # a column is "matched" at or above this similarity
MIN_SCORE = 0.3    # below this a table is noise
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

@lru_cache(maxsize=512)
def embed(query):
    """Vector literal for `query`, or None when the service is unreachable.

    Returning None is deliberate: the caller substitutes 0 for the vector
    score, so an embedding outage downgrades search to keyword-only instead of
    failing the page.
    """
    if not EMBED_KEY or not query:
        return None
    payload = json.dumps({"model": EMBED_MODEL,
                          "input": query[:MAX_QUERY_LEN]}).encode("utf-8")
    req = urllib.request.Request(
        "%s/embeddings" % EMBED_BASE, data=payload,
        headers={"Authorization": "Bearer %s" % EMBED_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT) as resp:
            vector = json.loads(resp.read().decode("utf-8"))["data"][0]["embedding"]
        return "[%s]" % ",".join("%.6f" % f for f in vector)
    except Exception as ex:  # noqa: BLE001
        logger.warning("meta_search: embedding failed, keyword-only: %s", ex)
        return None


# ----------------------------------------------------------------- data access

def _engine():
    from superset import db
    from superset.models.core import Database

    database = db.session.get(Database, DATABASE_ID)
    if database is None:
        raise RuntimeError("Superset database id %d not found" % DATABASE_ID)
    return database.get_sqla_engine()


def _rows(sql):
    from sqlalchemy import text

    with _engine() as eng, eng.connect() as conn:
        result = conn.execute(text(sql))
        keys = list(result.keys())
        return [dict(zip(keys, row)) for row in result.fetchall()]


def search_tables(query):
    vector = embed(query)
    vec_expr = ("COALESCE(cosine_similarity(embedding, %s), 0)" % vector
                if vector else "0")
    score = "%s * vec_score + %s * kw_hit" % (W_VEC, W_KW)
    sql = """
        SELECT db_name, table_name,
               MAX(CASE WHEN obj_type = 'table' THEN `comment` END) AS table_comment,
               MAX(CASE WHEN obj_type = 'table' THEN comment_source END) AS table_source,
               ROUND(MAX({score}), 3) AS score,
               GROUP_CONCAT(CASE WHEN obj_type = 'column'
                                  AND (vec_score >= {hit} OR kw_hit = 1)
                                 THEN column_name END) AS hit_columns,
               COUNT(CASE WHEN obj_type = 'column' THEN 1 END) AS column_n
        FROM (
          SELECT db_name, table_name, column_name, obj_type, `comment`,
                 comment_source,
                 {vec} AS vec_score,
                 CASE WHEN LOWER(search_text) LIKE LOWER({kw}) THEN 1 ELSE 0 END AS kw_hit
          FROM {table}
        ) t
        GROUP BY db_name, table_name
        HAVING MAX({score}) > {floor}
        ORDER BY score DESC
        LIMIT {limit}
    """.format(score=score, hit=COLUMN_HIT, vec=vec_expr,
               kw=like_literal(query), table=TABLE, floor=MIN_SCORE,
               limit=MAX_ROWS)
    return _rows(sql), bool(vector)


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
    from sqlalchemy import text

    sql = """
        UPDATE {table}
        SET `comment` = {comment}, comment_source = 'human',
            confidence = 1.0, updated_at = {now}
        WHERE id = {row_id}
    """.format(table=TABLE, comment=sql_str(comment[:2000]),
               now=sql_str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
               row_id=int(row_id))
    with _engine() as eng, eng.connect() as conn:
        conn.execute(text(sql))


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
        query = (request.args.get("q") or "").strip()[:MAX_QUERY_LEN]
        if not query:
            return jsonify({"q": "", "vector": False, "results": []})
        try:
            results, used_vector = search_tables(query)
        except Exception as ex:  # noqa: BLE001
            logger.exception("meta_search: query failed")
            return jsonify({"error": str(ex)[:300]}), 500
        return jsonify({"q": query, "vector": used_vector, "results": results})

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
