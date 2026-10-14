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

**JumpServer 通道**：`jumpserver.poweroak.ltd:2222`，账号密码不入库，运行脚本前设置环境变量 `JUMP_USER` / `JUMP_PASSWORD`；登录后菜单 `/Flink` → 选 `1`（StarRocks-01）→ 再 `ssh 10.100.19.1` 到生产。本目录 `_deploy/jump_run.py`、`jump_put_fast.py` 已把这套跳板流程封装好，正常情况下不用手动敲跳板。

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
9. **`chartsInScope` 跨环境不可信**：它是缓存字段，看板导入时不会被重映射（`scope.excluded` 会），生产里存的可能还是开发的图表 id。判断筛选器作用域要用 `scope.excluded` 推导（全部图表 − excluded）。**库里的漂移是无害的**：`DashboardContainer.tsx` 每次加载看板都会用 `getChartIdsInFilterScope(scope, ...)` 重算并 `setInScopeStatusOfFilters` 覆盖 redux（运行时 `activeAllDashboardFilters.ts` 虽然优先读 `chartsInScope`，读到的已是重算值），所以巡检出漂移不必逐个"修"——用 `_check_filter_scope.py` 看一眼即可，两环境现存 20+ 处都是历史陈旧缓存。详见第六节时间筛选器专题。
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

26. **"筛选器不生效"先分清是没接上还是被行数上限吃掉了**：报"这张图不受左侧时间范围限制"时有两个完全不同的成因，症状一样。① **作用域**：同一看板可能有多个 `filter_time` 筛选器，主筛选器的 `scope.excluded` 把目标图表排除了，实际管它的是另一个同名带后缀的筛选器（本次 `时间范围` vs `时间范围(数据详情)`）。② **行数上限截断**：明细表 `ORDER BY 时间 DESC` + `row_limit`，若数据密度高，取到的行只覆盖所选范围**末尾一小段**——本次每分钟 260~370 行、上限 5000，等于只看得到最新约 13 分钟，无论选多宽的范围显示的都是"今天"，看起来就像筛选被忽略。**判定方法**：直接 `POST /api/v1/chart/data` 带 `result_type=query` 对比带/不带 `time_range` 生成的 WHERE（能证明机制通不通），再看返回数据的 `min/max` 时间跨度（能证明是不是被上限截断）。
    另外记牢两条机制：**看板传来的 `time_range` 会覆盖图表自带的 `TEMPORAL_RANGE` 值**（`query_context_factory._apply_filters` 遍历所有 `TEMPORAL_RANGE` 过滤器改写 `val`），所以图表里写死一个保守范围是安全的，它只在 Explore 单独打开时兜底，不会挡住看板筛选；**导出 CSV/Excel 走的是同一份合并后的 formData**（`dashboard/.../Chart.jsx` 的 `exportCSV` 用 `getFormDataWithExtraFilters` 的结果），所以下载天然受左侧筛选约束，"下载到全部数据"必定是筛选本身没生效，别去改导出链路。

27. **筛选器"必填"（`enableEmptyFilter`）是看板级连坐，单独开必填等于锁死全看板**：`FilterBar/utils.ts` 的 `checkIsApplyDisabled` 只要发现**任意一个**筛选器 `validateStatus==='error'`（必填且无值）就禁用整条筛选栏的「应用」按钮。给"数据详情"专用的设备号筛选器只开必填，用户不选设备就没法应用其它 Tab 的时间/型号筛选。**必填必须和一个非空的 `defaultDataMask` 成对使用**——有默认值时筛选器一进页面就带值，`validateStatus` 不会是 error，必填只在用户主动清空时才拦人（这正是我们想要的护栏）。2026-07-30 撤回必填、2026-08-20 配默认值后重新开启，见日志 21/22。

28. **在 UI 里给筛选器设默认值可能把 `json_metadata` 写坏，且看不出报错**：生产看板 31 的「设备号(数据详情)」被 UI 存成了 `"defaultDataMask": "B52525000081783"`（**应该是 DataMask 对象**，字符串会让前端取 `dataMask.filterState` 得到 undefined）外加一个 `"requiredFirst": {"nativeEvent": ..., "target": {...}}`（**React 的 checkbox 事件对象被整个序列化进了配置**）。同一次编辑还把 `targets[0].datasetId` 从小快照表改到了 `ads_tb_history`（底表 `dwd_iot_device_pack_minute` 152 亿行），下拉框取值等于在大表上做 `GROUP BY device_sn`。**症状**：看板卡死、再点这个筛选器就报错。**判定**：直接 dump `native_filter_configuration`（`_deploy/_dbg_devfilter.py`），看 `defaultDataMask` 是不是 dict、有没有多出的怪 key。**对策**：这类配置改动走脚本落库（结构可断言、可备份、可回滚），别在 UI 里点；下拉选项一律指向小快照表（`ads_tb_device_latest_geo`，10383 行），筛选器发出的 `device_sn IN (...)` 靠列名同名照样作用于大表图表。

29. **`SELECT COUNT(*) FROM (聚合SQL)` 不能用来估聚合成本**：StarRocks 看到外层只要行数，会把内层 44 个 `MAX(JSON_QUERY(...))` 从执行计划里整个裁掉——本次据此得出"单日 3 秒"，实际带全部聚合列是约 2 分钟/天，导致 90 天回填的时间估错了两个数量级。**对策**：基准测试必须把真实列清单 `SELECT` 出来（哪怕 `LIMIT 50`），或者直接计时一次真实 `INSERT`。

30. **StarRocks 的 `INSERT OVERWRITE` 默认清空整表**：对自动分区表（`PARTITION BY (biz_date)`）不写 `PARTITION` 子句时，必须先 `SET dynamic_overwrite = true`（默认 `false`），否则只想覆盖 2 天却会把 90 天全删了再写 2 天。另外 `INSERT` 用的是 `insert_timeout`（默认 14400s）而不是 `query_timeout`（300s），所以长时间装载不会被 300 秒掐断。**更危险的一条**：`dynamic_overwrite` 写成语句提示 `INSERT /*+ SET_VAR(dynamic_overwrite = true) */ OVERWRITE ...` 时提示被**静默忽略**，行为退回"清空整表"。2026-09-18 在临时表 `_tmp_ds_hint_probe` 上实测：三个日分区里只覆盖一个，结果另外两个分区全没了。**对策**：只用"同一连接先 `SET dynamic_overwrite = true` 再 `INSERT OVERWRITE`"这一种写法；因此调度侧要能在一个会话里跑多条语句（mysql 客户端跑 SQL 文件），而不是只发单条语句的 SQL 任务。顺带一提，`ALTER TABLE ... DROP PARTITIONS WHERE <条件>` 在 4.0.9 上直接抛 `Database.getFullName() because "db" is null`，分区淘汰仍得逐个 `DROP PARTITION`。

31. **`partition_live_number` 在 4.0.9 上 `ALTER` 不报错但也不生效**：`ALTER TABLE ... SET ("partition_live_number"="90")` 返回成功，`SHOW CREATE TABLE` 和 `information_schema.tables_config` 里都查不到该属性，分区不会被自动淘汰。**对策**：保留窗口自己算——从 `information_schema.partitions_meta` 取出早于阈值的分区名逐个 `ALTER TABLE ... DROP PARTITION`（`sync_tb_history_daily.sh` 即如此），别指望这个属性。

