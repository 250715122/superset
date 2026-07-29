# Superset 变更与生产同步操作手册

> 目的：固化「在开发环境改 Superset → 同步到生产」的标准做法，避免每次重新摸索。
> 适用看板：卡车电池设备分析、全球AI客服·运营分析（两者共用同一套环境与流程）。
> 维护：每次对生产做变更，在文末「变更日志」追加一条。

---

## 一、环境拓扑（先记牢这张表）

| 角色 | 地址 / 访问方式 | Superset 配置 | venv / 代码 | 元数据库 |
|---|---|---|---|---|
| **开发 Superset** | `agi@192.168.41.122`（可直接 ssh/scp） | `/opt/superset/superset_config.py` | `/opt/superset/venv` | PostgreSQL（本机） |
| **生产 Superset** | `10.100.19.1`（**只能经 JumpServer**，不能直连） | `/mnt/data/superset/superset_config.py` | `/mnt/data/superset/venv` | PostgreSQL（本机） |
| **StarRocks（两环境共用）** | 生产 `10.100.11.201:9030` ＝ 开发 `192.168.40.180:19030`（**同一集群**） | — | — | 库名 `bluetti`，root 密码 `ek8Y#MVh8@--]uG` |

**JumpServer 通道**：`jumpserver.poweroak.ltd:2222`，账号 `guote@poweroak.net` / `qq250715122`；登录后菜单 `/Flink` → 选 `1`（StarRocks-01）→ 再 `ssh 10.100.19.1` 到生产。本目录 `_deploy/jump_run.py`、`jump_put_fast.py` 已把这套跳板流程封装好，正常情况下不用手动敲跳板。

**关键事实（最容易踩的认知坑）**：
- **两环境的 StarRocks 是同一个集群**。凡是改数据层（建/改/删 视图、MV、表、改名），在开发执行的瞬间生产就同时生效/受影响，**不需要也不应该在生产再执行一遍数据层 DDL**。反过来，开发改坏数据层 = 生产同时坏。
- **两环境的 Superset 元数据库是各自独立的**。看板、图表、数据集、角色、权限这些「元数据」改动**不会自动同步**，必须分别在两边执行（这正是本手册的核心）。
- 开发看板/数据集 id 与生产**不同**，脚本里不要写死 id，用 slug / table_name / 名称来定位。

| 对象 | 开发 id | 生产 id |
|---|---|---|
| 卡车电池看板（slug `pb-device-analysis`） | 32 | 31 |
| 客服看板（`全球AI客服·运营分析`） | 15 | 29 |
| PB 数据集 latest_geo / active_geo / history | 75 / 80 / 78 | 102 / 103 / 104 |

---

## 二、三类变更，三种同步方式

变更前先判断属于哪一类，方式完全不同：

| 变更类型 | 例子 | 同步方式 | 是否需在生产重做 |
|---|---|---|---|
| **A. 数据层**（StarRocks 视图/MV/表/改名） | 改视图 SQL、温度换算、建 MV、改名 | 开发执行即生效 | **否**（同集群，已生效）。只需在生产 Superset 侧修数据集指向（若表名变了） |
| **B. Superset 元数据**（看板/图表/数据集/角色/权限） | 加图表说明、show value、Tab 图标、数字格式、建角色、改数据集指向 | **本手册第三节的脚本双跑法** | **是**（元数据库独立，两边各跑一次） |
| **C. 前端资产**（自研插件/静态文件） | 新增 ECharts 地图插件、改 SPA 资源 | 打包 tar → 经 JumpServer 分片传输 → 替换 `static/assets` → 重启 | **是**（详见《卡车电池设备分析-数据对象清单.md》五节） |
| **D. 配置 / 自定义模板** | `superset_config.py`、`custom_templates/*.html`（登录页、注入 CSS） | `jump_put_fast.py` 传文件 → 修属主 → **重启 Superset** | **是**（两边各改一次；改配置务必先备份） |

本手册重点是**最常用的 B 类**。C 类是低频重活，A 类"改完就好"。

---

## 三、B 类（元数据）标准同步流程 ★核心

一句话：**写一个幂等、能自动识别环境的 Python 脚本；先在开发跑并验证；再用 `jump_put_fast.py` 传到生产、`jump_run.py` 执行。同一个脚本，两个环境各跑一次。**

### 3.1 脚本编写规范（照抄这个骨架）

```python
# -*- coding: utf-8 -*-
"""一句话说明脚本做什么。Dev & prod compatible. Idempotent. ASCII-safe output."""
import os

# 自动识别环境：开发在 /opt，生产在 /mnt/data
CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard
    # ...用 slug / table_name / 名称定位对象，不要写死 id...
    d = db.session.query(Dashboard).filter_by(slug="pb-device-analysis").first()
    # ...改动...
    db.session.commit()
    print("XXX_DONE|changed=%d" % n)   # 打印可 grep 的结果行
```

**四条硬规矩**（每条都是踩过坑总结的）：
1. **配置路径自动识别**：`/opt` 存在→开发，否则→生产。这样同一个脚本文件两边都能跑，不用改。
2. **幂等**：重复跑结果一致（已改的跳过并打印 `SKIP`）。生产传输/执行偶有中断，必须能安全重跑。
3. **ASCII 安全输出**：中文用 `.encode("unicode_escape").decode()` 再打印，避免跳板 pty 编码乱码。结果行用 `TAG|字段=值` 格式，方便 `grep -E`。
4. **不写死 id**：用 slug / table_name / slice_name 定位，因为两环境 id 不同。

### 3.2 开发环境执行（直连）

```powershell
# 传脚本
scp "本地\脚本.py" agi@192.168.41.122:/tmp/脚本.py
# 执行并只看结果行（2>&1 而不是 2>/dev/null，否则会吞掉报错！见坑4）
ssh agi@192.168.41.122 "cd /opt/superset && ./venv/bin/python /tmp/脚本.py 2>&1 | grep -E 'DONE|FIX|SKIP|Error|Traceback' && rm -f /tmp/脚本.py"
```

改元数据**不需要重启** Superset，浏览器刷新看板即可看到（角色/权限变更同理，用户重新加载页面生效）。

### 3.3 生产环境执行（经 JumpServer）

```powershell
cd "d:\...\BI系统\_deploy"

# ① 传脚本到生产（jump_put_fast 走跳板，自带 sha256 校验）
python jump_put_fast.py 脚本.py /mnt/data/superset/脚本.py 2>&1 | Select-String "REMOTE_SHA_MATCH"
#   期望输出 REMOTE_SHA_MATCH=True

# ② 把要执行的命令写进一个文件（jump_run 只接受单条命令、内部用单引号）
Set-Content -Path "$env:TEMP\_cmd.txt" -Encoding ASCII -Value `
  "/mnt/data/superset/venv/bin/python /mnt/data/superset/脚本.py 2>&1 | grep -E 'DONE|FIX|SKIP|Error|Traceback'; rm -f /mnt/data/superset/脚本.py"

# ③ 经跳板执行（第二个参数是等待秒数，元数据脚本给 240 足够）
python jump_run.py "$env:TEMP\_cmd.txt" 240 2>&1 | Select-String "DONE|FIX|SKIP|Error|Traceback"
```

- `jump_put_fast.py <本地> <生产路径>`：分片 base64 传输 + 逐片/整包 sha256 校验，看到 `REMOTE_SHA_MATCH=True` 才算成功。
- `jump_run.py <命令文件> <等待秒数>`：命令文件里**只放一条命令**、**只能用单引号**（内部会包进双引号 `ssh 10.100.19.1 "..."`）；输出夹在 `BEGIN_MARK`/`END_MARK_RC=` 之间。
- 传输 + 执行一轮约 40s，属正常（跳板多跳）。

### 3.4 验证与清理
- 开发环境可直接用 `requests` 起本地会话做端到端验证（登录 → 调 API → 断言），例：`_deploy/_test_pb_role.py`。
- 涉及权限/角色的，建临时用户实测后**务必删除**（删用户前若它建过对象，需先置空外键，见坑5，脚本 `_cleanup_ro2.py`）。
- 生产验证优先用只读脚本（QueryContext 取数、清点图表/数据源），参考 `_deploy/prod_final_verify.py`。
- 收尾删掉 `/tmp` 与 `/mnt/data/superset/` 下的临时脚本。

---

## 四、踩过的坑（务必避开）

1. **PowerShell 吃引号/多行**：不要把多行 Python 或含 `()` 的命令直接塞进 `ssh "..."`，PowerShell 会解析报错。**对策**：脚本写成 `.py` 文件用 `scp` 传，或把命令写进 `.txt` 用 `jump_run.py`。
2. **`Set-Content` 编码**：写命令文件一律加 `-Encoding ASCII`，否则跳板端可能乱码。
3. **StarRocks 不能从生产 Superset 直连测**：生产机连 `192.168.41.85:9030` 会 `Connection refused`。要查数据层，走 Superset 引擎（`Database.get_sqla_engine()`）或用 root 从能连通的机器查。
4. **`2>/dev/null` 会吞掉报错**：调试期一律用 `2>&1 | grep -E '...|Error|Traceback|Integrity'`，否则脚本静默失败你还以为成功了（本次删用户就因此漏看了外键报错）。
5. **删用户/对象报外键约束**：`ForeignKeyViolation on ab_user`。用户建过看板/图表/标签时，`created_by_fk`/`changed_by_fk` 会挡住删除。**对策**：遍历 `information_schema` 找所有指向 `ab_user.id` 的外键列，逐一 `UPDATE ... SET col=NULL WHERE col=uid`，再删用户（脚本 `_deploy/_cleanup_ro2.py`）。
6. **改名/改指向后 perm 不同步**：数据集 `table_name` 改了要同步 `perm = t.get_perm()` 并 `add_permission_view_menu('datasource_access', perm)`，否则鉴权错乱。
7. **权限调试别只看角色**：若"角色明明没有写权限，用户却能写"，先查 **Public 角色**（`PUBLIC_ROLE_LIKE` 会把 Gamma 权限复制给它，FAB 的 `is_item_public` 会先于角色判定放行）。详见第六节专题。
8. **看板设了 RBAC 角色列表 = 对其他所有角色隐藏**：给某看板挂了角色后，别的只读角色就看不到它了，需要把新角色一并加进该看板的允许列表。
9. **`chartsInScope` 跨环境不可信**：它是缓存字段，看板导入时不会被重映射（`scope.excluded` 会），生产里存的可能还是开发的图表 id。判断筛选器作用域要用 `scope.excluded` 推导（全部图表 − excluded），与前端 `DashboardContainer.tsx` 的算法一致。详见第六节时间筛选器专题。
10. **时间范围筛选器需要图表侧有"接线"**：图表必须带一个 `TEMPORAL_RANGE` adhoc 过滤器（comparator 填 `"No filter"` 即可）来提供时间列，否则看板的时间范围会被静默忽略。新建图表时记得加。
11. **切换 `AUTH_TYPE` 或升级大版本后必须跑 `superset init`**：认证方式变了，FAB 提供用户页面的视图类也会变（AUTH_DB→`UserDBModelView`，AUTH_OAUTH→`UserOAuthModelView`），加上 Superset 6 新增的 `UserInfoView`，这些新视图的权限条目不会自动创建，表现为**连 Admin 都打不开 Info 页**。`superset init` 才会补建。**但它只授予内置角色（Admin/Alpha/Gamma），自定义角色必须另外补**（`fix_selfservice_perms.py`）。详见第六节 Info/改密码专题。
12. **排查"点某按钮报无权"，先确认按钮真正请求的 URL**：不要凭页面名猜权限。Superset 6 里 `/user_info/`（导航栏 Info，权限 `can_read@user`）和 `/users/userinfo/`（FAB 旧页，权限 `can_userinfo@UserOAuthModelView`）是两个不同页面——本次就因为按 `userinfo` 过滤路由漏掉了带下划线的 `/user_info/`，导致第一轮只修好了没人点的那个页面。菜单地址在 `superset/views/base.py` 的 `user_info_url`。
13. **生产 `SESSION_COOKIE_SECURE=True`，明文 HTTP 跑不了登录验证脚本**：Secure cookie 不会回发到 `http://127.0.0.1:8088`，会话拿不住，表现为"密码错误"而非真实权限问题。生产验权限用 app context 里的 `sm.has_access()` 直接判定；想连路由和序列化一起验，用坑 18 的测试客户端注入登录态。
14. **从 Windows 传 `.sh` 到 Linux 记得去 CRLF**：`bash` 会报 `$'\r': command not found` 或 `head: invalid trailing option`。执行前先 `sed -i 's/\r$//' 脚本.sh`（`.py` 不受影响）。
15. **判断前端是否生效，不能靠"抓服务端 HTML 搜关键字"**：SPA 的文案是运行时用 JS 翻译/渲染的，服务端返回的 HTML 里没有中文也很正常。要看 `data-bootstrap` 里的 `locale` 字段（HTML 转义过，需 `html.unescape` 再 `json.loads`）和 `/superset/language_pack/<lang>/` 的返回。同理，`Access is Denied` 那类提示是 Flask flash 被前端渲染成 toast，别只盯着 HTTP 状态码。
16. **`pip` 升级 Superset 会冲掉写进 site-packages 的产物**：翻译包（`messages.json`/`.mo`）就在里面。升级后需重跑 `_gen_lang_packs.sh` + `_install_lang.sh`。
17. **清空 Public 权限后要跑全用户审计**：历史上很多自定义角色是"薄角色"（只有几条 `datasource_access`），隐性依赖 `PUBLIC_ROLE_LIKE=Gamma` 提供的浏览基线。Public 清空后这些用户会缺权限（本次 6 个真实用户的 `/api/v1/me/` 变 403）。用 `_deploy/_audit_users.py` 逐用户体检。
18. **HTTP 探针里"页面返回 200"根本不能当作登录成功**：登录失败会 302 回登录页，而登录页本身也是 200，于是断言 `status_code == 200` 稳稳通过——本次验证看板渲染就这么拿到过一个假阳性（`/superset/dashboard/...` 200，实际拿到的是登录表单）。**两个对策**：① 断言里加内容判据，比如 `'name="password"' not in body`；② 干脆别走密码登录，用 app 自己的测试客户端注入登录态：

    ```python
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = str(admin.id)   # flask-login 认这个键
            sess["_fresh"] = True
        c.get("/api/v1/dashboard/<slug>")      # 就是浏览器那条链路
    ```

    这法子不依赖密码、不受自定义登录页影响，生产上也绕开了坑 13 的 Secure cookie 问题，比 `sm.has_access()` 更接近真实请求（会走 `@protect`、路由、序列化）。

