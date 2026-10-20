# Superset 运维脚本说明

本目录存放 Superset BI 系统的运维脚本。所有脚本均：

- **幂等**：重复执行结果一致，已完成的步骤自动跳过并打印 `SKIP`
- **双环境自动识别**：`/opt/superset` 存在时为开发（192.168.41.122），否则为生产（10.100.19.1）
- **ASCII 安全输出**：中文用 `unicode_escape` 编码打印，适合 SSH 终端
- **不含敏感信息**：`superset_config.py`（含数据库密码）不入库

> 详细变更记录、原理说明、踩坑汇总：见 `../docs/Superset变更与生产同步操作手册.md`
> 日常授权操作（给用户开只读/编辑权限）：见 `../docs/Superset看板授权操作指南.md`

---

## 环境准备

```bash
# 开发机
ssh agi@192.168.41.122
cd /opt/superset

# 生产机（经跳板）
# Windows 本地用 jump_run.py / jump_put_fast.py 传文件执行
#   先设置跳板凭据：$env:JUMP_USER='<账号>'; $env:JUMP_PASSWORD='<密码>'
# 或 ssh 进跳板后 ssh 10.100.19.1，cd /mnt/data/superset
```

脚本运行方式：
```bash
./venv/bin/python <脚本名>.py [参数]
```

---

## 授权相关脚本（日常运维最常用）

### `authz_model.py` — 授权模型唯一真源

管理"只读基线"角色、每看板受众角色、观众数据授权的完整生命周期。

```bash
# 为新看板补建受众角色并挂进 RBAC（上线新看板后跑）
./venv/bin/python authz_model.py migrate

# 重新生成"只读基线"角色（权限漂移时修复）
./venv/bin/python authz_model.py baseline

# 查看当前授权状态（不修改）
./venv/bin/python authz_model.py migrate --dry-run
```

### `editor_group_setup.py` — 开通某看板的编辑权限（每看板一次性）

为指定看板创建编辑角色、挂进看板 RBAC、建立编辑组。运行后在 UI 页面往组里加人即可开通编辑权限。

```bash
# 用法：传入看板 id（URL 里的数字）
./venv/bin/python editor_group_setup.py <看板id>

# 示例：为 id=9 的 VOC 看板初始化编辑授权
./venv/bin/python editor_group_setup.py 9

# 预演（不写库）
./venv/bin/python editor_group_setup.py 9 --dry-run
```

**运行完后日常操作**：`Security ▸ List Groups` → 找「<看板名>编辑」组 → 加人。

> 前提：`patch_editor_ownership.py` 补丁已在两环境应用（一次性，已完成）。
> 若某环境配置被重置，需重跑该补丁并重启 Superset。

### `patch_editor_ownership.py` — 编辑授权页面化配置补丁（一次性）

重写 `raise_for_ownership`：持有挂在看板 RBAC 上的 `编辑·X` 角色 = 该看板及其图表的 Owner。使"加组即有编辑权"成为可能，无需逐人挂 Owner。

```bash
./venv/bin/python patch_editor_ownership.py
# 应用后需重启 Superset
sudo systemctl restart superset
```

**两环境已应用，正常情况不需要重跑。** 备份在 `superset_config.py.bak.editorown`。

### `grant_dashboard_editor.py` — 直接给单个用户开编辑权限

不建组，直接把三要素（能力+数据授权+Owner）一次性授给指定用户。适合临时授权场景。

```bash
./venv/bin/python grant_dashboard_editor.py <看板id> <用户id或用户名>
./venv/bin/python grant_dashboard_editor.py <看板id> <用户id> --revoke   # 收回
./venv/bin/python grant_dashboard_editor.py <看板id> <用户id> --dry-run  # 预演
```

### `authz_probe.py` — 授权模型端到端验证

以真实用户模拟 HTTP 请求，验证只读用户能看看板/不能改，改完授权后必跑。

```bash
./venv/bin/python authz_probe.py
```

---

## Tab 级权限（源码改造）