32. **`jump_run.py` 的命令里把 `rm -f 脚本` 跟在 `nohup ... &` 后面，会在后台进程启动前把脚本删掉**：本次探测脚本就这样"文件不存在"失败了一次（更隐蔽的是上一次前台运行留下的 `rm` 在我断开后才执行，把重传的脚本删了）。**对策**：清理单独跑一条命令；生产脚本一律 `nohup ... > /tmp/x.log 2>&1 &` 后用另一条命令 tail 日志（跳板会话只等 20~30 秒，长任务必须这么跑）。

33. **被 Ctrl-C 打断的 `ssh` 并不会停掉远端的 `mysql`**：本次中断 90 天回填后，远端客户端仍在逐条执行剩余语句，我又起了两条并行流，结果三条重复装载互相抢资源（用户查询仍是秒级，但 DDL/元数据查询被锁等到 60 秒以上）。**对策**：重启长任务前先 `ps -o pid,etime,args -C mysql` 看有没有还在跑的，必要时按 pid `kill`。

---

## 五、常用脚本索引（`_deploy/`）

| 脚本 | 用途 | 备注 |
|---|---|---|
| `jump_put_fast.py <本地> <生产路径>` | 经跳板传文件到生产，带 sha256 校验 | 看 `REMOTE_SHA_MATCH=True` |
| `jump_run.py <命令文件> <秒>` | 经跳板在生产执行单条命令 | 命令文件用单引号、ASCII |
| `fix_detail_device_filter.py {apply\|verify\|revert}` | 卡车电池看板：「设备号(数据详情)」指回小快照表、钉死默认设备、设必填 | 幂等，`--dry-run`/`--sn=`/`--dash=`，改前快照到 `backups/` |
| `_dbg_devfilter.py [看板id]` | dump 看板的 `native_filter_configuration` 原文 + 各图表 viz/数据集/行数上限 | 只读，排查 UI 存坏的筛选器配置（坑 28） |
| `_probe_detail_tab_cost.py [设备SN]` | 数据详情 Tab 各查询在"单设备/全设备"下的耗时与行数，含底表规模 | 只读，直连 StarRocks，不走 Superset API |
| `sr_run.py <本地.sql> [--root] [--tail N]` | 把本地 `.sql` 经开发机（`agi@192.168.41.122`，唯一能直连 StarRocks 的机器）送进共享集群 | 数据层改动的标准通道，比跳板快一个数量级；`--root` 用 `/tmp/.sr_root.cnf`（含 root 口令，600 权限） |
| `build_history_daily_aggregate.py <模式> <out.sql> [...]` | 生成卡车电池日聚合表的 SQL：`create-table`/`load`/`range`/`backfill`/`compare`/`bench` | 只生成文件不连库；44 个聚合字段与 `ads_tb_history` 同源定义 |
| `optimize_pb_detail_click_latency.py {apply\|verify\|revert <备份目录>}` | 点击仅联动明细 370（避免 5 路并发）；曲线改跟左侧设备号 | 幂等，`apply` 前自动备份 |
| `tune_pb_detail_query_defaults.py {apply\|verify\|revert <备份目录>}` | 明细/曲线时间兜底改为 Current day，370 row_limit 降至 5000 | 幂等，`apply` 前自动备份 |
| `fix_pb_daily_paging_date_align.py {apply\|verify\|revert}` | 卡车电池：384 去翻页全量排序 + 点击同日明细 | 幂等；probe 失败自动回滚 |
| `fix_pb_detail_crossfilter_emit.py {apply\|verify\|revert <备份目录>}` | 修复 384 点击联动（`emitCrossFilters`）+ 左侧设备号仅作用日聚合 | 幂等，`apply` 前自动备份 |
| `guard_pb_detail_require_device.py {apply\|verify\|revert <备份目录>}` | 明细无设备号护栏：虚拟数据集 113，370/362–365 改指 | 幂等，`apply` 前自动备份 |
| `enable_pb_daily_detail_crossfilter.py {apply\|verify\|revert <备份目录>}` | 看板 31：chart 384 点击 device_sn 联动 370/362–365；从原生设备号筛选解耦 | 幂等，`apply` 前自动备份 |
| `deploy_ds_daily_workflow.py [apply\|verify\|run\|instances\|offline]` | 在生产 DolphinScheduler「数据中台」注册/校验/手动跑/下线日聚合工作流 | 幂等；凭据由调用方提供，不入库；API 走 `10.100.19.1` |
| `sync_tb_history_daily.sh [天数]` | 覆盖最近 N 天日聚合 + 裁剪 90 天窗口 | 部署在 DolphinScheduler 机 `10.100.21.202:/data/bi-sync/`（属主 `dolphin`），DS 每天调一次、窗口 3 天；`flock` 防并发；`SR_HOST`/`SR_PORT`/`SR_USER`/`SR_PASS`/`BUILDER` 可用环境变量覆盖 |
| `apply_chart_desc.py` | 批量写图表悬停口径说明（两看板） | 幂等，改文案重跑 |
| `pb_show_value.py` | PB 所有柱状图开启 show value | 幂等 |
| `apply_tab_icons.py` | 两看板 Tab 名称加图标 | 幂等 |
| `pb_pct_unify.py` | PB 的 SOC/SOH 卡片统一百分比显示 | 幂等 |
| `collect_ads_ops_sr_light.py apply` | （历史）数据中台速览轻量快照 `ads_ops_sr_*` | 已被 Cockpit P0 取代；可停 |
| `build_dp_sr_overview.py {apply\|verify}` | （历史）表格版「数据中台速览」 | 已被 `build_sr_cockpit.py` 取代 |
| `collect_starrocks_ops_p0.py apply` | StarRocks Cockpit：DDL + `ads_ops_cockpit_*` 采集（phase1+2：hist增长/7d冷表/Digest一次扫/资产·存算·任务快照） | 需新数据时再跑；主机 crontab 每 15 分钟；看板不直扫 audit |
| `build_sr_cockpit.py {apply\|verify}` | 建/验「StarRocks Cockpit·数据中台速览」（总览/Query/资产/存算/任务/治理） | 幂等；前缀 `驾驶舱·` |
| `sync_sr_cockpit_collect.sh` | Cockpit 采集 crontab 包装（flock + 日志） | 装在 `10.100.19.1:/mnt/data/superset/` |
| `build_run_analysis_tab.py` | （历史）建看板 38「运行分析」Tab：数据集 190–195 + 图表 644–653 + Tab 内筛选器 | **不要再跑**：该 Tab 已手工拆成「运行状态」+「性能分析」，重跑会把布局推回单 Tab |
| `apply_run_status_rework.py` | 「运行状态」/「性能分析」双 Tab 返工：筛选器跨 Tab 重新作用域、审计明细、查询平均耗时、TOP 榜按语句前 200 字符聚合、导入任务并入 routine load / pipe | 幂等；改前自动快照到 `backups/dp-sr-global_*_run_status.json` |
| `sync_sr_rg_bindings.py` / `.sh` | 解析 `SHOW RESOURCE GROUPS ALL` 的 classifier 落 `bluetti.ads_sr_global_rg_bindings`，供「用户清单」的资源组列关联 | `10.100.19.1` crontab 每小时第 23 分；滚动保留 3 份快照 |
| `authz_model.py {baseline\|migrate\|revoke\|retire}` | **授权模型唯一真源**：生成`只读基线`、逐看板建零权限受众角色并挂 RBAC、回收数据授权、退役旧角色；每步带全员可见性零漂移自检与自动回退 | 幂等，支持 `--dry-run`（**注意 dry-run 仍会建空角色**），取代 `ro_role_policy.py`/`groups_setup.py` |
| `authz_probe.py` | 以每组代表真实走 HTTP 验证新模型：列表/打开/取数/分享/筛选/下钻/中文包 + 负向（建看板、脱离看板取数应 403） | 只读，改授权后必跑 |
| `patch_editor_ownership.py` | 配置补丁：重写 `raise_for_ownership`，持挂在看板 RBAC 上的`编辑·X`角色 = 该看板及其图表的 Owner（**需重启**，编辑授权页面化的前提） | 幂等，备份 `.bak.editorown`，语法自检失败自动还原 |
| `editor_group_setup.py <看板id>` | 每看板一次性：建`编辑·<看板名>`角色（含数据集授权）+ 挂看板 RBAC + 建组「<看板名>编辑」（Gamma+该角色）；之后日常授权=页面上往组加人 | 幂等，支持 `--dry-run` |
| `_editor_probe.py <看板id> <观众>` | 编辑授权端到端验证：零角色零 Owner 探针用户入组后可 GET/PUT 图表、跨看板被拒、观众被拒，自动清理探针用户 | 只读语义（探针 PUT 用原值） |
| `grant_dashboard_editor.py <看板id> <用户>` | 旧路径（直授+挂 Owner）：进看板制作者组 + 直授`编辑·<看板名>`角色 + 看板/图表/数据集 Owner；适合临时给单人开权限 | 幂等，支持 `--revoke`/`--dry-run` |
| `_authz_snapshot.py` | 全量授权关系快照（角色→权限、用户/组→角色、看板→RBAC）落 JSON 到主机 `backups/` | 只读，动授权前先跑 |
| `fix_ds54_guard.py [apply\|revert]` | 生产数据集 54（电池包明细，71 亿行）加"无时间筛选返回空"护栏，防裸查打爆 StarRocks 内存 | 幂等，带备份/回滚与真实用户验证 |
| `fix_detail_time_filter.py [apply\|verify\|revert]` | 卡车电池看板：把左侧「时间范围」作用域放开到全部图表、删掉重复的「时间范围(数据详情)」、明细表行数上限 5000→50000 并追加"先选设备号"提示 | 幂等，支持 `--dry-run`；改前自动快照 `backups/dash<id>_timefilter_*.json` |
| `_verify_detail_e2e.py` | 端到端验证明细表：选定设备 + 指定时间范围后，页面取数与 CSV 导出的时间跨度是否真覆盖所选范围 | 只读，用测试客户端注入 admin 登录态 |
| `_check_filter_scope.py [看板id\|标题片段]` | 巡检看板筛选器作用域：`scope.excluded` 推导值 vs 存的 `chartsInScope`，并提示"同类型筛选器有多个"（"这张图不受筛选限制"的头号成因） | 只读；缓存漂移是无害的，别去逐个修（坑 9） |
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