19. **判断一条权限危不危险，别看名字，看它守的 HTTP 动词**：Superset 的权限命名不守规律——`can_bulk_create`（建标签）、`can_invalidate`（清缓存）名字里没有"写"字；`can_tag` 在代码里校验、**根本没有路由**；反过来 `can_read` 守的却是 `POST /api/v1/chart/data`，只看动词又会误杀。`can_delete_embedded` 更离谱：权限行是 FAB 按方法名建的，但处理函数上写的是 `@permission_name("set_embedded")`，握着它什么也删不了。**对策**：用 `_deploy/_perm_routes.py` 反查（同时读 `method_permission_name` 和 `@permission_name`，再取 `_urls` 上的动词），别靠名字黑名单——本次就是名字黑名单漏掉了 4 类真写权限。

20. **`Gamma` 不是稳定基线，`superset init` 会给它加权限**：以"复制 Gamma 再去掉写"建的角色，会随 Gamma 漂移（本次开发 106 条 vs 生产 95 条，多出来的含 `can_read@security`，能列角色/组/注册申请）。**对策**：把该保留什么写死在脚本里并自检，别假设 Gamma 不变。

21. **迁到组之后，脚本里判断"谁持有某角色"必须用 `sm.get_user_roles(u)`**，不能用 `u.roles`——后者只有直授角色，迁组后是空的，脚本会直接得出"没人持有这个角色"（本次探针就这么中断过一次）。同理排查用户权限时，UI 的用户列表里"Roles"一栏也只显示直授角色，得去 `Security ▸ List Groups` 看组。

22. **改 `position_json`（看板布局）前必须备份，改完必须验结构**：布局 JSON 结构坏掉的表现是**整个看板白屏**，而且从图表数量上看不出来。改之前先跑 `_pb_backup.py` 留快照；改完至少验这几条：目标节点在预期位置、`children` 里引用的 id 都存在（无悬空）、没有谁都不引用的孤儿节点、图表节点数不变、注入的 HTML `<div>` 闭合平衡。**撤销后要证明"真的还原了"，就拿改动前的快照和库里的 `position_json` 做整体对象比较**（`old == pos`），别只数节点个数。工具：`_verify_revert.py`（会自己在快照里递归找出 `ROOT_ID` 那棵布局树，不用管快照的键名叫什么）。

23. **FAB 的 `sm.add_role()` 会立刻 `commit` 整个 session，"dry-run"里千万别用**：它不止提交新角色，还把 session 里所有**挂起的其它改动一起提交**。本次授权迁移的 dry-run 循环里每次 `add_role` 都把上一轮暂存的 `dashboard.roles.append` 刷进了库——所谓预演实际把受众角色挂上了 11 块看板，而组还没拿到角色，**开发环境观众当场全部失明**（幸好推导快照立刻暴露：所有人可见集合变空）。**对策**：脚本里建角色一律 `sm.role_model(name=...)` + `session.add()`，提交时机自己攥着；出事后用 `_undo_leak.py` 这类"摘光 `看板·*` 绑定"的一次性脚本回退。同类坑：`find_permission_view_menu` 只读安全，但 FAB 里名字带 `add_`/`create_` 的辅助方法多半自带 commit。

24. **测试客户端量权限时，每个用户都要开全新的 `app_context()`，而弹出上下文会把 scoped session 一起 remove**：`g.user` 挂在 app context 上，复用一个上下文连测多人会串号（第一人的身份粘在 `g` 上）；但新开上下文弹出时 flask-sqlalchemy 的 teardown 会 `session.remove()`，**外层拿着的所有 ORM 对象全部 detach**（表现为 `DetachedInstanceError`）。**对策**：跨快照只携带纯 id/名字，每轮操作前重新查询对象（`authz_model.py` 的 `visible()`/`snapshot()` 即按此写法）。

25. **6.0.1 的图表 API 可见性只认数据集授权，Owner 不算数**：把用户设成图表 Owner + 给 Gamma，`GET /api/v1/chart/<id>` 照样 404——`ChartFilter`（图表 REST API 的 base filter）按"用户对图表底层数据集有无 `datasource_access`"过滤，压根不查 `owners`（看板 API 的 `DashboardAccessFilter` 则认 Owner，两者行为不一致，别互相类推）。**表现**：能在看板里"看到"这张图（走 RBAC 豁免渲染），点编辑却 404/白屏。**对策**：给编辑者发一个含相应数据集 `datasource_access` 的薄数据角色，Owner 只解决"能不能保存"，解决不了"能不能看见"。`grant_dashboard_editor.py` 已把两件事一起做掉。

---

## 五、常用脚本索引（`_deploy/`）