让同一块看板下的不同 Tab 只对持有指定角色的人可见。不是 Superset 原生能力，
需要给 venv 里的包打补丁并重新构建前端。原理、改动清单、回滚见
`../docs/Superset变更与生产同步操作手册.md` 第六节。

### `install_tab_access.sh` — 安装后端补丁

覆盖前先把原文件备份到 `<site-packages>/_tab_access_backup_<时间戳>/`，
逐个 `py_compile`，再试导入确认没有循环引用。**每次升级 Superset 后必须重装**。

```bash
bash install_tab_access.sh <venv 的 python> <site-packages/superset 目录> <暂存目录>
```

### `build_frontend_tabroles.sh` — 构建带配置界面的前端资产

在构建机 `gt@192.168.56.101:/opt/superset-build` 上执行，产物是 `static/assets`。

### `run_tab_access_http_check.sh` — 验收（改完必跑）

以管理员和一个没有该角色的账号分别真实登录，比对两边拿到的 Tab / 图表 /
数据集，并实际请求一次受限图表的数据，预期管理员通、该账号 403。
临时建一个管理员账号，跑完即删。

```bash
bash run_tab_access_http_check.sh <看板id> <账号>:<密码>
```

### `setup_tab_access_demo.py` — 搭一个可手工点验的演示场景

把某个 Tab 限定给一个一次性角色，并建一个**不持有**该角色的演示账号，
用于人工验收。`teardown` 按 setup 存下的副本原样还原 `json_metadata`。

```bash
./venv/bin/python setup_tab_access_demo.py setup <看板id> [tab id]
./venv/bin/python setup_tab_access_demo.py teardown <看板id>
```

### 回归脚本

| 脚本 | 覆盖 |
|---|---|
| `test_tab_access.py <看板id>` | 全链路：写入、四个读取出口、`raise_for_access`、下钻 |
| `test_tab_access_edges.py` | 24 条边界：嵌套 Tab、空容器塌缩、一图多处、筛选器作用域 |
| `test_tab_access_portability.py <看板id>` | 导出导入往返后限制仍在；受限用户拿不到隐藏内容 |

---

## 数据保护脚本

### `fix_ds54_guard.py` — 数据集裸查防护

为大表数据集（71亿行）加 Jinja 护栏：无时间筛选时返回空结果，防止 StarRocks OOM。

```bash
./venv/bin/python fix_ds54_guard.py apply   # 应用护栏
./venv/bin/python fix_ds54_guard.py revert  # 回滚
./venv/bin/python fix_ds54_guard.py verify  # 验证
```

---

## 系统修复脚本

### `fix_permalink_salt.py` — 修复分享链接 500 错误（已执行）

### `fix_public_role.py` — 关闭 Public 角色权限旁路（已执行）

### `fix_selfservice_perms.py` — 补全自定义角色的自助服务权限（已执行）

### `enable_password_views.py` — 注册本地密码修改页面（已执行）

### `set_default_locale_zh.py` — 设置默认语言为中文（已执行）

### `heal_stale_locale.py` — 修复老用户 session 语言未更新（已执行）

---

## 内容脚本（图表/看板样式）

| 脚本 | 用途 |
|---|---|
| `apply_chart_desc.py` | 给图表写口径说明（悬停 ⓘ 显示） |
| `apply_tab_icons.py` | 给看板 Tab 名称加 emoji 图标 |
| `pb_show_value.py` | 柱状图开启数值显示 |
| `pb_pct_unify.py` | SOC/SOH 卡片统一百分比格式 |
| `pb_fix_timefilter.py` | 修复图表时间筛选器接线 |
| `fix_detail_time_filter.py [apply\|verify\|revert]` | 卡车电池看板：左侧「时间范围」作用域放开到全部图表、删掉重复的「时间范围(数据详情)」、明细表行数上限 5000→50000 并追加"先选设备号"提示。支持 `--dry-run`，改前自动快照到 `backups/` |
| `fix_detail_device_filter.py [apply\|verify\|revert]` | 卡车电池看板：修复被 UI 存坏的「设备号(数据详情)」——取值指回小快照表、钉死默认设备（`--sn=` 换设备，默认 `B52525000081783`）、设为必填。支持 `--dry-run` / `--dash=<id>`，改前自动快照到 `backups/` |
| `_check_filter_scope.py [看板id\|标题片段]` | 只读巡检筛选器作用域，排查"某图表不受左侧筛选限制" |
| `_dbg_devfilter.py [看板id]` | 只读 dump 看板筛选器配置原文与各图表数据集/行数上限，排查配置被写坏 |
| `_probe_detail_tab_cost.py [设备SN]` | 只读：数据详情 Tab 的查询在"单设备 vs 全设备"下各要多久、扫多少行 |
| `_verify_detail_e2e.py` | 只读端到端验证：明细表选定设备+时间范围后，页面与 CSV 导出的时间跨度 |