### 2026-09-24（Cockpit 资产 Tab 增强）

1. **采集**：`collect_starrocks_ops_p0.py` 新增 `db_overview` / `asset_kpi` / `table_inventory` / `columns` / `sr_users` / `privileges`；`refill_select`（TRUNCATE+INSERT SELECT）；权限不可读时占位行；活跃账号取 audit 近 7 天。
2. **看板**：`build_sr_cockpit.py` 资产 Tab 增加 KPI/库一览/全量清单/表结构护栏虚拟集/活跃账号/权限；清单→表结构 cross-filter；模型/分区/最近创建保留为次要。
3. **对象清单**已同步。未部署（由父任务部署）。

### 2026-09-21（卡车电池：384 去翻页 + 点击同日）

1. 生产看板 `pb-device-analysis`：chart 384 开启服务端分页 500 并用 CSS 隐藏翻页；点击发出 `device_day_key=device_sn::biz_date`。
2. 数据集 113：Jinja `remove_filter=True` 拆键为索引条件；护栏仍要求有设备号或复合键。
3. 脚本 `_deploy/fix_pb_daily_paging_date_align.py`；备份 `20260921_153322_pb_daily_paging_date_align`；`VERIFY|PASS`。

### 2026-09-21（Cockpit phase1修整 + phase2 Tabs）

1. **phase1 采集修整**（`collect_starrocks_ops_p0.py`）：取消每轮 DROP kpi/digest，仅 `CREATE IF NOT EXISTS`；冷表列迁 `hit_n_7d`（缺失则一次性 DROP 重建）；`table_hist` 追加并剪 48h；增长对 ≤NOW-20h 最近基线；Digest 单次 GROUP BY≤200 后 Python 七维 TOP10；热门表 LIKE 仅 TOP10 / 7d；冷表 >10GB 且 7d 无命中；`query_timeout=35s`。
2. **phase2 Tabs**：看板 Tab 序 `总览/Query/资产/存算/任务/治理`；新增 `cn_nodes` / `mv` / `task_fail` / `loads` / `table_model` / `part_count` / `recent_table` / `rg_day`；总览去掉「重用户」，冷数据文案改 7d，热门表标题「热门表TOP10(近似)」。
3. **运维**：`enable_sql_digest=true` 需写入 **fe.conf** 持久化（仅 `ADMIN SET` 会在 FE 重启后丢失）。对象清单已同步。脚本 `build_sr_cockpit.py` 前缀仍 `驾驶舱·`。

### 2026-09-21（Cockpit 强化：双Y / Query下钻 / 治理 / 15min采集）

1. **双 Y 轴**：`驾驶舱·Query量与P95趋势` 改为 `mixed_timeseries`（左 Query Count，右 P50/P95 ms）。
2. **三 Tab**：总览 / Query（Digest 七维榜 + 慢SQL明细）/ 治理（用户消耗 + 冷表）。
3. **采集增强**：`ads_ops_cockpit_user_day` / `_cold_table` / `_slow_sql` / `_hot_db`；热门表用大表名 stmt LIKE；KPI 增 cold_bytes / heavy_user。
4. **定时**：`10.100.19.1` crontab `*/15` → `sync_sr_cockpit_collect.sh`。
5. **AuditLoader / Digest**：探查确认历史 `digest` 全空；已执行 `ADMIN SET FRONTEND CONFIG ("enable_sql_digest"="true")`（当前为 true）。**FE 重启后可能丢失**，需运维写入 `fe.conf` 持久化。`QueriedRelations` 仍空，热门表继续 stmt LIKE。看板 `VERIFY|PASS`（31 图）。

### 2026-09-21（数据中台速览 → StarRocks Cockpit P0，生产）

