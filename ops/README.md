# Superset 运维（ops）

本目录存放我们在 Apache Superset fork（`test-6.0-changes`）上的**运维脚本与文档**，与上游源码改动（GeoMaps 插件、首页重定向等）分开管理。

| 路径 | 内容 |
|---|---|
| `scripts/` | 授权、修复、看板样式、跳板工具等幂等运维脚本；使用说明见 `scripts/README.md` |
| `docs/` | 《Superset看板授权操作指南》日常授权；《Superset变更与生产同步操作手册》变更与踩坑 |

不入库：`superset_config.py`、一次性排查脚本（`_*.py`）、备份与大型数据文件。
