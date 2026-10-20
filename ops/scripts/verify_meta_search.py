# -*- coding: utf-8 -*-
"""Check the 数据资产检索 page end to end over real HTTP.

Covers the things that are easy to get wrong and invisible in unit tests:
the FAB permissions actually exist, an unauthorised user is refused, an
authorised one gets results, and the write-back marks a comment as human.

Creates its own short-lived admin so it never needs a real password, and
deletes it again on the way out.

Usage: verify_meta_search.py [base_url]
"""
import base64
import os
import sys
import urllib.parse

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8088").rstrip("/")
USER = "metaverify_admin"
PASSWORD = base64.b64encode(os.urandom(18)).decode().replace("/", "").replace("+", "")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       ("  -> %s" % detail) if detail else ""))


class LoopbackSession(requests.Session):
    """A session that replays Secure cookies over plain http.

    Prod sets SESSION_COOKIE_SECURE, and this suite talks to 127.0.0.1 over
    http, so the session cookie would never be sent back and every request
    would look logged out. Clearing the flag on the jar has to happen in
    prepare_request: requests copies cookies into a fresh jar with the default
    policy there, which is why setting a custom policy on the session does
    nothing.
    """

    def prepare_request(self, request):
        for cookie in self.cookies:
            cookie.secure = False
        return super().prepare_request(request)


def login(session, username, password):
    page = session.get("%s/login/" % BASE, timeout=20)
    token = ""
    if 'name="csrf_token"' in page.text:
        token = page.text.split('name="csrf_token"')[1].split('value="')[1].split('"')[0]
    resp = session.post("%s/login/" % BASE,
                        data={"username": username, "password": password,
                              "next": "", "csrf_token": token},
                        allow_redirects=False, timeout=20)
    # Redirects are followed by hand because requests' own redirect loop does
    # not go through prepare_request, so the cookie issued at login would keep
    # its Secure flag and every hop after the first would look logged out.
    for _ in range(5):
        if resp.status_code not in (301, 302, 303, 307, 308):
            break
        target = urllib.parse.urljoin(BASE, resp.headers.get("Location", ""))
        resp = session.get(target, allow_redirects=False, timeout=20)
    return session.get("%s/api/v1/me/" % BASE,
                       timeout=20).status_code == 200


