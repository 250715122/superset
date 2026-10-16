#!/bin/bash
# Daily refresh of bluetti.ads_sr_meta_knowledge: infer the missing StarRocks
# comments with an LLM and vectorise them for the 数据资产检索 entry of the
# 数据中台速览 dashboard.
#
# Runs on the Superset host because it is the only scheduled host with egress
# to the embedding API; the DolphinScheduler node (10.100.21.202) has none.
# Keys live in /mnt/data/superset/.meta_kb_env (640), never in this file.
#
# crontab: 47 3 * * * /mnt/data/superset/sync_sr_meta_knowledge.sh \
#            >> /mnt/data/superset/logs/sr_meta_knowledge.log 2>&1
set -euo pipefail

BASE_DIR=${BASE_DIR:-$(cd "$(dirname "$0")" && pwd)}
# shellcheck disable=SC1091
[ -f "$BASE_DIR/.meta_kb_env" ] && . "$BASE_DIR/.meta_kb_env"

export SUPERSET_CONFIG_PATH=${SUPERSET_CONFIG_PATH:-$BASE_DIR/superset_config.py}
export EMBED_BASE_URL=${EMBED_BASE_URL:-https://api.siliconflow.cn/v1}
export EMBED_MODEL=${EMBED_MODEL:-BAAI/bge-m3}
export EMBED_DIM=${EMBED_DIM:-1024}
export EMBED_API_KEY=${EMBED_API_KEY:?EMBED_API_KEY not set (expected in $BASE_DIR/.meta_kb_env)}
# The self-hosted OneAPI gateway returns 503 for every model, so inference
# shares the SiliconFlow endpoint and key with the embedding call.
export LLM_BASE_URL=${LLM_BASE_URL:-https://api.siliconflow.cn/v1}
export LLM_MODEL=${LLM_MODEL:-Pro/deepseek-ai/DeepSeek-V3}
export LLM_API_KEY=${LLM_API_KEY:?LLM_API_KEY not set (expected in $BASE_DIR/.meta_kb_env)}

LOCK=${LOCK:-/tmp/sync_sr_meta_knowledge.lock}
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "META_KB|SKIP_LOCKED|another run holds $LOCK"
  exit 1
fi

mkdir -p "$BASE_DIR/logs"
exec "$BASE_DIR/venv/bin/python" "$BASE_DIR/sync_sr_meta_knowledge.py" "${@:-apply}"
