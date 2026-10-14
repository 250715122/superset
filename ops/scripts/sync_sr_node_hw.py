# -*- coding: utf-8 -*-
"""Refresh the StarRocks cluster hardware inventory.

StarRocks itself only reports CpuCores / MemLimit for CN nodes and nothing at
all for FE, so the machine specs come from the node_exporter already running on
every node (:9100). The FE / CN identity comes from SHOW FRONTENDS and
SHOW COMPUTE NODES, which cannot be joined in SQL and so are resolved here.

Writes a new snapshot_ts and keeps the three most recent snapshots, so readers
never observe an empty table. Run daily from cron.
"""
import os
import re
import urllib.request
from datetime import datetime

CONF = "/mnt/data/superset/superset_config.py"
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from sqlalchemy import text  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()

TABLE_HW = "bluetti.ads_sr_node_hw"
TABLE_DISK = "bluetti.ads_sr_node_disk"
KEEP_SNAPSHOTS = 3
EXPORTER_PORT = 9100
TIMEOUT = 10
GB = 1024.0 ** 3

# pseudo filesystems carry no capacity worth reporting
REAL_FSTYPES = ("ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat")

METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)$")
LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')

DDL_HW = """
CREATE TABLE IF NOT EXISTS %s (
  snapshot_ts VARCHAR(32), role VARCHAR(16), node_ip VARCHAR(64),
  hostname VARCHAR(128), sr_role VARCHAR(32), sr_alive VARCHAR(16),
  sr_version VARCHAR(64), sr_start_time VARCHAR(32), warehouse VARCHAR(64),
  vendor VARCHAR(64), product VARCHAR(96), os_name VARCHAR(128),
  kernel VARCHAR(64), arch VARCHAR(32),
  cpu_cores INT, mem_total_gb DECIMAL(12,1), swap_total_gb DECIMAL(12,1),
  sr_mem_limit VARCHAR(32), disk_n INT,
  disk_total_gb DECIMAL(12,1), disk_avail_gb DECIMAL(12,1),
  nic VARCHAR(32), nic_mac VARCHAR(32), nic_mtu INT,
  uptime_days DECIMAL(12,1), exporter_ver VARCHAR(32),
  collect_status VARCHAR(256)
) DISTRIBUTED BY HASH(node_ip) BUCKETS 1 PROPERTIES("replication_num"="1")
""" % TABLE_HW

DDL_DISK = """
CREATE TABLE IF NOT EXISTS %s (
  snapshot_ts VARCHAR(32), role VARCHAR(16), node_ip VARCHAR(64),
  hostname VARCHAR(128), mountpoint VARCHAR(128), device VARCHAR(128),
  fstype VARCHAR(32), size_gb DECIMAL(12,1), avail_gb DECIMAL(12,1),
  used_pct DECIMAL(6,1), disk_model VARCHAR(128)
) DISTRIBUTED BY HASH(node_ip) BUCKETS 1 PROPERTIES("replication_num"="1")
""" % TABLE_DISK


def clip(v, n):
    return None if v is None else str(v)[:n]


def gb(v):
    return None if v is None else round(float(v) / GB, 1)


def parse_metrics(body):
    """Prometheus text format -> {name: [(labels, value), ...]}."""
    out = {}
    for line in body.splitlines():
        if not line or line[0] == "#":
            continue
        m = METRIC_RE.match(line)
        if not m:
            continue
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        labels = dict(LABEL_RE.findall(m.group(2) or ""))
        out.setdefault(m.group(1), []).append((labels, value))
    return out


def labels_of(metrics, name):
    rows = metrics.get(name) or []
    return rows[0][0] if rows else {}


def value_of(metrics, name, default=None):
    rows = metrics.get(name) or []
    return rows[0][1] if rows else default


def base_device(dev):
    """Mount device -> whole disk, e.g. /dev/nvme0n1p3 -> nvme0n1, /dev/sda1 -> sda.

    NVMe namespaces already end in a digit (nvme0n1), so only a trailing pNN
    may be stripped there.
    """
    name = str(dev or "").rsplit("/", 1)[-1]
    pattern = r"p\d+$" if name.startswith("nvme") else r"\d+$"
    return re.sub(pattern, "", name) or name


def primary_nic(metrics):
    """The non-loopback interface that is up, preferring the busiest one."""
    best = None
    for labels, _ in metrics.get("node_network_info") or []:
        dev = labels.get("device") or ""
        if dev == "lo" or dev.startswith(("veth", "docker", "br-", "virbr")):
            continue
        if labels.get("operstate") == "up" and best is None:
            best = labels
    return best or {}


