#!/bin/bash
# Runs ON one cluster node; driven by rename_cluster_hosts.sh.
#   usage: rename_cluster_hosts_node.sh <plan|apply|verify|rollback>
#
# The new name is derived from the current one via MAP, so the script is safe to
# run anywhere and is idempotent: a host that is already renamed falls through.
# apply also pins cloud-init, which would otherwise restore the ECS metadata
# hostname on the next reboot (preserve_hostname defaults to false here).
set -u
MODE="${1:-plan}"
BK=/var/backups/hostname-rename
DROPIN=/etc/cloud/cloud.cfg.d/99-preserve-hostname.cfg

MAP="HK-IaaS-AGI-Flink-01|HK-IaaS-AGI-Starrocks-admin-01
HK-IaaS-AGI-Flink-02|HK-IaaS-AGI-Starrocks-admin-02
HK-IaaS-AGI-Flink-03|HK-IaaS-AGI-Starrocks-admin-03
HK-SaaS-AGI-StarRocks-01|HK-IaaS-AGI-Starrocks-CN-01
HK-SaaS-AGI-StarRocks-02|HK-IaaS-AGI-Starrocks-CN-02
HK-SaaS-AGI-StarRocks-03|HK-IaaS-AGI-Starrocks-CN-03"

CUR=$(hostname)
NEW=""
while IFS='|' read -r o n; do
  [ -z "${o:-}" ] && continue
  [ "$CUR" = "$o" ] && NEW="$n"
done <<EOF
$MAP
EOF

sed_args=()
while IFS='|' read -r o n; do
  [ -z "${o:-}" ] && continue
  sed_args+=(-e "s/\\b${o}\\b/${n}/g")
done <<EOF
$MAP
EOF

services() {
  systemctl list-units --type=service --state=running --no-pager 2>/dev/null \
    | awk '{print $1}' | grep -E 'starrocks|flink|zookeeper|dolphin|node_exporter' \
    | tr '\n' ' '
}

case "$MODE" in
plan)
  echo "current=$CUR"
  if [ -z "$NEW" ]; then
    echo "  target=<already renamed or unknown host, nothing to do>"
  else
    echo "  target=$NEW"
  fi
  echo "  etc_hosts_lines_to_change:"
  grep -nE "$(echo "$MAP" | cut -d'|' -f1 | paste -sd'|')" /etc/hosts 2>/dev/null \
    | sed 's/^/    /' || echo "    (none)"
  echo "  cloud_init_preserve_hostname=$(grep -rhE '^[[:space:]]*preserve_hostname' \
        /etc/cloud/cloud.cfg /etc/cloud/cloud.cfg.d/*.cfg 2>/dev/null | tr '\n' ';')"
  echo "  dropin_exists=$([ -f "$DROPIN" ] && echo yes || echo no)"
  echo "  running=$(services)"
  ;;

apply)
  if [ -z "$NEW" ]; then echo "SKIP|$CUR|not in map (already renamed?)"; exit 0; fi
  sudo mkdir -p "$BK"
  if [ ! -f "$BK/hostname.orig" ]; then
    echo "$CUR" | sudo tee "$BK/hostname.orig" >/dev/null
    sudo cp -a /etc/hosts "$BK/hosts.orig"
    echo "  backup -> $BK (hostname.orig, hosts.orig)"
  else
    echo "  backup already present at $BK"
  fi

  sudo hostnamectl set-hostname "$NEW"
  echo "  hostnamectl -> $(hostname)"

  if grep -qE "$(echo "$MAP" | cut -d'|' -f1 | paste -sd'|')" /etc/hosts 2>/dev/null; then
    sudo sed -i "${sed_args[@]}" /etc/hosts
    echo "  /etc/hosts rewritten"
  else
    echo "  /etc/hosts has no stale names"
  fi

  # cloud-init would otherwise reset the hostname from ECS metadata on reboot
  printf '# Keep the manually set hostname across reboots.\npreserve_hostname: true\n' \
    | sudo tee "$DROPIN" >/dev/null
  echo "  wrote $DROPIN"
  ;;

verify)
  echo "hostname=$(hostname)"
  echo "  etc_hostname=$(cat /etc/hostname)"
  echo "  hostname_-f=$(hostname -f 2>&1)"
  echo "  resolves=$(getent hosts "$(hostname)" | tr '\n' ';')"
  echo "  uname_n=$(uname -n)"
  echo "  hosts_self=$(grep -n "$(hostname)" /etc/hosts 2>/dev/null | tr '\n' ';')"
  echo "  stale_names_left=$(grep -cE "$(echo "$MAP" | cut -d'|' -f1 | paste -sd'|')" /etc/hosts 2>/dev/null)"
  echo "  preserve_hostname=$(grep -rhE '^[[:space:]]*preserve_hostname' \
        /etc/cloud/cloud.cfg /etc/cloud/cloud.cfg.d/*.cfg 2>/dev/null | tr '\n' ';')"
  echo "  running=$(services)"
  echo "  failed_units=$(systemctl list-units --state=failed --no-pager 2>/dev/null | awk 'NR>1 && /\.service/ {print $2}' | tr '\n' ' ')"
  echo "  exporter_says=$(curl -s --max-time 5 http://127.0.0.1:9100/metrics 2>/dev/null | grep -o 'nodename=\"[^\"]*\"' | head -1)"
  ;;

rollback)
  if [ ! -f "$BK/hostname.orig" ]; then echo "NO_BACKUP|$CUR"; exit 1; fi
  OLD=$(cat "$BK/hostname.orig")
  sudo hostnamectl set-hostname "$OLD"
  sudo cp -a "$BK/hosts.orig" /etc/hosts
  sudo rm -f "$DROPIN"
  echo "ROLLED_BACK|now=$(hostname)"
  ;;
esac