| 脚本 | 用途 | 备注 |
|---|---|---|
| `jump_put_fast.py <本地> <生产路径>` | 经跳板传文件到生产，带 sha256 校验 | 看 `REMOTE_SHA_MATCH=True` |
| `jump_run.py <命令文件> <秒>` | 经跳板在生产执行单条命令 | 命令文件用单引号、ASCII |
| `apply_chart_desc.py` | 批量写图表悬停口径说明（两看板） | 幂等，改文案重跑 |
| `pb_show_value.py` | PB 所有柱状图开启 show value | 幂等 |
| `apply_tab_icons.py` | 两看板 Tab 名称加图标 | 幂等 |
| `pb_pct_unify.py` | PB 的 SOC/SOH 卡片统一百分比显示 | 幂等 |
| `authz_model.py {baseline\|migrate\|revoke\|retire}` | **授权模型唯一真源**：生成`只读基线`、逐看板建零权限受众角色并挂 RBAC、回收数据授权、退役旧角色；每步带全员可见性零漂移自检与自动回退 | 幂等，支持 `--dry-run`（**注意 dry-run 仍会建空角色**），取代 `ro_role_policy.py`/`groups_setup.py` |
| `authz_probe.py` | 以每组代表真实走 HTTP 验证新模型：列表/打开/取数/分享/筛选/下钻/中文包 + 负向（建看板、脱离看板取数应 403） | 只读，改授权后必跑 |
| `patch_editor_ownership.py` | 配置补丁：重写 `raise_for_ownership`，持挂在看板 RBAC 上的`编辑·X`角色 = 该看板及其图表的 Owner（**需重启**，编辑授权页面化的前提） | 幂等，备份 `.bak.editorown`，语法自检失败自动还原 |
| `editor_group_setup.py <看板id>` | 每看板一次性：建`编辑·<看板名>`角色（含数据集授权）+ 挂看板 RBAC + 建组「<看板名>编辑」（Gamma+该角色）；之后日常授权=页面上往组加人 | 幂等，支持 `--dry-run` |
| `_editor_probe.py <看板id> <观众>` | 编辑授权端到端验证：零角色零 Owner 探针用户入组后可 GET/PUT 图表、跨看板被拒、观众被拒，自动清理探针用户 | 只读语义（探针 PUT 用原值） |
| `grant_dashboard_editor.py <看板id> <用户>` | 旧路径（直授+挂 Owner）：进看板制作者组 + 直授`编辑·<看板名>`角色 + 看板/图表/数据集 Owner；适合临时给单人开权限 | 幂等，支持 `--revoke`/`--dry-run` |
| `_authz_snapshot.py` | 全量授权关系快照（角色→权限、用户/组→角色、看板→RBAC）落 JSON 到主机 `backups/` | 只读，动授权前先跑 |
| `fix_ds54_guard.py [apply\|revert]` | 生产数据集 54（电池包明细，71 亿行）加"无时间筛选返回空"护栏，防裸查打爆 StarRocks 内存 | 幂等，带备份/回滚与真实用户验证 |
| `_user_reassign.py {inventory\|apply}` | 删用户前把名下全部 DB 引用移交他人（按 `information_schema` 反查所有指向 `ab_user` 的外键；日志置 NULL、成员关系删除、其余改归属，唯一键冲突自动去重） | `apply <src> <dst> [--dry-run]`，src/dst 可用用户 id |
| `_test_ro_capabilities.py` | 以真实持角色用户跑 15 项能力探针（该能用的能用、该拒的拒）；参数用 ASCII 别名 `pb`/`all` | 只读，改完角色必跑 |
| `_audit_role_perms2.py` | 打印某角色全部权限并标出非只读项（白名单法，漏不掉） | 只读，做权限漂移巡检 |
| `_perm_routes.py` | 反查某权限守着哪个方法、哪些 HTTP 动词 | 只读，判断"这权限危不危险"必备 |
| `groups_setup.py` | 建组、挂角色、把角色组合一致的用户迁进组（**已退役**：组已建成，角色绑定改由 `authz_model.py` 管，别再重跑） | 历史一次性 |
| `_chk_groups_ui.py` | 验组管理页可用 + 逐组核对角色与成员（含 Group API） | 只读 |
| `_inv_access.py` | 盘点看板 RBAC / 角色持有人 / 用户组归属 | 只读，授权前先看这个 |
| `fix_permalink_salt.py` | 修分享链接 500（salt 由 base64 重编码为 JSON） | 幂等，已正常的会 SKIP |
| `_dbg_permalink2.py` | 定位 permalink salt 的编解码问题 | 只读 |
| `fix_public_role.py` | 关闭 Public 角色写权限旁路（改配置+清权限，**需重启**） | 幂等，带备份与护栏 |
| `head_custom_extra.html` | 注入 CSS 修下拉过窄 + JS 补「修改密码」入口 + **ES2025 Set 方法 polyfill**（旧浏览器切看板 Tab 报 `difference is not a function`）（放 `custom_templates/`，**需重启**） | 覆盖内置空模板 |
| `_test_set_polyfill.js` | Node 模拟旧浏览器（删原生 Set 方法后加载 polyfill）验证 7 个方法 + reducer 链式调用形态 | 在构建机 `gt@192.168.56.101` 跑（运行环境无 Node） |
| `_verify_prod_pwd.py` | 重启后复验改密路由 / 模板解析 / 用户权限 | 只读 |
| `_gen_lang_packs.sh` | 构建机上用官方 po2json 生成 21 个语种前端语言包 | 在 `/opt/superset-build/superset-frontend` 跑 |
| `_install_lang.sh <venv> <tgz>` | 装前端语言包 + 编译后端 `.mo`（**需重启**） | 自动推导路径/属主 |
| `set_default_locale_zh.py` | `BABEL_DEFAULT_LOCALE` 设为 `zh`（**需重启**） | 幂等，带备份 |
| `heal_stale_locale.py` | 一次性纠正老会话里烙着的旧默认语言（**需重启**） | 幂等，带备份，自适应缩进 |
| `_test_locale_heal.py` | 预置会话跑 5 个用例验证上面的迁移钩子 | 只读，测试客户端 |
| `_test_lang_e2e.py` / `_verify_prod_lang.py` | 语言切换端到端验证 / 生产免 HTTP 复验 | 只读 |
| `fix_selfservice_perms.py` | 给所有非 Public 角色补自助权限（Info/`me` 接口） | 幂等 |
| `enable_password_views.py` | 补注册 OAUTH 下被跳过的改密码视图（**需重启**） | 幂等，带备份 |
| `_audit_users.py` | 全用户权限体检（浏览/Info/改密） | 只读，改 Public 后必跑 |
| `_verify_prod_zh.py` | 按用户逐条判定 `has_access`（生产验权限用这个，别用 HTTP） | 只读 |
| `_find_user_info_route.py` | 反查某路由由哪个视图提供、要什么权限 | 只读，排查"无权"必备 |
| `_snap_perms.py` / `_diff_perms.py` | 角色权限快照与前后对比 | 只读，跑 `superset init` 前后用 |
| `pb_fix_timefilter.py` | 补齐图表的时间列绑定 + 刷新作用域缓存 | 幂等 |
| `_verify_timefilter.py` | 逐图对比"选/不选时间范围"的取数差异 | 只读 |
| `_verify_head_css.py` | 验证 Jinja 是否解析到自定义模板 | 只读 |
| `_dump_layout.py` | 打印看板逐 Tab 布局树（行/图表/宽高） | 只读，改布局前先看这个 |
| `_verify_revert.py [快照.json]` | 校验布局结构完整性，并与备份快照整体比对 | 只读，撤销布局改动后用 |
| `pb_tab_banner.py [remove]` | PB 每个 Tab 顶部插说明条 Markdown（**已撤回，见日志 11**） | 幂等，带 remove 回滚；当前两环境均未启用 |
| `prod_final_verify.py` | 两看板全量巡检（只读） | 只读，随时可跑 |
| `prod_import_pb.py` / `prod_cs_repoint.py` | 看板导入 / 数据集改指新名 | 历史一次性 |

---

## 六、变更日志

### 2026-07-28（本次，元数据 B 类，开发+生产均已应用）

均为 Superset 元数据改动，走第三节双跑法；数据层未动。

1. **卡车电池只读角色**（当时脚本 `pb_readonly_role.py`，**已被 `ro_role_policy.py` 取代并删除**）：新建角色「卡车电池只读」＝ Gamma 只读权限 + 仅 3 个 PB 数据集的 `datasource_access` + 绑定看板 RBAC。授予该角色的用户**只能看这一个看板**。开发用临时用户 `pbviewer` 端到端验证（看板列表仅 1 个、越权查客服数据集被 403）后删除。生产角色含 95 项权限、数据集 id 102/103/104。**使用**：给用户只勾这一个角色，勿叠加 Gamma。
2. **图表悬停口径说明**（`apply_chart_desc.py`）：给两看板每个图表 `description` 写入「口径+表达式+数据源」。开发 PB 38/38、CS 50/50；生产 PB 38/38、CS 51/51（生产多 1 个同名历史图）。看板中图表标题旁 ⓘ 悬停显示。
3. **柱状图显示数值**（`pb_show_value.py`）：PB 全部 10 个柱状图开启 `show_value`。开发新开 6 个（4 个原已开），生产新开 9 个（1 个原已开）。
4. **Tab 图标**（`apply_tab_icons.py`）：PB 5 个 Tab、CS 8 个 Tab 名称前加 emoji（📊运营总览 / 🗺️设备分布 / 🔋电池健康 / ⚡充放电分析 / 📋数据详情；📌管理摘要 / 📈经营对比 / 💬Chat在线对话 / 📧Email与VoC / 🙋转人工根因 / 🔄体验与回访 / 📋数据明细 / 📅客服周报）。
5. **百分比显示统一**（`pb_pct_unify.py`）：PB「平均SOC/平均SOH」原显示裸数字（0–100），改为 `AVG(...)/100` + d3 百分比格式（`.1%` / `.2%`），与「SOH数据覆盖率」一致；标题去掉多余「(%)」。两环境各改 3 张卡片。
6. **全局看板只读角色**（当时脚本 `all_dash_readonly_role.py`，**已被 `ro_role_policy.py` 取代并删除**）：新建角色「全局看板只读」＝ 复制 Gamma 并剥离 11 项内容编辑写权限 + `all_datasource_access`（保留筛选器状态/permalink/explore 表单态的写权限，否则筛选和分享链接报错）。能看**全部看板**但不能编辑/建图。开发用临时用户 `roviewer` 验证（可见全部看板、改图 403）后清理（含外键置空删用户）。**使用**：只勾这一个角色。

7. **修复「只读角色仍能编辑/另存图表」**（`fix_public_role.py` + 只读角色脚本，需重启）：见下方专题。
8. **权限下拉宽度 CSS 同步生产**（`head_custom_extra.html`，D 类·自定义模板，需重启）：角色编辑弹窗里的权限下拉被 Superset 前端硬编码成 168px（`superset-ui-core` 的 `Select.tsx`：`popupMatchSelectWidth={selectAllEnabled ? 168 : true}`）。用 CSS 覆盖拉宽到与输入框同宽，注入方式是在 `custom_templates/` 放 `head_custom_extra.html`（Superset 的 `templates/superset/spa.html` 第 81 行 `{% include "head_custom_extra.html" %}`，内置为空文件，被 `FLASK_APP_MUTATOR` 的 ChoiceLoader 优先命中我们的同名文件）。开发早前已生效，本次同步到生产 `/mnt/data/superset/custom_templates/`（sha256 一致、属主改回 `cloudapp:cloudapp`、`chmod 644`），重启后验证 Jinja 解析到的正是覆盖文件且 CSS 正常渲染。
   - **验证要点**：不要用登录页验证——登录页走的是独立的 `login_dual.html`，不继承 `spa.html`，抓 `/login/` 永远搜不到这段 CSS。正确做法是在 app context 里 `app.jinja_env.get_template("head_custom_extra.html")` 看 `.filename` 指向哪个文件（脚本 `_deploy/_verify_head_css.py`）。
9. **修复「点 Info 报 Access is Denied / 不能自己改密码」**（`superset init` + `fix_selfservice_perms.py` + `enable_password_views.py` + `head_custom_extra.html`）：**开发+生产均已应用并重启验证**。见下方专题。
10. **修复「切换语言无效」＋ 中文设为默认语言**（构建机 `po2json` + `_install_lang.sh` + `set_default_locale_zh.py` + `heal_stale_locale.py`，需重启）：**开发+生产均已应用并重启验证**。其中 `heal_stale_locale.py` 解决"改了默认语言但老用户仍是英文"——FAB 会把默认语言写进 session，存量会话会一直粘着旧值。见下方专题。
11. **Tab 顶部说明条：已尝试并撤回，两环境均未启用**（`pb_tab_banner.py`）。做法是在 PB 每个 Tab 的 `children[0]` 插一行满宽 MARKDOWN（内联 HTML 样式，依赖两环境都已设的 `HTML_SANITIZATION=False`），文案写的是各 Tab 的口径要点（快照含离线设备 / SOH 覆盖率低导致分布右偏 / 电量是累计计数器非区间增量 / 温度已转摄氏 / 电流正负号含义）。**开发环境实装后视觉效果不理想，已按需求撤回；生产自始至终没有改过**。
    - **还原证据**：撤回后拿改动前快照 `backups/pb_dash_20260728_163855.json` 与库里 `position_json` 整体比对，结果 `layout identical to pre-change backup`（节点数 77→67，38 图不变，无悬空/孤儿）；生产独立复查同为 67 节点、38 图、无残留。
    - **脚本处置**：apply 脚本**只留在本地 `_deploy/`，已从开发服务器 `/opt/superset/` 删除**，避免日后误跑。想重做换个设计的话，改 `pb_tab_banner.py` 里的 `BANNERS` 字典重跑即可，`python pb_tab_banner.py remove` 可干净回滚（两条路径本次都实测过：重跑是原地改写不叠加，回滚后可再装）。
    - **副产物**（已入索引，与本条无关也能用）：`_dump_layout.py` 看布局树、`_verify_revert.py` 验结构+比快照，以及坑 18 记录的免密登录态探测法。