1. **按设计方案** `project/数据中台情况速览/starrocks_superset_dashboard_design.md` **§24 首页 18 图**落地 P0：看板 37 升级为「StarRocks Cockpit·数据中台速览」（slug 仍 `dp-sr-overview`），图表前缀 `驾驶舱·`，共 20 张（KPI×8 + 趋势/榜单 + 当前查询/失败 SQL）；`VERIFY|PASS`。
2. **快照层** `bluetti.ads_ops_cockpit_*`（无 `CREATE DATABASE` 权限，未建 `starrocks_ops`）。采集 `_deploy/collect_starrocks_ops_p0.py`；建板 `_deploy/build_sr_cockpit.py`。
3. **现网差异**：`audit.digest` / `QueriedRelations` 全空 → soft-digest + 热度按 `audit.db`；Compaction 列名为 `MAX_CS`；Cache 用 `fe_metrics`/`be_metrics` 追加时序。
4. **对象清单**已更新。P1/P2 下钻页未做。RBAC 角色/组不变。

### 2026-09-21（数据中台速览，生产 · 初版表格看板）

1. **新建看板「数据中台速览」**（slug `dp-sr-overview`，生产 id=37）：六 Tab（总览/集群/审计/用户/仓库/MV），14 张表图；`refresh_frequency=0`；角色 `看板·数据中台速览`。
2. **轻量快照层** `bluetti.ads_ops_sr_*`：采集脚本 `_deploy/collect_ads_ops_sr_light.py`（`query_timeout=25s`，审计仅近 24h 聚合/TOP，库存只扫 bluetti，**不做 Paimon 探活**）。看板不直扫 `audit_db`。
3. **对象清单**：根目录 `数据中台速览-对象清单.md`。建看板脚本：`_deploy/build_dp_sr_overview.py`。
4. **授权**：`authz_model.py migrate` 已覆盖看板 37；组「数据中台速览观众」=`只读基线`+`看板·数据中台速览`（空组，在 Security ▸ Groups 加人）。`information_schema.user_privileges` 对 `agi` 当前 0 行，权限 Tab 可能为空。
5. **注意**：刷新数据时手动再跑 collect，勿高频。

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

21. **修复「设备数据明细」不受左侧时间范围限制、且下载像是全量**（2026-07-30，`fix_detail_time_filter.py`，开发看板 32 + 生产看板 31 均已应用并验证，**不需重启**）：两个成因叠在一起（详见坑 26）。① 看板有两个 `filter_time` 筛选器，左侧主「时间范围」的 `scope.excluded` 把数据详情 Tab 的 6 张图（开发 752~757 / 生产 361~366）全排除了，真正管它们的是另一个「时间范围(数据详情)」——用户拖主筛选器自然毫无反应。② 明细表 `ORDER BY event_time DESC` + `row_limit=5000`，而 `ads_tb_history` 全设备每分钟 260~370 行，5000 行只覆盖最新约 13 分钟，所以即使筛选生效，显示的永远是所选范围最末那十几分钟（默认范围到今天 → 永远是 7-30）。
    **改动**：主「时间范围」`excluded` 清空并同步 `chartsInScope`（管全看板 38 张图）；删掉重复的「时间范围(数据详情)」；明细表 `row_limit` 5000→50000（单设备约 1 行/分钟，50000 行≈34 天，时间范围才真实可见）；明细表 `description` 追加提示"请先在左侧选择设备号再选时间范围"。**图表自带的写死"最近 7 天"故意不动**：看板传来的 `time_range` 会覆盖它（坑 26），留着正好给 Explore 单独打开时兜底。
    **中途撤回的一步（重要）**：本想把「设备号(数据详情)」设成必填（`controlValues.enableEmptyFilter=true`）来强制先选设备，**实施后立即回退**——`enableEmptyFilter` 的校验是**看板级**的：`FilterBar/utils.ts` 的 `checkIsApplyDisabled` 只要发现**任意一个**筛选器 `validateStatus==='error'` 就禁用整条筛选栏的「应用」按钮，于是"详情 Tab 没选设备"会把其它 4 个 Tab 的时间/型号/省份筛选一起锁死。**结论：必填只适合"整个看板都围绕这个筛选器"的场景，给某个 Tab 专用的筛选器设必填会连坐全看板**。改用图表说明提示代替。
    **下载不是独立问题**，无需任何改动：看板里导出用的就是合并了看板筛选的 formData，实测导出与页面结果逐行一致。
    **验证**（两环境输出完全相同）：不选设备 → 50000 行仅 1 天（所以要有提示文案）；选 1 台设备 + 最近 30 天 → 28156 行跨 31 天（06-30~07-30）；选 1 台设备 + 7-01~7-10 → 8033 行跨 9 天；同条件 CSV 导出 → 8033 行、跨度一致。快照 `backups/dash32_timefilter_*.json` / `dash31_timefilter_*.json`，`fix_detail_time_filter.py revert` 可回滚（会一并还原 `description`）。**用户侧需硬刷新一次**（浏览器缓存着旧的筛选器配置）。
    **未做**：`ALLOW_FULL_CSV_EXPORT` 仍关闭。开了会多一个"导出完整 CSV"菜单（同样受筛选约束，行数上限走 `SQL_MAX_ROW=100000`）；当前导出上限已是图表的 50000 行，够用就没引入这个重启动作。

22. **修复「设备号(数据详情)」配置损坏：钉死默认设备 + 开必填**（2026-08-20，`fix_detail_device_filter.py`，开发看板 32 + 生产看板 31 均已应用并验证，**不需重启**）：现象是打开看板卡死、动这个筛选器就报错。dump 生产 `native_filter_configuration` 后发现该筛选器被 UI 存坏了（详见坑 28）：`defaultDataMask` 是字符串 `"B52525000081783"` 而非 DataMask 对象、多了一个装着 React checkbox 事件的 `requiredFirst`、`targets[0].datasetId` 还从小快照表 `ads_tb_device_latest_geo`(102) 被改到了 `ads_tb_history`(104)——于是下拉框取值要在 152 亿行的 `dwd_iot_device_pack_minute` 上 `GROUP BY device_sn`（实测 3.8s，且每次开看板都跑）。开发环境同一筛选器没被动过（仍指向 75，不必填、无默认值）。
    **改动**（两环境同一份配置）：`targets` 指回小快照表（10383 行，`DISTINCT` 0.0s，device_sn 值域与大表一致）；`defaultDataMask` 写成合规对象，钉死 `device_sn IN ['B52525000081783']`；`enableEmptyFilter=true`（必填）、`defaultToFirstItem=false`（"取第一条"要额外查一次且结果不可复现）；删掉垃圾 `requiredFirst`；同步 `chartsInScope`（开发 753~757 / 生产 362~366）。**必填这次能开，是因为配了默认值**——进页面就带值，`validateStatus` 不会是 error，不会连坐锁住其它 Tab 的「应用」按钮（坑 27），只有用户主动清空设备时才拦，这正是防全量扫描的护栏。
    **数据层实测**（`_probe_detail_tab_cost.py`，7 天窗口）：单设备明细 0.1s/3378 行、单设备 SOC 曲线 0.1s；全设备明细 0.5s、全设备曲线 0.3s；`ads_tb_history` 视图 7 天 364 万行、总量 3092 万行，底表 152 亿行。**结论**：详情 Tab 各图自带"最近 7 天"兜底（坑 26），在默认窗口下即使不选设备也不至于卡死；真正会打爆的是把左侧时间范围拉宽/清空后全设备扫大表，以及上面那个大表下拉框。钉死默认设备把两条路都堵上了。
    **验证**：`fix_detail_device_filter.py verify` 两环境均 `VERIFY|PASS`（目标数据集、5 项 controlValues、defaultDataMask 逐字段比对、无垃圾 key）；应用前断言 `B52525000081783` 确实在快照表里（`SN_CHECK|rows_in_snapshot=1`），设备不存在会直接 ABORT，不会钉一个死默认值。快照 `backups/dash32_devfilter_*.json` / `dash31_devfilter_*.json`，`fix_detail_device_filter.py revert` 可回滚。**用户侧需硬刷新一次**（浏览器缓存着旧的筛选器配置）。
    **换默认设备**：`./venv/bin/python fix_detail_device_filter.py apply --sn=<新SN>`，脚本会先校验该 SN 在快照表中存在。

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