---

## 数据中台速览（看板 38）

| 脚本 | 用途 |
|---|---|
| `build_run_analysis_tab.py` | （历史）建「运行分析」Tab：数据集 190–195、图表 644–653、Tab 内 5 个筛选器。**不要再跑**：该 Tab 已手工拆成「运行状态」+「性能分析」，重跑会把布局推回单 Tab |
| `apply_run_analysis_followups.py` | 定点补丁：平均耗时改毫秒、「用户清单」资源组列改走配置绑定 |
| `apply_run_status_rework.py` | 双 Tab 返工：筛选器跨 Tab 重新作用域、审计明细、查询平均耗时只算 SELECT、TOP 榜按语句前 200 字符聚合、导入任务并入 routine load / pipe。改前自动快照 |
| `apply_top_add_duration.py` | 给 CPU / 内存 TOP 榜补「最大耗时」列。只改 `metrics`，其余 params 原样保留（这两张图有手工调过的显示设置） |
| `sync_sr_node_hw.py` / `.sh` | 每日采集集群硬件：抓 6 个节点 `:9100` 的 node_exporter，关联 `SHOW FRONTENDS` / `SHOW COMPUTE NODES`，落 `ads_sr_node_hw` / `ads_sr_node_disk`。cron `17 3 * * *` |
| `add_cluster_hardware.py` | 把「节点硬件」「磁盘与挂载」两张图插进集群概览的集群名片下方。幂等，不动 `json_metadata` |
| `sync_sr_user_privileges.sh` | 快照全部用户的 StarRocks 权限（含角色继承展开）到 `bluetti.ads_sr_global_user_privileges`，保留 3 份。装在 10.100.21.202 的 `/data/bi-sync/`，由 DolphinScheduler 工作流 `ads_sr_global_user_privileges` 每天 03:50 调起；凭据读同目录 `.sr_env` |
| `fix_user_privileges_chart.py [--apply]` | 把 chart 557「用户权限」从 `SHOW GRANTS` 改为读上面的快照。不带参数是 dry run，会列出将改哪些 params 键、哪些保持不动 |
| `rename_cluster_hosts.sh [plan\|apply\|verify\|rollback]` | 给 6 台 StarRocks 节点改主机名，不重启机器也不重启服务。在 Superset 机上跑，逐台分发 `rename_cluster_hosts_node.sh`。会一并修 `/etc/hosts`（保留 `flink-jm*` 别名）并钉住 cloud-init，备份在各机 `/var/backups/hostname-rename/` |
| `sync_sr_rg_bindings.py` / `.sh` | 把 `SHOW RESOURCE GROUPS ALL` 的 classifier 解析落 `bluetti.ads_sr_global_rg_bindings`（`SHOW` 不能 join，只能先落表）。生产 crontab 每小时第 23 分；写新 `snapshot_ts` 再删旧的，滚动留 3 份，读侧取 `MAX(snapshot_ts)` |

---

## 数据资产检索（看板 38 ·「数据资产」Tab）

自然语言 / 表名片段检索 StarRocks 元数据，命中后可展开字段、就地改说明并回写。
以 FAB 视图注册在 `/meta-search/`（而不是裸 Blueprint），这样会生成 `MetaSearch`
权限，能在角色里勾选；看板里用一行满宽 MARKDOWN 同源 iframe 嵌入。