def scrape(ip):
    url = "http://%s:%s/metrics" % (ip, EXPORTER_PORT)
    body = urllib.request.urlopen(url, timeout=TIMEOUT).read().decode(
        "utf-8", "replace")
    return parse_metrics(body)


def host_facts(metrics):
    uname = labels_of(metrics, "node_uname_info")
    osinfo = labels_of(metrics, "node_os_info")
    dmi = labels_of(metrics, "node_dmi_info")
    nic = primary_nic(metrics)
    nic_dev = nic.get("device")

    cores = len({lb.get("cpu") for lb, _ in
                 metrics.get("node_cpu_seconds_total") or [] if lb.get("cpu")})
    mtu = None
    for lb, v in metrics.get("node_network_mtu_bytes") or []:
        if lb.get("device") == nic_dev:
            mtu = int(v)
            break
    boot = value_of(metrics, "node_boot_time_seconds")
    now_s = value_of(metrics, "node_time_seconds")
    uptime = round((now_s - boot) / 86400.0, 1) if boot and now_s else None

    return {
        "hostname": uname.get("nodename"),
        "kernel": uname.get("release"),
        "arch": uname.get("machine"),
        "os_name": osinfo.get("pretty_name"),
        "vendor": dmi.get("chassis_vendor") or dmi.get("bios_vendor"),
        "product": dmi.get("product_name"),
        "cpu_cores": cores or None,
        "mem_total_gb": gb(value_of(metrics, "node_memory_MemTotal_bytes")),
        "swap_total_gb": gb(value_of(metrics, "node_memory_SwapTotal_bytes")),
        "nic": nic_dev,
        "nic_mac": nic.get("address"),
        "nic_mtu": mtu,
        "uptime_days": uptime,
        "exporter_ver": labels_of(
            metrics, "node_exporter_build_info").get("version"),
    }


def filesystems(metrics):
    """Real mounts only, joined to the physical disk model."""
    models = {}
    for labels, _ in metrics.get("node_disk_info") or []:
        if labels.get("device"):
            models[labels["device"]] = labels.get("model")

    avail = {}
    for labels, v in metrics.get("node_filesystem_avail_bytes") or []:
        avail[labels.get("mountpoint")] = v

    out = []
    for labels, size in metrics.get("node_filesystem_size_bytes") or []:
        if labels.get("fstype") not in REAL_FSTYPES or not size:
            continue
        mount = labels.get("mountpoint")
        free = avail.get(mount)
        out.append({
            "mountpoint": mount,
            "device": labels.get("device"),
            "fstype": labels.get("fstype"),
            "size_gb": gb(size),
            "avail_gb": gb(free),
            "used_pct": (round((size - free) * 100.0 / size, 1)
                         if free is not None else None),
            "disk_model": models.get(base_device(labels.get("device"))),
        })
    out.sort(key=lambda r: r["mountpoint"] or "")
    return out


