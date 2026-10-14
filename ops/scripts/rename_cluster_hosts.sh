#!/bin/bash
# Rename the six StarRocks cluster nodes without rebooting them.
#
# Run from the Superset box (10.100.19.1), which has key-based SSH and
# passwordless sudo on all six nodes.  The per-node work lives in
# rename_cluster_hosts_node.sh; this just fans it out.
#
#   ./rename_cluster_hosts.sh plan      # show what would change
#   ./rename_cluster_hosts.sh apply     # rename + fix /etc/hosts + pin cloud-init
#   ./rename_cluster_hosts.sh verify    # confirm, incl. that nothing restarted
#   ./rename_cluster_hosts.sh rollback  # restore from /var/backups/hostname-rename
#
# Nothing needs restarting: no service here identifies itself by hostname.
# StarRocks runs with enable_fqdn_mode off and registers nodes by IP, Flink
# uses the flink-jm1/2/3 and flink-self aliases in /etc/hosts, and ZooKeeper's
# zoo.cfg points at localhost.
MODE="${1:-plan}"
NODE_SCRIPT="$(dirname "$0")/rename_cluster_hosts_node.sh"
NODES="10.100.11.201 10.100.21.201 10.100.21.202 10.100.19.18 10.100.15.18 10.100.25.18"
SSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8"

case "$MODE" in
  plan|apply|verify|rollback) ;;
  *) echo "usage: $0 <plan|apply|verify|rollback>"; exit 2 ;;
esac

for h in $NODES; do
  echo "########## $h ##########"
  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
      "$NODE_SCRIPT" "cloudapp@$h:/tmp/rename_cluster_hosts_node.sh" 2>&1
  timeout 90 $SSH "cloudapp@$h" \
      "bash /tmp/rename_cluster_hosts_node.sh $MODE" 2>&1
done
echo "ALL_DONE|$MODE"
