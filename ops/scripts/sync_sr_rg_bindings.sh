#!/bin/bash
# Hourly refresh of bluetti.ads_sr_global_rg_bindings (resource group classifiers).
# Feeds the 资源组(配置) column of the 用户清单 chart.
set -euo pipefail
export SUPERSET_CONFIG_PATH=/mnt/data/superset/superset_config.py
mkdir -p /mnt/data/superset/logs
/mnt/data/superset/venv/bin/python /mnt/data/superset/sync_sr_rg_bindings.py