12. **两个只读角色复审并收紧**（`ro_role_policy.py`，**取代并删除** `pb_readonly_role.py` / `all_dash_readonly_role.py`）：判定依据从"权限名黑名单"换成"看权限实际守的 HTTP 动词"，补删了名字里没有写字样的真写权限（打标签/清缓存/服务端截图）与一批无效死条目。开发各删 14 条、生产各删 9 条，`residual_write=0`，16 项能力探针两环境全通过。见下方专题。
13. **授权方式改为「用组管人」**（`groups_setup.py`）：建立 8 个受众组（开发 7 个，其中「电池包数据观众」因该角色开发环境不存在而跳过），把角色组合一致的用户迁入组并摘掉直授角色——开发迁 15 人 / 摘 24 条，生产迁 16 人 / 摘 28 条，两环境**零权限漂移**（脚本会前后比对"有效角色 + 可见看板集合"，不一致就自动回滚）。以后开权限只需在 `Security ▸ List Groups` 里往组加人。见下方专题。
14. **修复分享链接（permalink）500**（`fix_permalink_salt.py`）：`key_value` 里两条 salt 存的是 base64 编码 JSON，6.0.1 按纯 JSON 解码报错，导致所有人（含 admin）复制永久链接都 500。就地重编码后两环境的看板/Explore 分享链接均返回 201，且生成的链接可正常打开。见下方专题。
15. **授权模型重构：只读基线 + 看板受众角色 + 组**（`authz_model.py` 四步 + `authz_probe.py` 验证，**取代并删除** `ro_role_policy.py`、退役 `groups_setup.py`）：唯一能力角色`只读基线`由代码生成（顺带修复了 Gamma-Readonly 持有者**打不开看板页**的存量缺陷——缺 `can_dashboard@Superset` 等 18~21 条）；每看板一个零权限`看板·X`角色挂 RBAC，观众数据授权清零（开发 14 条、生产 18 条全部回收），旧数据角色删除（开发 6 个、生产 8 个含孤儿 SOH异常检测）；`AUTH_USER_REGISTRATION_ROLE` 两环境改为`只读基线`并重启。每步带全员可见性零漂移自检，探针验证取数走 RBAC 豁免、脱离看板直查 403。见下方专题。
16. **生产数据集 54 加裸查护栏**（2026-07-29，`fix_ds54_guard.py`）：电池包明细虚拟数据集底表 `bluetti.dwd_iot_pack` 有 71 亿行（5700 万/天），时间筛选靠 Jinja `get_time_filter` 下推到分区列 `pt`；没有时间筛选的查询（重放保存的 query_context、手工构造的 `/api/v1/chart/data`、Explore 裸开图）会全表聚合直至 StarRocks 报 `Memory of process exceed limit`。护栏：数据集 SQL 末尾追加 `{% if not tf.from_expr and not tf.to_expr %} AND 1 = 0 {% endif %}`——无时间筛选直接返回空。看板不受影响（时间筛选必填、默认 Last week，且作用域覆盖 ds54 全部 8 张图，脚本会先核对再动手）。验证：裸查从 OOM 变为 0.2s 空结果，看板路径 1.4s 返回 9418 行；SQL 备份在 `backups/ds54_sql_20260729_081548.txt`，`fix_ds54_guard.py revert` 可回滚。**验证时的坑**：模拟看板取数要把图表自带的 `TEMPORAL_RANGE="No filter"` 条目**替换**成目标时间范围——`get_time_filter` 取第一条匹配，追加第二条会被"No filter"挡住，误判成护栏误伤。
17. **裁撤「看板·全部」角色与「全部看板观众」组**（2026-07-29，`_drop_aud_all.py`，两环境）：按需求取消"一个角色看全部看板"的快捷通道，逐看板受众角色成为唯一授权路径（要看全部就把各「看板·X」都挂给对应组）。同时定案苗艺萌只看「卡车电池设备分析」：两环境移入「卡车电池观众」组（开发从「全部看板观众」移出、生产从「看板制作者」移出），验证可见集合开发 8 块→1 块、生产 0 块（Gamma 制作者本就看不到列表）→1 块，其他用户零变化。`authz_model.py` 已同步去掉自动创建/挂载「看板·全部」的逻辑。

18. **编辑授权工具化**（2026-07-29，`grant_dashboard_editor.py`，开发验证）：排查"郭特进了 VOC 项目组+Gamma 仍编辑不了 VOC 图表"发现 6.0.1 图表 API 的可见性只认数据集 `datasource_access`、不认 Owner（坑 25），单靠组+Gamma+Owner 凑不齐编辑条件。将"能力（看板制作者组）+ 数据（自动生成`编辑·<看板名>`薄角色）+ Owner（看板/图表/数据集）"三要素封装成一条命令，结尾以目标用户实测图表 API 与 Explore 均 200。开发环境对看板 9（VOC）+ 郭特落地并复跑验证幂等；早前手工建的临时角色「编辑·VOC」已删除，由规范命名的「编辑·VOC项目看板」取代。生产暂无编辑授权需求，未跑。

19. **编辑授权页面化**（2026-07-29，`patch_editor_ownership.py` + `editor_group_setup.py`，两环境已打补丁并重启；编辑组暂只建了开发的「VOC项目看板编辑」）：把日志 18 的脚本式编辑授权升级为"往组里加人即可"。做法：在 `CustomSsoSecurityManager` 重写 `raise_for_ownership()`——用户持有的`编辑·X`角色若挂在目标看板的 RBAC 上，则对该看板及其全部图表视同 Owner（判定异常一律回落拒绝）。每看板一次性跑 `editor_group_setup.py` 建角色/挂 RBAC/建「<看板名>编辑」组，日常在 `Security ▸ List Groups` 加人/移人。开发以零角色零 Owner 的探针用户验证：入组即可改本看板图表（200）、跨看板 404、观众 403；郭特已从直授迁入组。配置备份两环境 `superset_config.py.bak.editorown`。详见第六节授权模型专题"编辑授权"小节。

20. **修复旧浏览器打开带 Tab 看板报「意外错误 TypeError: (intermediate value).difference is not a function」**（2026-07-29，`head_custom_extra.html` 追加 Set polyfill，两环境已重启生效）：张华在开发环境打开看板 32 时报此错。根因：Superset 6 前端在看板 Tab 切换的 reducer 里直接调用 **ES2025 原生 Set 方法**（产物 `3397.*.entry.js`：`new Set(e.activeTabs).difference(...)`、`.union(...)`），Chrome/Edge<122、Firefox<127、Safari<17 没有这些方法，一切 Tab 即抛 TypeError（服务端无任何报错，logs 表只见正常取数——**这类"意外错误"弹窗都是前端 JS 异常，排查方向是浏览器兼容性/前端产物，不是后端**）。修法：在 `head_custom_extra.html`（`<head>` 内、早于应用 bundle 执行）补 7 个 Set 方法的 polyfill，新浏览器原样跳过；用 Node 在构建机模拟旧浏览器全 PASS（`_test_set_polyfill.js`），两环境重启后以 admin 实测渲染页均含 polyfill 且原有注入完好。备份：开发 `head_custom_extra.html.bak.setpoly`、生产同名（`/mnt/data/superset/custom_templates/`）。也可让用户直接升级浏览器，但 polyfill 对所有旧浏览器用户一次解决。

#### 专题：看板时间范围筛选器"不起作用"（2026-07-28）

**现象**：卡车电池看板选了顶部「时间范围」，充放电分析等多个 Tab 的图表数字纹丝不动。

**根因**：原生「时间范围」筛选器只会往查询里塞一个 `time_range` 字段，它**本身不带列名**。后端要把它变成 WHERE 条件，靠的是图表自己的 `TEMPORAL_RANGE` adhoc 过滤器提供时间列；图表若没有这个过滤器，`time_range` 就被静默丢弃。渲染 SQL 实测：

| 情形 | 生成的 SQL |
|---|---|
| 只有 `time_range`，无 `TEMPORAL_RANGE` | **完全没有 WHERE** ← 出问题的图表 |
| `TEMPORAL_RANGE` 占位 `"No filter"` + `time_range` | `WHERE last_time >= ... AND last_time < ...` ← 正常图表 |
| `TEMPORAL_RANGE` 占位 `"No filter"`，不选时间范围 | `WHERE true = 1`（空操作，行为不变） |

看板上只有 11 张图（建看板时随手加过）带这个占位，其余 26 张都没有，所以表现为"部分图表响应、部分不响应"。**与筛选器作用域无关**——作用域一直是对的。

**修复**：给作用域内每张缺失的图表补一个 `TEMPORAL_RANGE` 占位（列取数据集的 `main_dttm_col`：`ads_tb_device_latest_geo`→`last_time`、`ads_tb_active_geo`→`biz_date`），comparator 固定 `"No filter"`。因为不选时间范围时它渲染成 `true = 1`，所以**不改变默认行为**，只是把"接线"接上。脚本 `_deploy/pb_fix_timefilter.py`（幂等）。

**踩到的坑：`chartsInScope` 存的是旧环境的图表 id**。脚本最初按 `chartsInScope` 判断作用域，在生产 37 张图全部报 "not on dashboard"——因为看板是从开发导入的，导入逻辑重映射了 `scope.excluded`（生产 id，正确），却把派生字段 `chartsInScope` 原样搬了过来（还是开发的 662–757）。查前端 `DashboardContainer.tsx` 确认：**`chartsInScope` 只是缓存，每次渲染都会用 `scope`(rootPath+excluded) + 实际布局重算**，所以生产看板的筛选行为一直是正确的，被误导的只是脚本。脚本已改为按前端同样的方式推导（全部图表 − `excluded`），并顺带刷新那份过期缓存（生产 5 个筛选器共清理 113 个失效 id，开发清理 3 个）。

> 教训：**任何按 id 判断看板结构的脚本，都不要读 `chartsInScope`**，要从 `scope.excluded` 推导。跨环境的 id 一律不可信。

**验证**（开发/生产各跑一遍，结果一致）：作用域内 37 张图逐张跑真实查询，对比"不选时间范围"与"选 2026-07-20:07-25"的结果——**32 张数值改变**（如设备总数 7782→729、累计充电量 104367→4374 kWh），5 张不变且均已确认正常：`设备明细`/`SOH最低设备TOP50`/`设备数据明细` 是受 50 行上限约束的明细表（SQL 里时间谓词确实存在，实测 `设备明细` 50→33 行）、`低SOH设备数(<90%)` 全库恒为 0、`累计充放电量趋势` 取单调计数器的 MAX 两窗口相同。

**注意**：`近7天活跃设备`/`近30天活跃设备` 这两个 KPI 自带固定窗口（`last_time >= now()-7d`），现在会与看板时间范围取交集。若希望它们始终忽略全局时间范围、只看自己的窗口，把它们从「时间范围」筛选器的作用域里排除即可。

#### 专题：只读角色为什么"不只读"，以及怎么修（2026-07-28）

**现象**：授予只读角色的用户，仍能在 Explore 里编辑图表并「另存为」，还能新建看板。

**根因（不是角色配错了）**：两环境 `superset_config.py` 都设了 `PUBLIC_ROLE_LIKE = "Gamma"`。它让 FAB 在每次启动时把 Gamma 的全部权限**复制到 Public（匿名）角色**上，其中就包含 `can_write on Chart` 和 `can_write on Dashboard`。而 FAB 的 `@protect` 装饰器判定顺序是：

```
① permission 是否在 base_permissions  →  ② is_item_public(perm, view) 若为真则直接放行  →  ③ 才轮到 has_access() 查当前用户的角色
```