# ------------------------------------------------- permissions + temp account
os.environ.setdefault("SUPERSET_CONFIG_PATH", "/opt/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from superset import db as _db
    from superset import security_manager

    perms = [p for p in _db.session.query(
        security_manager.permissionview_model).all()
        if p.view_menu and p.view_menu.name == "MetaSearch"]
    names = sorted(p.permission.name for p in perms)
    check("FAB 生成了 MetaSearch 权限", len(names) >= 4, ", ".join(names))

    user = security_manager.find_user(username=USER)
    if user:
        security_manager.reset_password(user.id, PASSWORD)
    else:
        security_manager.add_user(USER, "Meta", "Verify", "metaverify@example.com",
                                  security_manager.find_role("Admin"),
                                  password=PASSWORD)
    _db.session.commit()


def cleanup():
    with app.app_context():
        from superset import db as _db2
        from superset import security_manager as _sm

        victim = _sm.find_user(username=USER)
        if victim:
            _db2.session.delete(victim)
            _db2.session.commit()

# --------------------------------------------------------------------- anon
anon = requests.Session()
resp = anon.get("%s/meta-search/" % BASE, allow_redirects=False, timeout=20)
check("未登录访问被挡", resp.status_code in (301, 302, 401, 403),
      "HTTP %s -> %s" % (resp.status_code, resp.headers.get("Location", "")[:60]))

resp = anon.get("%s/meta-search/api/search?q=test" % BASE,
                allow_redirects=False, timeout=20)
check("未登录调接口被挡", resp.status_code in (301, 302, 401, 403),
      "HTTP %s" % resp.status_code)

# -------------------------------------------------------------------- admin
sess = LoopbackSession()
if not login(sess, USER, PASSWORD):
    check("管理员登录", False, "登录失败，后续用例跳过")
    cleanup()
    sys.exit(1)
check("管理员登录", True)

resp = sess.get("%s/meta-search/" % BASE, timeout=20)
check("检索页可打开", resp.status_code == 200 and "数据资产检索" in resp.text,
      "HTTP %s, %d 字节" % (resp.status_code, len(resp.text)))
check("内联脚本带 CSP nonce", '<script nonce="' in resp.text
      and '<script nonce=""' not in resp.text)

# The page hands the CSRF token to its own JS through this meta tag; the test
# reads it the same way so it exercises the path the browser actually uses.
csrf = ""
if 'name="csrf-token"' in resp.text:
    csrf = resp.text.split('name="csrf-token"')[1].split('content="')[1].split('"')[0]
check("页面带 CSRF token", bool(csrf), "%d 字符" % len(csrf))

for query in ["客服首次响应时长", "会话转人工", "ads_cs_chat"]:
    resp = sess.get("%s/meta-search/api/search?q=%s"
                    % (BASE, urllib.parse.quote(query)), timeout=40)
    body = resp.json() if resp.status_code == 200 else {}
    rows = body.get("results") or []
    top = ("%s.%s %s" % (rows[0]["db_name"], rows[0]["table_name"],
                         rows[0]["score"])) if rows else "无结果"
    check("检索「%s」" % query, resp.status_code == 200 and len(rows) > 0,
          "%d 条, 向量=%s, 首位 %s" % (len(rows), body.get("vector"), top))

# -------------------------------------------------------------- field search
resp = sess.get("%s/meta-search/api/search?mode=column&q=%s"
                % (BASE, urllib.parse.quote("退款金额")), timeout=40)
body = resp.json() if resp.status_code == 200 else {}
fields = body.get("results") or []
top = ("%s.%s" % (fields[0]["table_name"], fields[0]["column_name"])
       if fields else "无结果")
check("按字段检索",
      resp.status_code == 200 and len(fields) > 0
      and all(f.get("column_name") and f.get("id") for f in fields),
      "%d 条, 模式=%s, 首位 %s" % (len(fields), body.get("mode"), top))

# A colon used to reach SQLAlchemy's text() as a bind parameter and take the
# whole request down; the space exercises the per-word keyword match.
resp = sess.get("%s/meta-search/api/search?q=%s"
                % (BASE, urllib.parse.quote("order_refund 退款:30")), timeout=40)
check("多词且带冒号的查询不报错",
      resp.status_code == 200 and "error" not in (resp.json() or {}),
      "HTTP %s" % resp.status_code)

# ------------------------------------------------------------------- columns
resp = sess.get("%s/meta-search/api/search?q=%s"
                % (BASE, urllib.parse.quote("客服会话")), timeout=40)
rows = resp.json().get("results") or []
if not rows:
    check("字段明细", False, "没有检索结果可用于下钻")
    cleanup()
    sys.exit(1)
first = rows[0]
resp = sess.get("%s/meta-search/api/columns?db=%s&table=%s"
                % (BASE, urllib.parse.quote(first["db_name"]),
                   urllib.parse.quote(first["table_name"])), timeout=20)
cols = resp.json().get("columns") or []
check("字段明细可取", resp.status_code == 200 and len(cols) > 0,
      "%s.%s 共 %d 字段" % (first["db_name"], first["table_name"], len(cols)))

# ------------------------------------------------------------------- confirm
target = cols[0]
original = target["comment"]
probe = "【校验】" + (original or "临时")
resp = sess.post("%s/meta-search/api/confirm" % BASE,
                 json={"id": target["id"], "comment": probe},
                 headers={"X-CSRFToken": csrf}, timeout=20)
check("确认注释写回", resp.status_code == 200 and resp.json().get("ok") is True,
      "HTTP %s %s" % (resp.status_code, resp.text[:80]))

resp = sess.get("%s/meta-search/api/columns?db=%s&table=%s"
                % (BASE, urllib.parse.quote(first["db_name"]),
                   urllib.parse.quote(first["table_name"])), timeout=20)
after = {c["id"]: c for c in resp.json().get("columns") or []}.get(target["id"], {})
check("写回后来源变为 human",
      after.get("comment_source") == "human" and after.get("comment") == probe,
      "source=%s comment=%s" % (after.get("comment_source"), after.get("comment")))

# restore so the probe does not leave a fake comment behind
sess.post("%s/meta-search/api/confirm" % BASE,
          json={"id": target["id"], "comment": original or "待补充"},
          headers={"X-CSRFToken": csrf}, timeout=20)

# -------------------------------------------------------------- injection
nasty = "'; DROP TABLE bluetti.ads_sr_meta_knowledge; --"
resp = sess.get("%s/meta-search/api/search?q=%s" % (BASE, urllib.parse.quote(nasty)),
                timeout=40)
check("注入字符串不报错也不破坏", resp.status_code == 200, "HTTP %s" % resp.status_code)
resp = sess.get("%s/meta-search/api/search?q=%s"
                % (BASE, urllib.parse.quote("客服")), timeout=40)
check("注入后知识表仍在", bool((resp.json().get("results") or [])))

cleanup()
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