**追加坑（时间筛选中文显示成「货币」「运行查询」，2026-10-12）**：上游 zh `.po` 里 `Current day/week/...`、`Last day/...` 等是 `#, fuzzy` 的机器乱猜译文，而生成语言包用了 `--fuzzy`/`-f`，所以错译直接上屏。fork 提交 `e0636da4` 把正确译文**追加到文件末尾**而不是改原条目，导致同一 msgid 出现两次，po2json/pybabel 取**第一条**（错的），修正不生效。**对策**：改译文一律就地改原条目并去掉 `fuzzy`，不要追加。fork 提交 `d3af4182` 已合并 40 条重复项并补 `Start (inclusive)`/`End (exclusive)`。只换 zh 三件套的流程：构建机 `_gen_zh_langpack.sh` 生成 json → `_install_zh_lang.sh <venv> <dir>`（自动备份到 `LC_MESSAGES/backup_<时间戳>/`、编译 `.mo`）→ 重启。检查脚本 `_audit_zh_datefilter.py`（本地查重复/fuzzy）、`_verify_zh_datefilter_served.sh`（测试机）、`_verify_zh_datefilter_prod.py`（生产，ASCII 输出）。测试 + 生产均已应用，sha256：json `e76bf4c1…`、po `5e917e82…`。