只要 Public 角色持有某权限，第 ② 步就对**所有人**放行，角色 RBAC 根本不会被检查。所以无论把只读角色配得多干净都没用——实测该角色 `has_access(can_write, Dashboard)` 确实是 `False`，但写请求照样成功。

**结论：单靠改角色权限无法解决**，必须同时做两件事（缺一不可）：

1. **改配置**：`PUBLIC_ROLE_LIKE: Optional[str] = None`，阻止每次启动重新复制；
2. **清库**：把 Public 角色已有的权限清空（只改配置不会移除已复制的权限）；
3. 重启 Superset 使配置生效。

以上三步已封装进 `_deploy/fix_public_role.py`（含配置改写 + 自动备份 + 安全护栏：若启用了嵌入式看板或有用户挂 Public 角色则中止）。

**顺带修的两个问题**：
- 「卡车电池只读」角色当初是**整份复制 Gamma**建的（含写权限），本次改为与「全局看板只读」一致的**剥离写权限**建法，并从角色上移除已授予的 11 项写权限（`pb_readonly_role.py` 已重写为幂等的"重建+清理"逻辑，`RESIDUAL_WRITE=0` 自检）。
- 设了 RBAC 角色列表的看板，会对**其他所有角色**隐藏。卡车电池看板原先只允许「卡车电池只读」，导致「全局看板只读」看不到它（404）。已把全局只读角色一并加入该看板的允许列表。

**安全护栏检查（改前已确认，两环境一致）**：未启用嵌入式看板（`EMBEDDED_SUPERSET` 未开、`embedded_dashboards` 表 0 行）、无任何用户挂 Public 角色、看板页面本就会把匿名访问重定向到 `/login/`。因此关闭 Public 继承**不影响正常使用**。

**验证结果（开发环境，两个临时用户端到端实测后已清理）**：

| 操作 | 卡车电池只读 | 全局看板只读 | 匿名 |
|---|---|---|---|
| 看板列表 | 1 个（仅 PB） | 8 个（全部） | — |
| 打开看板 / 图表取数 | 200 | 200 | 重定向登录 |
| 编辑图表 / 另存图表 / 新建看板 / 删除图表 | **全部 403** | **全部 403** | 401 |
| `/api/v1/chart/` 列表 | — | — | **401**（修复前为 200 且泄露 13 个图表） |

**附带收益**：修复前匿名用户可通过 API 列出图表元数据（`/api/v1/chart/` 返回 200、13 条），修复后为 401，堵住了这个信息泄露。

**生产同步**：同一套脚本经跳板执行（Public 权限 92→0、角色移除 11 项写权限、`RESIDUAL_WRITE=0`、看板 31 的 RBAC 已含两个只读角色），重启后 `systemctl is-active=active`、`/health=200`，复查 `PUBLIC_ROLE_LIKE=None` 且 Public 权限为 0（确认重启后未被重新复制）。

**回滚**：配置备份在两台机器的 `superset_config.py.bak_20260728_*`；恢复该文件并重启即可回到原状（Public 角色权限会在启动时由 `PUBLIC_ROLE_LIKE=Gamma` 自动重新填充）。

#### 专题：只读角色里为什么还有 delete 权限（2026-07-28 复审）

**疑问**：在 UI 里看「卡车电池只读」，列表里能看到 delete 字样的权限，看着不像只读。

**审计结论**：角色共 97 条权限，**名字里带 delete 的只有 1 条**（`can_delete_embedded on Dashboard`），而且它是**无效条目**——`DELETE /api/v1/dashboard/<id>/embedded` 的处理函数上写的是 `@permission_name("set_embedded")`，实际校验 `can_set_embedded`（角色里没有）。FAB 只是按 `include_route_methods` 里的方法名把权限行建出来了，握着它删不掉任何东西。

**但审计确实查出了真问题**：上一版脚本靠**权限名黑名单**（`can_write`/`can_add`/`can_delete`/`can_edit`…）过滤 Gamma，而 Superset 的权限命名不守这个规律，于是四类真写权限漏了进来：

| 漏掉的权限 | 实际能干什么 | 为什么名字黑名单没抓住 |
|---|---|---|
| `can_bulk_create on Tag` | `POST /api/v1/tag/bulk_create` 建标签 | 动词叫 bulk_create |
| `can_tag on Chart` / `on Dashboard` | 给图表/看板打标签 | 在代码里 `can_access` 校验，**没有路由** |
| `can_invalidate on CacheRestApi` | `POST /invalidate` 清缓存 | 动词叫 invalidate |
| `can_cache_dashboard_screenshot` | `POST` 触发服务端渲染截图 | 动词里没有写字样 |

**改法（判定依据换掉）**：不再靠名字猜，而是把每条权限映射到**它实际守的路由与 HTTP 动词**（同时读 `method_permission_name` 与 `@permission_name`），再叠三层例外。判定顺序见 `_deploy/ro_role_policy.py` 头部注释。要点：

- `can_read` 守着 `POST /api/v1/chart/data`，**只看动词会误杀**，所以读类名字优先放行；
- 名字明确是写的（`can_add`/`can_edit`/`can_delete`…）**即使当前无路由也拒**——6.0.1 里 `SavedQuery` 那几条是死条目，但升级后可能变活，而且留着就是在误导看列表的人；
- 代码内校验、没有路由的写权限（`can_tag`）只能显式列黑名单。

**本轮移除**（开发 14 条 / 生产 9 条，差异是生产没有那批历史死条目）：

| 类别 | 条目 |
|---|---|
| 真写权限 | `can_bulk_create@Tag`、`can_tag@Chart`、`can_tag@Dashboard`、`can_invalidate@CacheRestApi`、`can_cache_dashboard_screenshot@Dashboard` |
| 无效/死条目 | `can_delete_embedded@Dashboard`、`can_put_chart_customizations@Dashboard`、`can_copy_clipboard@Superset`、`can_file_handler@Superset`、`can_export_as_example@Dashboard`、`can_export_streaming_csv@SQLLab`、`can_store@KV`、`can_get_value@KV` |
| 只读但属安全管理面 | `can_read@security`（能 `GET /roles/`、`/list_groups/`、`/registrations/`）、`can_read@RowLevelSecurity`（能读 RLS 过滤条件） |

**必须保留的 7 条写权限**（删了看板就坏，脚本里每条都写了理由）：

| 权限 | 保留原因 |
|---|---|
| `can_write@DashboardFilterStateRestApi` | 原生筛选器状态，写的是本人临时 key |
| `can_write@ExploreFormDataRestApi` | 点开图表/下钻时暂存表单态 |
| `can_write@DashboardPermalinkRestApi` / `@ExplorePermalinkRestApi` | 生成分享链接 |
| `can_query@Api` | 遗留取数接口，用 POST 只为带查询载荷，语义是读 |
| `can_this_form_post@ResetMyPasswordView`、`resetmypassword@UserDBModelView` | 自助改密码 |

另外 **`can_read@SecurityRestApi` 千万别删**——它守的是 `GET /csrf_token/`，前端所有 POST 都要先拿这个 token。

**顺带发现：Gamma 自己会漂移**。本次开发环境 Gamma 有 106 条、生产 95 条，差的那批是这轮跑 `superset init` 时新增的（含 `can_read@security`）。所以"复制 Gamma"是个会动的基线，这也是要把策略写死在脚本里的原因。

**脚本合并**：`pb_readonly_role.py` + `all_dash_readonly_role.py` 已合并为 **`ro_role_policy.py`**（两个旧脚本已删除，本地和两台服务器都删了——留着被人重跑会把权限带回来）。新脚本是**增量式**的：只按策略增删，不会清掉别处授的权限（如 `fix_selfservice_perms.py` 授的 Info/改密权限）。数据集按**表名**查而不是写死 `database_id`（两环境 id 不同，写死会在一边静默跳过授权）。

**验证（`_test_ro_capabilities.py`，注入登录的测试客户端，15 项）**：

| 必须还能用 | 必须已被拒 |
|---|---|
| 看板页 200、看板接口 200、图表取数未被拦、筛选器状态可写(201)、个人信息页 200、改密页 200 | 打标签 403、清缓存 403、删嵌入配置 403、改图表 403、建看板 403、列角色 302、读 RLS 403，且探针跑完图表名未被改动 |

开发两个角色各 15 项全 PASS；生产「卡车电池只读」15 项全 PASS。生产「全局看板只读」当前**没有用户持有**，端到端探针跑不了（不在生产临时造用户），以权限判定比对为准（`removed=9`、`residual_write=0`，与开发同策略）。

#### 专题：授权改成「用组管人」，不再勾权限（2026-07-28）

**要解决的问题**：人工建角色、在几百个复选框里勾权限，既看不懂也管不住。

**Preset（Superset 商业版）的做法**：把 FAB 权限彻底藏起来，只暴露两层——① 固定的**工作区角色**（Workspace Admin、几档 Creator、Viewer、Dashboard Interactor、Dashboard Viewer），管"能用哪些功能"；② **数据访问角色 DAR**，管"能看哪些数据"，粒度是 全部/数据库/Catalog/Schema/数据集，把人加进去即可。RLS 是独立第三层。**没有勾复选框这回事。**

**本版能落地的等价方案（已实施）**：

1. **角色即代码**：角色定义只写在脚本里（`ro_role_policy.py`），每条例外都带理由，带 `--dry-run` 和"残留写权限=0"自检。UI 里不再改角色。
2. **用组管人**：`Security ▸ List Groups` 里按受众建组，给组挂一次角色，之后**只往组里加人**。

**为什么组是安全的（改之前逐条验过）**：FAB 5.0 的 `get_user_roles()` 返回 `user.roles + [r for g in user.groups for r in g.roles]`，而所有鉴权路径都走它——`_has_view_access`（`has_access` 的实现）、`_get_user_permission_view_menus`（数据集/菜单过滤）、看板 RBAC（`security/manager.py` 571、2484 行）、RLS（2574 行）。所以"组带来的角色"和"直接授予的角色"完全等价。UI 侧也确认可用：`/groups/list/`、`/groups/add`、`/groups/edit/<id>` 均 200，表单字段就是 `name / label / description / roles / users`，Admin 已持有全部组权限。

**组目录**（`groups_setup.py`，每个角色写成别名列表，因为两环境角色名不一致，如「Dify监控」vs「Dify监控看板」；某角色在本环境不存在则整组跳过）：

| 组 | 挂的角色 | 开发成员 | 生产成员 |
|---|---|---|---|
| 卡车电池观众 | 卡车电池只读 | 3 | 1 |
| 全部看板观众 | 全局看板只读 | 1 | 0 |
| 智能客服观众 | Gamma-Readonly + 智能客服 + Dify监控 | 3 | 3 |
| Dify监控观众 | Gamma-Readonly + Dify监控 | 1 | 1 |
| VOC观众 | Gamma-Readonly + VOC看板 | 2 | 1 |
| 电池包数据观众 | Gamma-Readonly + 电池包数据 | 该角色开发没有，跳过 | 3 |
| PV预测观众 | Gamma-Readonly + PV预测 | 0 | 1 |
| 看板制作者 | Gamma（**可编辑，不是只读**） | 5 | 6 |