| 脚本 | 用途 |
|---|---|
| `meta_search.py` | 检索页后端。`register(app)` 挂 `/meta-search/` 与 `api/search`、`api/columns`、`api/confirm`、`api/stats`，并幂等补齐五个 `can_*` 权限。`api/search` 带 `mode=table\|column` 两种粒度（同一个权限）；关键词按词计分，整串命中优先。向量检索不可用时自动回落关键词检索，中文按二字切分 |
| `meta_search.html` | 检索页前端（放 `custom_templates/`）。「按表 / 按字段」切换、实时检索、库/分层/来源筛选、字段展开、就地改说明、清空按钮、`/` 聚焦与方向键，随 Superset 主题切换明暗与紧凑模式 |
| `patch_config_meta_search.py` | 把 `meta_search.register(app)` 写进测试机 `superset_config.py` 的 `FLASK_APP_MUTATOR`（函数形态）。幂等，带备份 |
| `patch_config_meta_search_prod.py` | 同上，生产形态：`FLASK_APP_MUTATOR` 是 `CustomFlaskAppMutator` 类实例，钩子要写进 `__call__` 且缩进不同 |
| `add_meta_search_tab_row.py` | 在看板 38「数据资产」Tab 最上方插一行 iframe。只动 `position_json`，新行的 `parents` 从同 Tab 原首行复制。幂等 |
| `sync_sr_meta_knowledge.py` / `.sh` | 扫全库元数据，缺注释的用 LLM 补、再向量化，落 `bluetti.ads_sr_meta_knowledge`。`plan` 只报计划、`apply` 实写。生产 crontab `47 3 * * *`，密钥读同目录 `.meta_kb_env`（640，不入库） |
| `verify_meta_search.py [base_url]` | 17 项验收：权限生成、未登录拦截、CSP nonce、向量与回落检索、按字段检索、多词且带冒号的查询、字段读取、注释回写、注入字符串 |
| `eval_meta_search.py --tag <名字>` | 固定标注评测集（29 条查询）量化检索质量，自己拼 SQL 不走接口，改代码前后同一把尺子。`--scoring max\|combo`、`--keyword single\|tokens`、`--col-weight` 可用来扫参和做消融。明细落 `backups/eval_*.json` |

**两个容易踩的点**（都已在脚本里处理）：

- 写入语句一律走 `conn.execute(text(...))` 并把连接设成 `compiled_cache=None`。
  换成 `exec_driver_sql` 会让 pymysql 把注释里的字面 `%` 当成参数占位符
  （`unsupported format character`，整表跳过）；而不关编译缓存，每批几 MB 的
  向量 SQL 会一直攒在缓存里，进程最终被 OOM kill。
- `verify_meta_search.py` 走 127.0.0.1 的 http，而生产 `SESSION_COOKIE_SECURE=True`，
  cookiejar 不会回传 Secure cookie。脚本用 `LoopbackSession` 在每次
  `prepare_request` 时清掉 `secure`，并**手动跟重定向**——requests 自己的重定向
  循环不经过 `prepare_request`，登录后新发的 cookie 会漏掉这步。

---

## 看板保护

### `protect_manual_dashboard_edits.py` — 人工编辑保护

改生产看板前后各跑一次：`snapshot` 落一份带时间戳的元数据，`diff` 列出实际变动的字段，用来确认没有误伤用户在 UI 里手工调过的图表配置。

```bash
./venv/bin/python protect_manual_dashboard_edits.py snapshot
./venv/bin/python protect_manual_dashboard_edits.py diff
```

---

## 跳板工具

| 脚本 | 用途 |
|---|---|
| `jump_put_fast.py <本地文件> <生产路径>` | 经跳板传文件到生产，带 sha256 校验 |
| `jump_run.py <命令文件> <超时秒>` | 经跳板在生产执行命令（命令文件用单引号） |

---

## 自定义模板

`head_custom_extra.html` — 注入到 Superset `<head>`，包含：
- 权限下拉框宽度修复（CSS）
- 导航栏"修改密码"入口（JS）
- 旧浏览器 ES2025 Set 方法 polyfill（JS，修复切 Tab 报错）

部署：复制到服务器 `custom_templates/` 目录，重启 Superset 生效。
