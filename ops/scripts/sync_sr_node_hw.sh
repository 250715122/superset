#!/bin/bash
# Daily refresh of the cluster hardware inventory
# (bluetti.ads_sr_node_hw / ads_sr_node_disk).
# Specs come from node_exporter on :9100 of every FE / CN node.
set -euo pipefail
export SUPERSET_CONFIG_PATH=/mnt/data/superset/superset_config.py
mkdir -p /mnt/data/superset/logs
/mnt/data/superset/venv/bin/python /mnt/data/superset/sync_sr_node_hw.py