**迁移方式（构造上不改任何人的权限）**：用户只在"当前直授角色集合 **完全等于** 某个组的角色集合"时才被移入该组，移入后再摘掉那些直授角色。脚本在动手前先给每个用户拍两份快照——**有效角色名**和**能看见的看板 id 集合**（真发 `/api/v1/dashboard/` 请求取），提交后重新比对，一旦有人对不上就**自动把直授角色补回去**并以失败退出。

结果：开发 7 组 / 迁 15 人 / 摘 24 条直授，生产 8 组 / 迁 16 人 / 摘 28 条直授，**两边都无漂移**。Admin 用户一律不动。

**端到端验证**：`_test_ro_capabilities.py` 改成按 `get_user_roles()` 找人（原来按直授角色找，迁完就找不到人了）。两环境跑出来都是 `direct=[] groups=['卡车电池观众']` 且 16 项检查全 PASS——**用户身上一条直授角色都没有，权限全部来自组，真实请求链路照常工作**。

**以后怎么用**：

- 给人开权限：`Security ▸ List Groups` → 打开对应组 → `users` 里加人。**不要**去 List Roles 勾权限。
- 新受众：先想清楚要哪些角色，加进 `groups_setup.py` 的 `GROUPS` 再跑一次（幂等）。
- 改角色内容（能干什么/能看哪些数据）：改 `ro_role_policy.py` 这类脚本，别在 UI 改。

> **2026-07-28 深夜更新**：上面的"薄数据角色"路线已被下一个专题的**受众角色模型**取代，`ro_role_policy.py` 与 `groups_setup.py` 均已退役（组还在，组里挂的角色换了）。本节保留作为演进记录。

#### 专题：授权模型重构——只读基线 + 看板受众角色（2026-07-28，开发+生产均已落地）

**要解决的问题**：上一轮"Gamma-Readonly 当公共底座 + 每看板一个薄数据角色"的思路方向对，但落地后审计发现三类病：① 手工建的 Gamma-Readonly 既缺关键能力（`can_dashboard@Superset` 没有——**持有者根本打不开看板页**，还缺中文包/CSV/下钻/分享），又混着漏网写权限；② 各只读角色权限数 73/88/94 互不一致，全靠手勾，必然漂移；③ 数据授权（datasource_access）散在各角色里，观众其实能绕过看板用 Explore 直接查数据集。

**新模型（官方推荐的形态，三层各司其职）**：

| 层 | 是什么 | 数量 |
|---|---|---|
| `只读基线` | 唯一携带权限的只读角色，由脚本从 Gamma 按策略生成（能力全、写权限零、**数据授权零**） | 1 个 |
| `看板·<名>` | 每看板一个**零权限**受众角色，唯一用途是挂进该看板的 RBAC 列表（曾配套一个挂在所有看板上的 `看板·全部`，**2026-07-29 已按需求裁撤**，见日志 17） | 每看板 1 个 |
| 组 | `XX观众` = 只读基线 + 若干 `看板·X`；给人开权限=往组加人 | 每受众 1 个 |

**原理（6.0.1 实测）**：开 `DASHBOARD_RBAC` 后，已发布看板一旦挂了角色，列表、打开、图表取数、原生筛选、下钻全部**只看角色**，不再要求 datasource_access（`DashboardAccessFilter` 会对有角色的看板关闭数据集回退路径；取数走 `raise_for_access` 的看板豁免，前端请求里带 `dashboardId`）。所以观众可以**一条数据授权都没有**：能看的=被授权看板呈现的，脱离看板直连 `/api/v1/chart/data` 一律 403（两环境实测，回收前 200 → 回收后 403）。

**唯一真源 `authz_model.py`**，四个子命令按序执行，全部幂等、支持 `--dry-run`：

1. `baseline`：Gamma-Readonly 改名`只读基线`并按策略修正（开发 +21/-11=83 条、生产 +18/-10=77 条，残留写权限=0），Gamma-Readonly+ 持有人并入后删除。
2. `migrate`：逐看板建 `看板·<名>` 挂进 RBAC，并把受众角色发给**当下真实看得见这块看板的**组/个人（受众按可见性快照推导，不靠人工声明）；每块看板提交后重测全员可见集合，有漂移即自动回退该看板并中止。
3. `revoke`：把旧数据角色的数据授权全部剥掉（开发 6 角色 14 条、生产 7 角色 18 条含孤儿 SOH异常检测），漂移自检带自动恢复。
4. `retire`：删除已清空的旧数据角色；对只靠胖角色（卡车电池只读/全局看板只读）拿能力的组，删除前自动换入`只读基线`。

**验证**：`authz_probe.py` 以每组代表+直授受众用户真实走 HTTP——看板列表/打开/取数（带 `dashboardId`）/分享/筛选器状态/下钻/中文包全 PASS，建看板 403，脱离看板取数 403。仅剩的红项都与权限无关：开发看板 9 的 VOC 库 `127.0.0.1:3306` 本来就没起（Admin 同样报错）、生产看板 17 图 200 是 StarRocks 内存限制、jackey.que/刘世君 能建看板是因为持有 Gamma（制作人）。

**保留的特例**（都有意为之）：`newapi` 角色未动（对接账号，刘世君继续持有，他因此还能脱离看板取数）；jackey.que（两环境）与刘世君（生产）的 `看板·X` 是直授不入组，因为他们的可见组合独一份；`AUTH_USER_REGISTRATION_ROLE` 两环境已改为`只读基线`并重启（新 SSO 用户默认零数据、零看板，进组才看得见东西）。生产改动前有完整授权快照 `/mnt/data/superset/backups/authz_snapshot_20260728_225427.json`，配置备份 `superset_config.py.bak.authz`。

> 日常授权（给某用户开某看板的只读/编辑权限）的完整操作步骤已单独整理成
> 《Superset看板授权操作指南.md》（同目录），给管理员照着做用；本节以下是原理与变更记录。

**日常操作（新看板上线三步）**：

1. 建好看板、发布；
2. 跑 `authz_model.py migrate`（只会为新看板补 `看板·<名>` 并挂进看板 RBAC，已迁移的看板幂等跳过）；
3. `Security ▸ List Groups` 把 `看板·<名>` 挂到目标组（或建新组=只读基线+该角色），以后只往组里加人。

**别做的事**：不要在 UI 给角色勾权限；不要给观众发 datasource/schema/database 授权（会重新打开 Explore 直查数据的口子）；不要手工建"数据角色"。

**编辑授权（给某人开通"改某看板全部图表"，2026-07-29，当天即页面化）**：编辑一张图在 6.0.1 里需要三要素，缺一不可：

1. **能力**：Gamma（`can_write@Chart` 等）；
2. **数据**：图表底层数据集的 `datasource_access`。这一条**没有商量余地**——6.0.1 的 `ChartFilter` 只按数据集授权过滤图表列表/详情 API，Owner 身份完全不看，缺了它图表 API 直接 404（见坑 25）；
3. **Owner 判定通过**：非 Admin 的 `can_write` 只能保存"自己拥有"的对象。

**现行做法（页面化，推荐）**：Owner 是唯一没法用组表达的要素，因此在 `CustomSsoSecurityManager` 里重写了 `raise_for_ownership()`（6.0.1 所有 Owner 判定的唯一收口，`is_owner()` 也走它）——原判定不通过时，若用户持有的某个 `编辑·X` 角色**恰好挂在目标看板的 RBAC 上**，则对这块看板及其全部图表视同 Owner。映射走"角色挂在看板 RBAC"而非角色名匹配看板名，看板改名不受影响；判定内部任何异常一律回落默认拒绝。补丁：`patch_editor_ownership.py`（幂等、带备份 `superset_config.py.bak.editorown`、语法自检失败自动还原，**需重启**），两环境已应用。

于是授权分两层：

- **每看板一次性**（跑 `editor_group_setup.py <看板id>`）：建 `编辑·<看板名>` 角色（含全部相关数据集的 `datasource_access`）→ 挂进看板 RBAC → 建组「<看板名>编辑」= Gamma + 该角色；
- **日常授权 = 纯页面**：`Security ▸ List Groups` 把人加进「XX编辑」组，立即可看可编辑该看板全部图表；移出组即收回。不用挂 Owner，不用跑脚本。

验证（开发，`_editor_probe.py`）：零角色、零 Owner 的探针用户入组后 GET/PUT 图表均 200；同一人改**其他看板**的图 404（数据集授权不覆盖，天然限界）；观众 PUT 403。郭特已从直授角色迁入「VOC项目看板编辑」组并复验可编辑。

`grant_dashboard_editor.py`（直授+挂 Owner 的旧路径）保留可用，适合"临时给一个人、不想建组"的场景；注意它会把直授角色加回去，与组模式混用时留意。两种方式下编辑者都能在 Explore 里对这些数据集写任意查询，只给信得过的人开。

#### 专题：分享链接（permalink）点了报 500（2026-07-28）

**现象**：看板「分享 ▸ 复制永久链接」500，Explore 的分享链接也一样，**admin 也复现**——所以不是权限问题。