def read_nodes(conn):
    """FE / CN identity from the cluster itself."""
    nodes = []
    res = conn.execute(text("SHOW FRONTENDS"))
    cols = list(res.keys())
    for row in res.fetchall():
        d = dict(zip(cols, row))
        nodes.append({
            "role": "FE", "node_ip": d.get("IP"),
            "sr_role": d.get("Role"), "sr_alive": d.get("Alive"),
            "sr_version": d.get("Version"), "sr_start_time": d.get("StartTime"),
            "warehouse": None, "sr_mem_limit": None,
        })
    res = conn.execute(text("SHOW COMPUTE NODES"))
    cols = list(res.keys())
    for row in res.fetchall():
        d = dict(zip(cols, row))
        nodes.append({
            "role": "CN", "node_ip": d.get("IP"),
            "sr_role": None, "sr_alive": d.get("Alive"),
            "sr_version": d.get("Version"),
            "sr_start_time": d.get("LastStartTime"),
            "warehouse": d.get("WarehouseName"),
            "sr_mem_limit": d.get("MemLimit"),
        })
    return nodes


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with app.app_context():
        from superset import db
        from superset.models.core import Database

        database = db.session.get(Database, 12)  # agi: reads SHOW, writes bluetti
        assert database, "database 12 missing"

        with database.get_sqla_engine() as eng, eng.connect() as conn:
            nodes = read_nodes(conn)
            print("NODES|%s|fe=%s|cn=%s" % (
                now,
                sum(1 for n in nodes if n["role"] == "FE"),
                sum(1 for n in nodes if n["role"] == "CN")))

            conn.execute(text(DDL_HW))
            conn.execute(text(DDL_DISK))

            disk_n = 0
            for node in nodes:
                ip = node["node_ip"]
                facts, mounts, status = {}, [], "OK"
                try:
                    metrics = scrape(ip)
                    facts = host_facts(metrics)
                    mounts = filesystems(metrics)
                except Exception as exc:
                    status = "exporter unreachable: %s" % str(exc)[:180]
                    print("SCRAPE_FAIL|%s|%s" % (ip, status))

                total = sum(m["size_gb"] or 0 for m in mounts)
                free = sum(m["avail_gb"] or 0 for m in mounts)
                row = {
                    "ts": now, "role": node["role"], "ip": clip(ip, 60),
                    "host": clip(facts.get("hostname"), 120),
                    "srrole": clip(node["sr_role"], 32),
                    "alive": clip(node["sr_alive"], 16),
                    "ver": clip(node["sr_version"], 60),
                    "start": clip(node["sr_start_time"], 32),
                    "wh": clip(node["warehouse"], 60),
                    "vendor": clip(facts.get("vendor"), 60),
                    "product": clip(facts.get("product"), 90),
                    "os": clip(facts.get("os_name"), 120),
                    "kernel": clip(facts.get("kernel"), 60),
                    "arch": clip(facts.get("arch"), 32),
                    "cores": facts.get("cpu_cores"),
                    "mem": facts.get("mem_total_gb"),
                    "swap": facts.get("swap_total_gb"),
                    "memlimit": clip(node["sr_mem_limit"], 32),
                    "diskn": len(mounts) or None,
                    "disktot": round(total, 1) if mounts else None,
                    "diskfree": round(free, 1) if mounts else None,
                    "nic": clip(facts.get("nic"), 32),
                    "mac": clip(facts.get("nic_mac"), 32),
                    "mtu": facts.get("nic_mtu"),
                    "up": facts.get("uptime_days"),
                    "exp": clip(facts.get("exporter_ver"), 32),
                    "status": clip(status, 250),
                }
                conn.execute(text("""
                    INSERT INTO %s
                    (snapshot_ts, role, node_ip, hostname, sr_role, sr_alive,
                     sr_version, sr_start_time, warehouse, vendor, product,
                     os_name, kernel, arch, cpu_cores, mem_total_gb,
                     swap_total_gb, sr_mem_limit, disk_n, disk_total_gb,
                     disk_avail_gb, nic, nic_mac, nic_mtu, uptime_days,
                     exporter_ver, collect_status)
                    VALUES (:ts,:role,:ip,:host,:srrole,:alive,:ver,:start,:wh,
                            :vendor,:product,:os,:kernel,:arch,:cores,:mem,
                            :swap,:memlimit,:diskn,:disktot,:diskfree,:nic,
                            :mac,:mtu,:up,:exp,:status)
                """ % TABLE_HW), row)

                for m in mounts:
                    conn.execute(text("""
                        INSERT INTO %s
                        (snapshot_ts, role, node_ip, hostname, mountpoint,
                         device, fstype, size_gb, avail_gb, used_pct,
                         disk_model)
                        VALUES (:ts,:role,:ip,:host,:mp,:dev,:fs,:sz,:av,:up,:md)
                    """ % TABLE_DISK), {
                        "ts": now, "role": node["role"], "ip": clip(ip, 60),
                        "host": clip(facts.get("hostname"), 120),
                        "mp": clip(m["mountpoint"], 120),
                        "dev": clip(m["device"], 120),
                        "fs": clip(m["fstype"], 32),
                        "sz": m["size_gb"], "av": m["avail_gb"],
                        "up": m["used_pct"],
                        "md": clip(m["disk_model"], 120),
                    })
                    disk_n += 1

                print("NODE|%s|%s|%s|cores=%s|mem=%sGB|disks=%s|%s" % (
                    node["role"], ip, facts.get("hostname"),
                    facts.get("cpu_cores"), facts.get("mem_total_gb"),
                    len(mounts), status))

            for table in (TABLE_HW, TABLE_DISK):
                keep = [r[0] for r in conn.execute(text(
                    "SELECT DISTINCT snapshot_ts FROM %s "
                    "ORDER BY snapshot_ts DESC LIMIT %s"
                    % (table, KEEP_SNAPSHOTS)
                )).fetchall()]
                if keep:
                    conn.execute(text(
                        "DELETE FROM %s WHERE snapshot_ts < :oldest" % table
                    ), {"oldest": min(keep)})
                print("PRUNE|%s|kept=%s" % (table, len(keep)))

            ok = conn.execute(text(
                "SELECT COUNT(*) FROM %s WHERE snapshot_ts = :ts "
                "AND collect_status = 'OK'" % TABLE_HW
            ), {"ts": now}).scalar()
            print("OK|snapshot=%s|nodes_ok=%s/%s|disks=%s"
                  % (now, ok, len(nodes), disk_n))


if __name__ == "__main__":
    main()