### 历史变更
- 2026-10-14 chart 648「CPU消耗TOP100」、649「内存消耗TOP100」加「最大耗时(毫秒)」列（`MAX(query_ms)`，插在「平均耗时」左边）。用户此前已手工把 647 改名「任务耗时TOP100」、三张 TOP 表拉到整行宽并在 Explore 里存过一次（`params` 多出 `server_pagination`/`show_totals`/`allow_rearrange_columns` 等控件），所以脚本只改 `metrics` 一个键，其余 20 个键原样保留。脚本：`_deploy/apply_top_add_duration.py`；备份 `/mnt/data/superset/backups/top_charts_20261014_103604.json`。
- 2026-10-14 摸清了 StarRocks 集群硬件信息的来源：**6 个节点（3 FE + 3 CN）都跑着 node_exporter 1.5.0，9100 端口从 Superset 机可直连**，`dmi`/`os`/`cpu`/`diskstats`/`filesystem`/`netclass`/`nvme`/`hwmon` 等 collector 均正常，不需要 SSH 也不需要装 agent。StarRocks 自身只给到 CN 的 `CpuCores`/`MemLimit`/`MemUsedPct`/`CpuUsedPct`/`DataCacheMetrics`（`SHOW COMPUTE NODES`），**FE 侧 `SHOW FRONTENDS` 完全没有硬件列**；`information_schema.be_metrics`(524 指标)/`be_datacache_metrics`/`fe_metrics`(JVM) 可补充运行时但同样没有机器规格。node_exporter 唯一缺的是 CPU 型号（需启 `--collector.cpu.info`，本版本未开）。集群实况：全部阿里云 ECS、Ubuntu 24.04.3、内核 6.8.0-90，每节点 8 核 / 30.4GB / 3 块 NVMe 云盘（系统盘 41.9GB + `/data1`、`/data2` 各 322GB xfs）；FE 与 Flink、Superset、DolphinScheduler 同机（`10.100.11.201` 即 `10.100.19.1` 本机，主机名 HK-IaaS-AGI-Flink-01）。
- 2026-10-13 生产看板 38「运行分析」Tab 经用户手工拆成「运行状态」+「性能分析」后返工。**手工拆 Tab 会让筛选器静默失效**：5 个筛选器的 `scope.rootPath` 还钉在 `TAB-525bfeeea0`，移到新 Tab 的 645–649 直接掉出作用域，`chartsInScope` 那份缓存仍列着它们所以表面看不出来（坑 9 的同一类问题）。已把 `rootPath` 改成 `[运行状态, 性能分析]` 两个 Tab 并重算 `excluded`。其余改动：chart 650「当前运行任务」改成「审计明细」（改挂数据集 190、`ts` 倒序、1000 行，数据集 191 `v_run_current_queries` 就此闲置但保留）；645 改名「查询平均耗时趋势」并固定 `task_kind='SELECT'`，因为 `SET`/`SHOW`/`COMMIT`/`ROLLBACK` 平均耗时接近 0ms（近一天 `SET` 8276 条均值 0ms），混进去会把均值压低，同时把它移出「任务类型」筛选作用域以免条件互斥出空图；646 由「总耗时」改成「平均耗时趋势（按类型）」并从柱状改折线；647/648/649 三张 TOP 榜改成按 `SUBSTR(stmt,1,200)` 聚合（近一天 573,175 行压到 50,751 个模板），耗时/CPU/内存取 `MAX`，另给出执行次数、平均耗时、最近执行时间、用户、库。脚本：`_deploy/apply_run_status_rework.py`；备份 `/mnt/data/superset/backups/dp-sr-global_20261013_180907_run_status.json`。
- 2026-10-13 表格图在本实例的服务端排序键是 **`timeseries_limit_metric` + `order_desc`**（不是 `series_limit_metric`）。判断依据是实例里 30 多张在用的聚合表格都这么写（如 chart 92/166/176/185/273/274）。聚合模式下 `groupby` + `metrics` 生效、`all_columns`/`order_by_cols` 被忽略；原始模式反之。
- 2026-10-13 `information_schema.loads` **已经包含 `STREAM_LOAD`/`BROKER LOAD`/`SPARK LOAD`**，不要再 union `information_schema.stream_loads`（会重复计数）。真正不在 `loads` 里的是 `routine_load_jobs` 和 `pipes`，当前集群这两张都是 0 行。另外 `loads` 只保留最近一段时间的作业（受 FE `label_keep_max_second` / `label_keep_max_num` 限制，实测约 12 小时），不能当历史表用。`load_tracking_logs` 必须带 label 或 job_id 才能查，不能裸 `SELECT`。
- 2026-10-13 生产看板 38「数据中台速览」新增「运行分析」Tab（`TAB-525bfeeea0`）：数据集 190–195（`v_run_audit` / `v_run_current_queries` / `v_run_loads` / `v_run_mv_status` / `v_run_task_fail` / `v_show_users_rg`），图表 644–653（任务量趋势（按类型）、平均耗时趋势、总耗时趋势（按类型）、执行耗时/CPU 消耗/内存消耗 TOP100、当前运行任务、物化视图刷新状态、数据导入任务、调度任务失败记录），Tab 内 5 个筛选器（时间范围默认近 1 天上限 7 天、时间粒度默认小时、任务类型、用户、资源组）。任务按 `stmt` 首词归类（`SELECT`/`INSERT`/`UPDATE`/…）。平均耗时**单位是毫秒**：实测每小时均值 104–167ms，取整到秒会全是 0。「用户清单」(chart 556) 增加 `资源组` 列，取**配置绑定**（`SHOW RESOURCE GROUPS ALL` 的 classifier），不是审计日志里实际跑过的组；没有 classifier 的用户（`root`/`dashboard`/`ro_geo`）显示 `-`，实际落 `default_wg`。脚本：`_deploy/build_run_analysis_tab.py`、`_deploy/apply_run_analysis_followups.py`；备份 `/mnt/data/superset/backups/dp-sr-global_20261012_212041_run_analysis.json`。
- 2026-10-13 `SHOW RESOURCE GROUPS ALL` 不能在 SQL 里 join，所以新增 `10.100.19.1` crontab **每小时第 23 分** 跑 `sync_sr_rg_bindings.sh`，把 classifier 解析进 `bluetti.ads_sr_global_rg_bindings` 供「用户清单」关联。写新 `snapshot_ts` 再删旧的（保留最近 3 份），读侧取 `MAX(snapshot_ts)`，避免 TRUNCATE 期间读到空表。注意这张表原先只有 `sync_sr_global_collect.py` 手工跑时才更新，而那个脚本**从未接入任何调度**（本来是给 DolphinScheduler 准备的），数据从 2026-09-29 一直停到现在。脚本：`_deploy/sync_sr_rg_bindings.py` / `.sh`。
- 2026-10-13 StarRocks 小于一天的时间粒度（秒/分/小时）全部改走 `DATE_TRUNC`，测试与生产 `superset_config.py` 均已加 `TIME_GRAIN_ADDON_EXPRESSIONS`。根因：StarRocks 引擎继承 MySQL 的 `DATE_ADD(DATE({col}), INTERVAL HOUR({col}) HOUR)`，而 Superset 执行前会用 sqlglot 重写语句并把外层 `DATE()` 吃掉，截断就变成了偏移——按小时分组会退化成按原始时间戳分组（实测 215 行变 10000 行）。`DATE_TRUNC` 过重写不变形。改完 `kill -HUP` gunicorn 主进程即可生效。测试机备份 `backups/superset_config.py.20261013_085437`。
- 2026-10-12 测试机 41.122 换装 master（`3569ffc`）构建的前端 + master 版 `models.py`，上线「看板时间筛选器·限制可选时间范围」与「命令数据集排序」；核对脚本 22 项全过。构建脚本 `_build_frontend_master.sh`（约 6 分钟），部署脚本 `_deploy_master_to_test.sh`；回滚：`static/assets_prev_20261012145536` 换回 `assets`、`connectors/sqla/models.py.bak_20261012145536` 换回，重启。生产待验证后再发。
- 2026-10-12 fork 分支统一：GitHub `250715122/superset` 只保留 `master`（`3569ffc7`），原 `test-6.0-changes` 的插件提交（自研 ECharts 插件 + GeoMaps）与 ops 脚本提交已摘入 master，ops 里的 JumpServer 账号密码改为读环境变量 `JUMP_USER`/`JUMP_PASSWORD`，含明文密码的 `test-6.0-changes` 已从 GitHub 删除（旧提交按 SHA 仍可访问，需改密码）。构建机 `/opt/superset-build` 已切到 `master` 并跟踪 `origin/master`，切换前本地改动备份在 `~/superset-build-backup/20261012143933/`；`test-venv/`、`superset_config_test.py` 写进 `.git/info/exclude`。核对结论：插件/地图/翻译/后端 6 个文件三边一致；`models.py` 生产=master（差 3 个空行），测试机缺「命令数据集排序」；前端「限制可选时间范围」只在 master，测试/生产均未发布。核对脚本 `_make_expected_master.py` + `_verify_deployed_vs_master.py`。
- 2026-10-12 修正 zh 时间筛选译文（Current/Last/previous calendar 等），测试 41.122 与生产均已替换 zh `messages.po/json/mo` 并重启；备份 `translations/zh/LC_MESSAGES/backup_20261012112704`（测试）、`backup_20261012113227`（生产）。fork 提交 `d3af4182`。
- 2026-09-24 Cockpit 资产 Tab 增强：`db_overview`/`asset_kpi`/`table_inventory`/`columns`/`sr_users`/`privileges` + 虚拟护栏 `columns_guard`；清单→表结构 cross-filter；权限不可读时占位。脚本 `collect_starrocks_ops_p0.py` / `build_sr_cockpit.py`。见「数据中台速览-对象清单.md」。
- 2026-09-22 Email 打标展示微调：`tags_history` 去掉时间只保留标签；工单明细新增 `replies_history`；轮次明细新增本轮 `customer_message`/`reply_body`（anchor 留言 + 轮次后非公开评论，末轮回落 ticket.reply_body）。脚本同 `_deploy/add_email_tag_round_history.py`。
- 2026-09-22 生产看板 29「数据明细」：Email 多轮打标历史可见。chart 292 `Email工单明细` 改挂新逻辑视图 `dws_cs_email_ticket_history_detail`（数据集 151），新增列 `tag_round_count`、`tags_history`；原物化对象 `dws_cs_email_ticket_detail` 未改。新增 chart 493 `Email打标轮次明细`（数据集 152 / `dws_cs_email_ticket_tag_round_detail`，一行一轮）。源表 `email_ticket_tag_round` 已在 Paimon；验收 139,309 工单、180 个多轮、最多 6 轮。接入时间范围/站点/明细日期。脚本：`_deploy/add_email_tag_round_history.py`；备份：`/mnt/data/superset/backups/20260922_105124_email_tag_round_history/before.json`；变更前保护快照：`.../manual_dashboard_baselines/cs-bi-overview/20260922_104651.*`。
- 2026-09-21 Cockpit phase1修整+phase2 Tabs：去每轮 DROP、hist≥20h 增长、冷表7d、Digest一次扫、六 Tab（资产/存算/任务）；fe.conf 需持久化 `enable_sql_digest`。脚本 `collect_starrocks_ops_p0.py` / `build_sr_cockpit.py`。
- 2026-09-21 Cockpit 强化：双 Y 轴、Query/治理 Tab、User+冷表、15min crontab；`VERIFY|PASS`（31 图）。脚本 `collect_starrocks_ops_p0.py` / `build_sr_cockpit.py` / `sync_sr_cockpit_collect.sh`。
- 2026-09-21 生产看板 37 按设计方案升级为「StarRocks Cockpit·数据中台速览」P0（§24 首页）：`ads_ops_cockpit_*` + `collect_starrocks_ops_p0.py` / `build_sr_cockpit.py`；`VERIFY|PASS`。见「数据中台速览-对象清单.md」。
- 2026-09-20 审计 `audit_db.audit` 确认：点击联动 SQL **已带当天 event_time**（非无时间路径），scanRows≈107；但一次点击并发打 370+四条曲线，单条 queryTime 17–25s（cpuCostNs 极高），实验室 5 路并行约 8–9s、单路约 3s。优化：cross-filter 接收方改为仅 370；曲线 362–365 改回跟随左侧设备号。备份：`/mnt/data/superset/backups/20260920_100827_pb_detail_click_latency`。脚本：`_deploy/optimize_pb_detail_click_latency.py`。
- 2026-09-20 排查明细联动慢：设备号+当天在 `ads_tb_history`（底层 Paimon 日分区约 1800 万行 + `PARSE_JSON`/46 列投影）单次约 2.7–3.5s，属存储/视图成本而非缺筛选；点击会同时刷新 370+四条曲线。将 370/362–365 图表自带时间兜底从「近 7 天」改为 `Current day`，370 `row_limit` 50000→5000。备份：`/mnt/data/superset/backups/*_pb_detail_query_defaults`。脚本：`_deploy/tune_pb_detail_query_defaults.py`。
- 2026-09-19 生产看板 31「数据详情」修复 384→370 点击联动：根因是 Superset 6 表格需 `emitCrossFilters=true` 才会 `setDataMask`，此前仅写了 `chart_configuration` 未开发射；顺带把左侧「设备号(数据详情)」加回仅作用于日聚合 chart 384（明细/曲线仍解耦，避免与点击 AND 空结果），修正 chart 370 节点过期 `parents`，并把 384 残留 `event_time` adhoc 改为 `biz_date`。备份：`/mnt/data/superset/backups/20260919_181813_pb_detail_crossfilter_emit`。脚本：`_deploy/fix_pb_detail_crossfilter_emit.py`。
- 2026-09-19 生产看板 31「数据详情」明细无设备号护栏：新建虚拟数据集 113 `ads_tb_history_by_device`（无 `filter_values('device_sn')` 则 `AND 1=0`），chart 370/362–365 改指 113；未点日聚合设备号时 0 行约 0.2s，点击联动带设备号后正常出数。备份：`/mnt/data/superset/backups/20260919_074638_pb_detail_device_guard`。脚本：`_deploy/guard_pb_detail_require_device.py`。
- 2026-09-19 生产看板 31「数据详情」：chart 384 点击 `device_sn` 单元格通过 cross-filter 联动 chart 370 与历史曲线 362–365；接收图已从原生「设备号(数据详情)」解耦（该筛选现无作用图且取消必填），避免与默认设备 AND 出空结果；顺带把「时间范围(数据详情)」作用域恢复为含 361/362–365/370/384。备份：`/mnt/data/superset/backups/20260919_072313_pb_daily_detail_crossfilter`。脚本：`_deploy/enable_pb_daily_detail_crossfilter.py`。
- 2026-09-18 生产看板 31 chart 384「设备数据日聚合(按设备/日期)」改为读预聚合物理表 `bluetti.ads_tb_history_daily`（46 列，按 `biz_date` 自动分区、`device_sn` 8 分桶），排序/翻页从 46~77 秒降到 0.26~0.38 秒。**选型有实测依据**：按天分区物化视图能穿透 `UNION ALL` 推导出 Paimon `pt` 分区，但单分区刷新 6 分钟未完成、且首次异步刷新会从最老分区起串行刷满 91 个分区；而带 `pt` 谓词直接写物理表约 2 分钟/天。写入用 `SET dynamic_overwrite = true` + 无 `PARTITION` 子句的 `INSERT OVERWRITE`，只覆盖命中日分区（**不设这个变量会清空全表**）。口径核对：2026-09-17 全天 3,362 个设备×日组合、44 列逐值与 `ads_tb_history` 的 `MAX` 一致，差异 0。新增生产数据集 112（显式建列、`main_dttm_col=biz_date`）；chart 384 仅改数据源、`groupby`、`order_by_cols` 并去掉时间粒度，44 个 `MAX` 指标与筛选器作用域原样保留。增量刷新交给生产 DolphinScheduler 3.4.1（`10.100.21.202:12345`，standalone，服务用户 `dolphin`）项目「数据中台」工作流 `ads_tb_history_daily`（每天 02:00 跑一次 Shell 任务 `bash /data/bi-sync/sync_tb_history_daily.sh 3`，窗口 3 天吸收迟到数据，单天约 3 分钟）；脚本和 SQL 生成器装在该机 `/data/bi-sync/`，属主 `dolphin`。开发机 `192.168.41.122` 上临时加过的 crontab 已 `crontab -r` 撤除。回滚：`repoint_pb_daily_aggregate.py revert /mnt/data/superset/backups/20260918_154855_pb_daily_aggregate_repoint`。脚本：`_deploy/build_history_daily_aggregate.py`、`_deploy/repoint_pb_daily_aggregate.py`、`_deploy/sync_tb_history_daily.sh`、`_deploy/sr_run.py`。
- 2026-09-17 生产看板 31「卡车电池设备分析」的「数据详情」Tab 在原明细 chart 370 上方新增 chart 384「设备数据日聚合(按设备/日期)」：按 `device_sn + DATE(event_time)` 聚合，当前明细其余 44 个字段全部取 `MAX`。筛选器仅纳入「时间范围(数据详情)」，显式排除全局时间、设备型号、省份和设备号筛选器。QueryContext、生成 SQL 日粒度、布局顺序和筛选作用域均验证通过。脚本：`_deploy/add_pb_detail_daily_aggregate.py`；备份：`/mnt/data/superset/backups/20260917_181340_pb_detail_daily_aggregate/`。
- 2026-09-17 生产看板 29 新增「产品与导购」Tab（chart 375–383、数据集 108–110）：统一 Chat 有效会话关联产品与 Email `product_models` 提取型号，提供产品关联案例/覆盖率/型号数/命中次数 KPI、跨渠道 TOP20、历史趋势、站点分布、服务结果及未归一型号。新增 `dws_cs_product_model_case` 物化视图、`ads_cs_product_model_daily` / `ads_cs_product_coverage_daily` 普通视图；Email 按 `products.name/alias` 归一。`chat_session_products` 因无主键被主 CDC 排除，改由测试 Flink 同步机 `/home/agi/bi-sync/sync_chat_product_bridge_snapshot.sh` 每小时第 17 分全量去重对账至 `ods_cs_chat_session_products`，初始 19,010 行；未占用或重启现有 Flink 作业。生产元数据备份：`/mnt/data/superset/backups/20260917_165446_product_model_analysis/before.json`。脚本：`_deploy/sync_chat_product_bridge_snapshot.sh`、`_deploy/build_product_model_views.py`、`_deploy/add_product_model_analysis.py`、`_deploy/_probe_product_model_analysis.py`。
- 2026-09-17 生产看板 29「数据明细」chart 326 `Chat对话明细` 新增 `user_id`：最终口径为实际用户消息发送者关联的 `chat_user.user_id`（Zendesk/Sunshine 用户标识），不是内部 `chat_message.sender_id`，也不使用可能指向 business 用户的 `chat_session.chat_user_id`。近 7 天用户消息外部 ID 覆盖率 100%；明细 4,746 行反查 `chat_user` 未匹配数为 0。仅首次增加展示列时修改 chart 326；口径纠正只更新视图取值和数据集字段类型，保护审计最终 `clean=1`。脚本：`_deploy/add_chat_detail_user_id.py`、`_deploy/fix_chat_detail_zendesk_user_id.py`；纠正前备份：`/mnt/data/superset/backups/20260917_162009_fix_zendesk_user_id/`。
- 2026-09-17 已将生产看板 29「全球AI客服·运营分析」当前人工编辑状态固化为保护基线：完整保存布局、原生筛选器、CSS、54 张图的参数/数据源/描述等，并同时导出 Superset assets ZIP。基线指纹 `afaf3445c23f94a165d110eb6ad89ec3d202d9f073e4e5ea3db5fa380e9aa37e`，首次差异检查 `clean=1`。快照：`/mnt/data/superset/backups/manual_dashboard_baselines/cs-bi-overview/20260917_154937.json` 和 `20260917_154937_assets.zip`；工具：`_deploy/protect_manual_dashboard_edits.py`（`snapshot/diff/restore --confirm`）。项目规则要求后续修改前快照、仅补丁式改目标字段、修改后审计差异，禁止整板导入或重建覆盖人工配置。
- 2026-09-17 卡车电池 history 数据层完成单表化：对账近 1 天设备/时间键 518,647 个且双向缺失为 0；旧分钟宽表多出的 281 行为重复键残留。`bluetti.ads_tb_history` 现仅直读 `dwd_iot_data_raw_ops`，CTE 对 `inv`、`pack` 各 `PARSE_JSON` 一次，保留旧 19 个基础字段并合并 v2 扩展字段，共 59 列。生产 chart 370 已从数据集 105 并入 104，数据集 105 与视图 `ads_tb_history_v2` 已删除；QueryContext 同时查询旧曲线字段、明细字段及 NTC1/NTC10 成功。脚本：`_deploy/unify_tb_history_view.py`、`_deploy/finalize_tb_history_unification.py`；备份：`/mnt/data/superset/backups/history_unify_20260917_125414/`。
- 2026-09-17 共享视图 `bluetti.ads_tb_history_v2` 完成 JSON CTE 优化：由每个字段分别解析 `pack` 改为 CTE 中一次 `PARSE_JSON`、外层统一 `JSON_QUERY` 提取；全部输出逐值一致，设备号/时间谓词可下推，生产看板 31 chart 370 QueryContext 验证成功。脚本：`_deploy/optimize_history_v2_json_cte.py`（`apply/verify/revert`）；备份：`/mnt/data/superset/backups/history_v2_json_cte_20260917_122020/before.sql`。
- 2026-09-16 生产看板 31「卡车电池设备分析」chart 370「设备数据明细(按设备/时间调取)」将 `NTC1_NTC2`、`NTC3_NTC4`、`NTC5_NTC6`、`NTC7_NTC8`、`NTC9_NTC10` 全部替换为十进制 `NTC1` 至 `NTC10`。共享视图 `ads_tb_history_v2` 保留 5 个原组合字段并新增高/低字节拆分列；生产数据集 105 已刷新，开发 Superset 元数据按要求未同步。脚本：`_deploy/add_ntc_detail_columns.py`（`apply/verify/revert`）；完整拆分前备份：`/mnt/data/superset/backups/ntc_split_20260916_144042/before.json`。
- 2026-09-16 生产看板 29「体验与回访」新增 chart 374 `Chat回复超过120秒会话趋势`：默认按日同时展示严格 `resp_sec > 120` 的会话数及这些超时会话的加权平均回复时间。新增每小时异步刷新物化视图 `ads_cs_chat_response_timeout_daily`、生产数据集 106；图表接入「明细日期」「时间粒度」，其它筛选作用域跟随现有 Chat 首响趋势。脚本：`_deploy/add_chat_over_120s_trend.py`（apply/verify）；生产备份：`/mnt/data/superset/backups/20260916_155516_chat_over_120s_trend/before.json`；两段日期范围真实查询验证通过。
- 2026-09-16 生产看板 29「数据明细」chart 326 `Chat对话明细` 新增 `reply_duration_seconds`（显示名「回复耗时(秒)」）：按每轮用户提问到第一条实际 AI/business 回复计算，无实际回复为空；排除中/日文“用户结束会话”系统通知。新增逻辑视图 `dws_cs_chat_message_reply_detail` 和生产数据集 107，chart 326 已改指新数据集。脚本：`_deploy/add_chat_reply_duration_detail.py`（apply/verify）；最终修正前备份：`/mnt/data/superset/backups/20260916_163850_chat_reply_duration_detail/before.json`；验证通过（68,865 轮、62,577 轮有回复耗时）。
- 2026-09-16 生产看板 29「体验与回访」口径标识与日期联动修正：确认 6 张图均为 Chat 数据源，将标题统一改为 `Chat平均首响(秒)`、`Chat 10秒内首响率`、`Chat回访用户占比`、`Chat首响时延趋势(秒)`、`Chat新客vs回访趋势`、`Chat各站点首响明细`；左侧「明细日期」由仅覆盖图 293 扩展为覆盖全部 6 图。脚本 `_deploy/fix_experience_chat_scope.py` 支持 apply/verify/revert；生产备份 `/mnt/data/superset/backups/experience_chat_scope_20260916_142521.json`。两段不同日期范围真实查询均通过。
- 2026-09-11 生产看板 29「全球AI客服·运营分析」的「Chat在线对话」新增 3 图：`用户会话数(周期)`、`每会话消息数趋势(平均/最大)`、`平均每用户会话数趋势`。两张趋势图固定按自然月（`P1M`）展示；接入全局「时间范围」「站点」，排除时间粒度、标签分类、明细日期及周报专用筛选器。12:11 将 `用户会话数(周期)` 改为与 `用户消息数` 完全相同的 `big_number`、时间轴、默认日粒度、趋势展示和筛选作用域，避免“周期合计”和“最后时间桶”混比。部署脚本：`_deploy/add_chat_session_metrics.py`；修正脚本：`_deploy/fix_chat_session_kpi_period.py`；验证脚本：`_deploy/_probe_chat_session_metrics.py`。生产修正前备份位于 `/mnt/data/superset/backups/20260911_121119_chat_session_kpi_period/`。
- 2026-07-27 生产发布（两看板首次上线生产）+ 数据对象命名统一：见《卡车电池设备分析-数据对象清单.md》五节、《全球AI客服·运营分析_指标计算口径说明.md》两条 2026-07-27 附录。
- 2026-07-20 客服口径统一 + 生产同步：见《全球AI客服·运营分析_指标计算口径说明.md》2026-07-20 附录。
- SSO + 本地双登录、Casdoor 配置、Redis 服务端会话、权限下拉宽度修复：见 `_deploy/superset_config_dev_sso.py`、`login_dual.html`、`head_custom_extra.html`。

---

## 七、当前状态与待决事项（截至 2026-07-28）

### 两环境现状（开发与生产已对齐）

| 项 | 开发（192.168.41.122） | 生产（10.100.19.1） |
|---|---|---|
| 卡车电池设备分析 | 看板 id **32**，38 图，5 Tab | 看板 id **31**，39 图，5 Tab |
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