**根因**：`key_value` 表里那两条 shared salt（`DASHBOARD_PERMALINK_SALT` / `EXPLORE_PERMALINK_SALT`）存的是 **base64 编码的 JSON**，而 6.0.1 用纯 `JsonKeyValueCodec` 去解，抛 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`。是旧版本写入、升级后编解码不一致的遗留。调用链：`CreateDashboardPermalinkCommand.run()` → `base.salt` → `get_permalink_salt()` → `KeyValueDAO.get_value()`。

**修法**：`fix_permalink_salt.py` 把这两行**就地重编码**（base64 解出来按纯 JSON 存回），salt 值不变。没选"删行让它重生成"——删了 salt 会变（旧链接仍能解析，因为 GET 是按 key 查表，但没必要动）。已解得开的行会 `SKIP`。

**验证**：两环境 readback 正常，`POST /api/v1/dashboard/<id>/permalink` 与 `POST /api/v1/explore/permalink` 都返回 **201**，并且以只读用户身份生成链接后 `GET /superset/dashboard/p/<key>/` 返回 302（正常跳转）。已并入 `_test_ro_capabilities.py` 做回归。

> 观察：修完发现两环境对同一输入生成的 key 完全相同，说明两边 salt 值一样（生产元数据库大概源自开发）。permalink key 是 `uuid3(salt, (user_id, state))` 决定性生成的，所以知道开发链接就能推出生产链接——但对方仍需有查看权限才能打开，影响有限。要彻底隔离可以只在生产轮换 salt（旧链接不受影响，因为解析是按 key 查表）。**未做。**

#### 专题：点 Info 报「Access is Denied」+ 无法自己改密码（2026-07-28）

**现象**：用户点右上角 Info 被弹回登录页并提示 `Access is Denied`；也找不到任何修改自己密码的入口。

**这是两个独立的原因，都不是 Public 角色改动造成的**（起初怀疑过，实测排除：`admin` 同样进不去 Info，说明改 Public 之前就坏了）。

**原因一：导航栏的 Info 指向 `/user_info/`，它要的权限是 `can_read@user`，而这条权限条目从未被创建。**

★ **最容易踩的坑：Superset 6 有两个"用户信息"页面，长得像但路由和权限完全不同。**

| 页面 | 路由 | 视图 | 需要的权限 |
|---|---|---|---|
| **导航栏 Settings ▸ Info（用户实际点的这个）** | `/user_info/` | `UserInfoView.list`（`class_permission_name="user"`） | **`can_read@user`** |
| FAB 旧版个人资料页 | `/users/userinfo/` | `UserOAuthModelView.userinfo` | `can_userinfo@UserOAuthModelView` |

菜单地址在 `superset/views/base.py`：`"user_info_url": "/user_info/"`。第一次排查时我按 `userinfo` 关键字过滤路由，**`/user_info/` 带下划线所以没被匹配到**，结果只修了 FAB 那个页面（`/users/userinfo/` 返回 200 了），用户点导航栏 Info 依旧报错。**排查这类问题一定要先确认按钮真正请求的 URL**（看 `user_info_url` 或浏览器 Network），不要凭页面名猜。

两个权限条目都是"视图已注册、权限行从未创建"，因此**所有人（含 Admin）判定无权**。实测生产 `superset init` 前 Admin 也没有 `can_read@user`，即生产管理员同样打不开 Info。

**为什么权限行会缺失**：`AUTH_TYPE = AUTH_OAUTH` 时 FAB 用 `UserOAuthModelView` 而非 `UserDBModelView`，而库里的授权全记在 `UserDBModelView` 名下（实例早期是 AUTH_DB 留下的）；加上 Superset 6 新增的 `UserInfoView`，这些新视图的权限行只有跑 `superset init` 才会补建。

失败表现：`has_access` 拒绝后闪一条 `Access is Denied` 并重定向；Superset 把 Flask flash 渲染成前端深色 toast，所以用户看到的是一个提示框而不是错误页。

**原因二：FAB 只在 AUTH_DB 下注册改密码视图。** 源码 `flask_appbuilder/security/manager.py` 的 `register_views()` 里，`resetmypasswordview()`（自助改密）和 `resetpasswordview()`（管理员重置他人）都写在 `if self.auth_type == AUTH_DB:` 分支内。OAUTH 下这两个路由根本不存在（`/resetmypassword/form` → 404），而 `UserOAuthModelView` 的编辑表单也没有密码字段——也就是说**全站没有任何图形界面能改本地密码，只能用 CLI**。库里那些 `ResetMyPasswordView.can_this_form_get` 权限是 AUTH_DB 时代的遗留，视图没注册所以一直是空转。

**修复三步**：
1. `superset init`（官方权限同步）：创建 `UserOAuthModelView` 的权限条目，并按 Superset 自己的 `ACCESSIBLE_PERMS = {can_userinfo, resetmypassword, can_recent_activity}` 归类授予内置角色。开发实测只新增权限、**不删任何权限**，Public 保持 0 项（`PUBLIC_ROLE_LIKE=None` 时 `sync_role_definitions` 会跳过它），自定义角色不受影响。改前后用 `_snap_perms.py` + `_diff_perms.py` 快照对比确认：Admin 238→251、Alpha 128→131、Gamma 103→106。
2. `fix_selfservice_perms.py`：`superset init` **只授予内置角色**（Admin/Alpha/Gamma），自定义角色一个都不管，所以挂自定义角色的用户仍然报错——这正是「张华」（只有「卡车电池只读」）的情况。该脚本给除 Public 外所有角色补 `can_read@user`（导航栏 Info，**关键的那条**）、`can_userinfo@UserOAuthModelView`、`can_read@CurrentUserRestApi`、`can_recent_activity@Log`；权限行不存在时会自己 `add_permission_view_menu` 创建，因此不依赖 `superset init` 也能单独用。开发改 9 个角色、生产改 11 个。**Public 必须跳过**，否则又把 `is_item_public` 旁路打开了。
3. `enable_password_views.py`：在 `CustomSsoSecurityManager.register_views()` 里 `super()` 之后补注册 `resetmypasswordview()` 和 `resetpasswordview()`，把 FAB 在 OAUTH 下跳过的两个页面加回来（双登录既然保留本地账号就得有改密入口）。**需重启**。
4. `head_custom_extra.html` 追加一段 JS，在导航栏 Settings ▸ User 分组里补「修改密码」入口：克隆 Info 那个菜单项、把 `href` 改成 `/resetmypassword/form` 并改文案（克隆是为了直接继承 antd 样式），用 `MutationObserver` 应对 React 重渲染，带 `busy` 标志防止自触发循环。**需重启**（Jinja 会缓存模板，改完不重启页面里还是旧内容——实测旧 CSS 在、新 JS 不在）。

**顺带修掉一个 Public 改动引入的真实回归**：`can_read@CurrentUserRestApi`（导航栏调的 `/api/v1/me/`）原先靠 `PUBLIC_ROLE_LIKE=Gamma` 送达所有人，Public 清空后，挂 `Gamma-Readonly`/`VOC看板`/`Dify监控` 的 **6 个真实用户**该接口变 403。已在第 2 步显式授权。教训：**清 Public 权限后要跑一遍全用户审计**（`_audit_users.py`），因为过去很多自定义角色是"薄角色"，隐性依赖 Public 提供的 Gamma 基线。

**验证（开发环境用真实账号「张华」＝只有「卡车电池只读」，另用临时用户 `ro2_probe`/`selftest_probe` 实测后已删除）**：

| 项 | 修复前 | 修复后 |
|---|---|---|
| **`/user_info/`（导航栏 Info）** | 302 → Access is Denied | **200** |
| `/users/userinfo/`（FAB 页） | 302 → Access is Denied | **200** |
| `/api/v1/me/` | 403 | **200** |
| `/resetmypassword/form` | 404 | **200**（含密码字段） |
| 提交改密 → 新密码登录 | 不可能 | **成功**，且旧密码失效 |
| 看板列表（张华） | — | 仅「卡车电池设备分析」1 个（RBAC 仍生效） |
| 全用户审计 | 6 个真实用户缺权限 | **全部 OK**（仅遗留空角色账号 `test` 例外，与本次无关） |

**生产同步（2026-07-28 已全部完成）**：
- 权限部分**无需重启**（FAB 每请求现查库）：`superset init` 纯新增（Admin 224→237、Alpha 114→117、Gamma 92→95，与开发一致，无删除），`fix_selfservice_perms.py` 补了 11 个角色。
- 改密码视图 + 入口 JS **需重启**：配置补丁（备份 `superset_config.py.bak.20260728154911`）、模板 sha256 与本地一致、属主 `cloudapp:cloudapp`/644，重启后 `is-active=active`、`/health=200`。
- 重启后生产复验：`/resetmypassword/form` 与 `/resetpassword/form` 路由已注册、Jinja 解析到 `/mnt/data/superset/custom_templates/head_custom_extra.html` 且同时含改密入口与下拉宽度 CSS、「张华」`can_read@user` 等逐条判定 OK。

**生产验证的坑：不能用明文 HTTP 在本机跑登录脚本。** 生产 `SESSION_COOKIE_SECURE=True`，`requests` 不会把 Secure cookie 回发到 `http://127.0.0.1:8088`，于是会话拿不住、表现为"密码错误"（`ME|401`），但 `sm.auth_user_db()` 明明返回 OK。**对策**：生产验权限走 app context 内的 `sm.has_access(perm, view)` 直接判定（脚本 `_verify_prod_zh.py`），不要依赖 HTTP 登录。

**注意事项**：
- **SSO 用户改这里的密码没意义**：`/resetmypassword/form` 改的是 Superset 本地密码哈希，Casdoor 登录不受影响。SSO 用户要改密码请去 Casdoor。
- **入口靠 JS 注入**：Superset 6 的用户下拉是 React 硬编码的（只有 Info / Logout）；前端 bundle 里只有 "Reset my password" 这个文案、没有对应路由，补注册视图不会自动长出链接。已在 `head_custom_extra.html` 用 JS 补上（见上文第 4 步），两环境均已生效；直接访问 `/resetmypassword/form` 同样可用。
- 管理员重置他人密码走 `/resetpassword/form?pk=<用户id>`（仅 Admin 有权），或用 CLI `superset fab reset-password`。

**回滚**：`superset_config.py.bak.20260728151918`（开发）；恢复并重启即可。权限授予如需回退，按 `fix_selfservice_perms.py` 的 `WANTED` 列表反向删除即可。

#### 专题：切换语言一直不生效 + 中文设为默认（2026-07-28）

**现象**：右上角语言切换器点了没反应，界面永远是英文。

**根因：装的 Superset 包里只有翻译源文件 `.po`，没有任何编译产物。** 两层翻译都因此失效：

| 层 | 需要的文件 | 实际情况 | 后果 |
|---|---|---|---|
| 前端 SPA（绝大部分界面文字） | `translations/{locale}/LC_MESSAGES/messages.json`（Jed 格式） | **不存在** | `/superset/language_pack/zh/` 返回 404，`get_language_pack()` 异常后回落 `empty_language_pack.json` |
| 后端 Python/Jinja（FAB 页面、报错文案） | `translations/{locale}/LC_MESSAGES/messages.mo` | **不存在** | gettext 找不到目录，直接返回 msgid（英文） |

安装目录里 21 个语种各有一份 `messages.po`（zh 338 KB）却 0 个 `.mo`、0 个 `messages.json`。所以切换器本身是好的（`/lang/zh` 确实写入了 `session["locale"]`），只是没有任何语料可用。

**修复**：
1. **生成前端语言包**：在构建机（`gt@192.168.56.101:/opt/superset-build`）用 Superset 自带的官方方式生成，**不要手写**：
   ```bash
   po2json --domain superset --format jed1.x --fuzzy <file>.po <file>.json
   ```
   （即 `superset-frontend/scripts/po2json.sh` 的核心命令，脚本 `_deploy/_gen_lang_packs.sh` 对 21 个语种批量执行。）先核对构建机与运行环境的 `.po` **sha256 一致**、版本同为 6.0.1，确保 msgid 对得上。zh 产出 4036 条。
2. **编译后端目录**：`pybabel compile -d <translations> -D messages -f`（`-f` 保留 fuzzy，与前端 `--fuzzy` 口径一致）。upstream 有约 388 条 printf 占位符不平衡的条目会报 error 并被跳过，**不影响目录生成**（zh 得到 3656 条可用翻译）。脚本 `_deploy/_install_lang.sh`（自动从 venv 推导 translations 路径、按原 `.po` 的属主 `chown`、`chmod 644`）。
3. **中文设为默认**：`set_default_locale_zh.py` 把 `BABEL_DEFAULT_LOCALE` 从 `'en'` 改成 `'zh'`（原配置值是 `'en'` 但注释写着"默认语言为中文"，之前想改没改成）。FAB 的 `get_locale()` 优先用 `session["locale"]`、否则用这个值；SPA 的 bootstrap `locale` 由 `get_locale()` 推导，所以改这一个值就够，且**不影响用户自己切换**。**需重启**。

**为什么必须用官方 po2json 而不是手搓 JSON**：Jed 的 `locale_data` 取值格式很容易搞错（`["译文"]` 还是 `[null,"译文"]`），格式错了界面会渲染成**空白**而不是回落英文，比不翻译更糟。用官方工具直接规避。

**关于 384 条空译文（已确认安全）**：zh 语料里有 384 条 `msgstr ""`。查 Jed 源码 `dcnpgettext` 确认它显式处理了这种情况——
```js
res = val_list[ val_idx ];
// This includes empty strings on purpose
if ( ! res ) { res = [ singular_key, plural_key ]; return res[...]; }
```
空字符串会**回落到英文原文**，不会出现空白标签，因此无需过滤，官方产物可直接使用。

