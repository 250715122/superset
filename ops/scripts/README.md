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