**验证（开发环境用真实账号实测；关键点：SPA 是运行时用 JS 翻译的，服务端 HTML 里本来就没有中文，别用"抓页面搜中文"判断前端是否生效）**：

| 场景 | bootstrap locale | 语言包接口 | 后端渲染页面 |
|---|---|---|---|
| 默认（session 无 locale） | **zh** | — | 中文（看板/图表/密码） |
| `/lang/en` | en | 200，4036 条 | 英文 |
| `/lang/ja` | ja | 200，`Dashboards=['ダッシュボード']` | 日文 |
| `/lang/zh` | zh | 200，`Dashboards=['看板']` | 中文 |

**生产同步**：`langpacks.tgz`（1.8 MB）经跳板传输（sha256 一致）→ `_install_lang.sh` 安装（json=21、mo=21，属主 `cloudapp:cloudapp`、644）→ `set_default_locale_zh.py` 改配置（备份 `superset_config.py.bak.20260728160648`）→ 重启（`is-active=active`、`/health=200`）→ 复验 `BABEL_DEFAULT_LOCALE=zh`、`get_locale()=zh`、`gettext('Dashboards')=看板`、zh/ja 包均有译文（脚本 `_verify_prod_lang.py`）。

**注意**：语言包和 `.mo` 是写进 **site-packages 内**的，`pip install/upgrade superset` 会覆盖丢失，**升级后需重跑第 1–2 步**。构建机 `/opt/superset-build/superset/translations/` 下已留有生成好的 21 份 json，可直接打包复用；`langpacks.tgz` 未入库，需要时按 `_gen_lang_packs.sh` 重新生成即可。

**已知小瑕疵**：`views/base.py` 里导航栏数据用的是 `session.get("locale", "en")`（硬编码 en 兜底，不读 `BABEL_DEFAULT_LOCALE`），所以用户**没主动选过语言时**，语言切换器高亮的仍是 English，而界面已经是中文；点一次「简体中文」写入 session 后就一致了。纯显示问题，不影响实际语言。

**追加坑（改完默认语言后老用户仍是英文，2026-07-28）**：上面全部做完、生产也重启验证过，用户登录进去**还是美国英语**。原因在 FAB 的 `babel/manager.py::get_locale()`：

```python
locale = session.get("locale")
if locale:
    return locale
session["locale"] = self.babel_default_locale   # ← 把默认值“落盘”进 session
```

它读不到 `session["locale"]` 时会**把当时的默认语言写进 session**。也就是说，凡是在改默认语言**之前**建立过的会话，里面都烙着 `locale='en'`；而 session 优先级高于 `BABEL_DEFAULT_LOCALE`，这些老用户会**永远**看到英文，除非自己点一次语言或会话销毁。改配置对存量会话完全无效——这就是"开发是中文、生产还是英文"的真实原因（开发那边是新会话）。

**修法**：`heal_stale_locale.py` 在 `FLASK_APP_MUTATOR` 里挂一个 `before_request` 钩子做**一次性迁移**——会话上的版本标记 `_locale_policy` 不等于当前值时，把 `locale` 重置为当前默认语言并打标记；之后用户自己选的语言不会被覆盖（那时会话已带当前标记）。只在 `session["locale"]` 已存在时才动手，避免给全新访客白建会话。

- 该脚本**自动适配两种写法**：开发是 `def FLASK_APP_MUTATOR(app)`（缩进 4），生产是 `class CustomFlaskAppMutator.__call__`（缩进 8），按 `])` 的实际缩进插入，别硬编码。
- 验证脚本 `_test_locale_heal.py` 用 Flask 测试客户端**预置**会话内容跑 5 个用例：`locale=en/ja` 无标记 → 重置为 zh；带当前标记的 en/ja → **原样保留**；空会话 → 不凭空写 locale。开发与生产各自跑通全 PASS 后才重启。
- **需重启**。用户侧只需刷新页面（必要时 Ctrl+F5），下一个请求就会被自动纠正，无需重新登录。
- 顺带确认：生产 `SESSION_TYPE="redis"` + `Session(app)`，是**服务端会话**；另一条路是直接清 Redis 里的 session key，但那会强制所有人重新登录，不如钩子温和。生产还有 `SESSION_COOKIE_SECURE = True`，所以本机 http 探针拿不到会话，验证要走 app context（见坑位表）。

### 历史变更
- 2026-07-27 生产发布（两看板首次上线生产）+ 数据对象命名统一：见《卡车电池设备分析-数据对象清单.md》五节、《全球AI客服·运营分析_指标计算口径说明.md》两条 2026-07-27 附录。
- 2026-07-20 客服口径统一 + 生产同步：见《全球AI客服·运营分析_指标计算口径说明.md》2026-07-20 附录。
- SSO + 本地双登录、Casdoor 配置、Redis 服务端会话、权限下拉宽度修复：见 `_deploy/superset_config_dev_sso.py`、`login_dual.html`、`head_custom_extra.html`。

---

## 七、当前状态与待决事项（截至 2026-07-28）

### 两环境现状（开发与生产已对齐）

| 项 | 开发（192.168.41.122） | 生产（10.100.19.1） |
|---|---|---|
| 卡车电池设备分析 | 看板 id **32**，38 图，5 Tab | 看板 id **31**，38 图，5 Tab |
| 全球AI客服·运营分析 | 看板 id **15**，50 图 | 看板 id **29**，51 图（多 1 张同名历史图） |
| 界面语言 | 默认 `zh`，21 语种包已装，切换正常 | 同左 |
| 会话 | Redis 服务端会话 | Redis 服务端会话 + `SESSION_COOKIE_SECURE=True` |
| 登录 | SSO（Casdoor `agi-casdoor.bluetti.com`）+ 本地账号双登录 | 同左 |
| Public 角色 | 已清空，`PUBLIC_ROLE_LIKE=None` | 同左 |
| 只读角色 | 仅「只读基线」1 个带权限（83 条，零数据授权，`authz_model.py` 生成）；旧数据角色已全部退役 | 同左（77 条） |
| 看板授权 | 每看板挂零权限受众角色「看板·X」，观众取数走 RBAC 豁免，脱离看板直查 403（「看板·全部」已裁撤） | 同左 |
| 授权方式 | **用组管人**：组=只读基线+若干「看板·X」，开权限只往组加人 | 同左 |
| 新用户默认角色 | `AUTH_USER_REGISTRATION_ROLE="只读基线"`（已重启生效） | 同左（配置备份 `superset_config.py.bak.authz`） |
| 分享链接 | 已修（salt 重编码） | 已修 |
| 自定义模板 | `custom_templates/head_custom_extra.html`（下拉加宽 + 改密码入口 + 旧浏览器 Set polyfill） | 同左 |
| 编辑授权 | 页面化：`raise_for_ownership` 已重写（配置补丁），组「<看板名>编辑」加人即可编辑；已建「VOC项目看板编辑」 | 补丁已应用，编辑组按需再建（`editor_group_setup.py`） |
| Tab 说明条 | **未启用**（试过后撤回，见日志 11） | **未启用**（从未改过） |

数据层（StarRocks `ads_tb_*`）两环境共用同一集群，改一边等于改两边。

### 待决 / 未做

1. **PB 的 Tab 顺序**：实际是「设备分布」在第一位、「运营总览」第二，打开看板默认落在地图页。是否调整未定。
2. ~~用户 `guote`（郭特）的删除~~ **已解决（2026-07-29）**：用 `_user_reassign.py` 把名下引用全部处理（key_value 2 条移交 admin、组成员关系删除、567 条日志 user_id 置 NULL 保留审计）后删除，残余引用=0。该脚本按 `information_schema` 反查所有指向 `ab_user` 的外键，谁都能这么删；支持按用户 id 指定（规避中文用户名过 ssh 乱码）。生产无此账号，无需操作。
3. **提过但尚未执行的美化项**：统一色板与分类固定配色（`label_colors`）、数字格式统一（千分位/小数位/单位后缀）、明细表条件着色（如 SOH<90 标红）、看板级自定义 CSS。这几项都能像已做的那样脚本化批量应用到两环境。
4. ~~`Gamma-Readonly` / `Gamma-Readonly+` 漏网写权限~~ **已解决**：`authz_model.py baseline` 改名`只读基线`并清零写权限（残留=0），`Gamma-Readonly+` 已并入删除。见第六节授权模型重构专题。
5. ~~两角色疑似重复~~ **已解决**：同上，已合并删除。
6. ~~新 SSO 用户默认拿 Gamma~~ **已解决**：两环境 `AUTH_USER_REGISTRATION_ROLE` 已改为`只读基线`并重启。新用户默认零数据、零看板，进组才看得见东西。
7. **jackey.que（两环境）与生产 `刘世君` 的「看板·X」是直授不入组**（可见组合独一份，属有意保留）：jackey.que = Gamma + 只读基线 + 直授受众角色；刘世君 = Gamma + newapi + 看板·newapi看板。`newapi` 角色未动（对接账号），他因此仍可脱离看板取数。要收紧再议。
8. ~~`苗艺萌` 两环境权限不一致~~ **已解决（2026-07-29）**：确认她只看「卡车电池设备分析」，两环境均已移入「卡车电池观众」组（开发从"看全部"收敛、生产从看板制作者移出），见日志 17。
9. ~~生产「全部看板观众」组没有成员~~ **已随「看板·全部」裁撤一并删除（两环境，日志 17）**。生产 `yuanqing`/`huml` 只有基线、看不到任何看板（迁移前就如此，零漂移保留）；若 huml 本该看 pv预测，把看板发布后将「看板·pv预测」挂给对应组即可。
10. **permalink 的 salt 两环境相同**，可选在生产轮换以隔离（详见第六节 permalink 专题末尾的观察）。**未做。**
11. **开发看板 9（VOC项目看板）的数据源 `127.0.0.1:3306` 连不上**（Admin 也报 MySQL 2003），数据层问题，与授权无关。~~生产看板 17 图 200 触发 StarRocks 内存上限~~ **已解决（2026-07-29）**：根因是数据集 54 的裸查（无时间筛选 → 无 `pt` 分区裁剪 → 对 71 亿行全表聚合），真实看板因时间筛选必填从未受影响；已给数据集 SQL 加"无时间筛选返回空"护栏（`fix_ds54_guard.py`，SQL 备份 `backups/ds54_sql_20260729_081548.txt`），验证：裸查 0.2s 返回空，看板正常路径 1.4s 返回 9418 行。**残余风险**：手工构造"只带时间、不带设备"的查询仍可能很重（一周约 4.1 亿行），要彻底兜底需在 StarRocks 侧配查询资源组/单查询内存上限。
12. **未发布的看板（开发 2/8/18/37，生产 9/14/20/21/24）已挂受众角色但无人可见**，发布后需把对应「看板·X」挂给目标组才会亮相。

> 注：Superset 主干文档里的 Subjects / `ENABLE_VIEWERS`（按看板直接指派可见人或组，连角色都不用建）在**当前 6.0.1 尚不可用**（无 `superset/subjects` 模块、配置里无该开关），要等升级。升级后可以把「XX观众」这类组直接指派到看板上，连薄数据角色都能省掉。
