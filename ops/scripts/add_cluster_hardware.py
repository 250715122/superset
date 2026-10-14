# -*- coding: utf-8 -*-
"""Put the cluster hardware inventory on the 集群概览 tab of dashboard 38.

Adds two datasets and two charts and splices four rows into position_json
directly below 集群名片. Every pre-existing node is left byte-identical, and
json_metadata is not touched at all: all native filters are scoped to other
tabs, so the new charts fall outside them automatically.

Idempotent.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/mnt/data/superset/superset_config.py")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()

BACKUP_DIR = "/mnt/data/superset/backups"
SLUG = "dp-sr-global"
TAB = "TAB-e3f27f99d2"          # 集群概览
ANCHOR_ROW = "ROW-d571b2d199"   # 集群名片, we splice in right after it
SCHEMA = "bluetti"

SECTION_CSS = (
    '<div style="font:600 13px/1.2 system-ui,sans-serif;color:#334155;'
    'letter-spacing:.02em;padding:4px 2px 0;">%s</div>'
    '<div style="height:1px;background:linear-gradient(90deg,#cbd5e1,'
    'transparent);margin-top:6px;"></div>'
)

HW_SQL = """SELECT role, node_ip, hostname, sr_role, sr_alive, sr_version,
       sr_start_time, warehouse, vendor, product, os_name, kernel, arch,
       cpu_cores, mem_total_gb, swap_total_gb, sr_mem_limit, disk_n,
       disk_total_gb, disk_avail_gb, nic, nic_mac, nic_mtu, uptime_days,
       exporter_ver, collect_status, snapshot_ts
FROM bluetti.ads_sr_node_hw
WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM bluetti.ads_sr_node_hw)"""

DISK_SQL = """SELECT role, node_ip, hostname, mountpoint, device, fstype,
       size_gb, avail_gb, used_pct, disk_model, snapshot_ts
FROM bluetti.ads_sr_node_disk
WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM bluetti.ads_sr_node_disk)"""

INT, DEC, STR = "INT", "DECIMAL", "VARCHAR"

HW_COLS = [
    ("role", "角色", STR), ("hostname", "主机名", STR), ("node_ip", "IP", STR),
    ("sr_role", "FE角色", STR), ("sr_alive", "存活", STR),
    ("sr_version", "StarRocks版本", STR), ("sr_start_time", "启动时间", STR),
    ("warehouse", "Warehouse", STR), ("vendor", "云厂商", STR),
    ("product", "机型", STR), ("os_name", "操作系统", STR),
    ("kernel", "内核", STR), ("arch", "架构", STR),
    ("cpu_cores", "CPU核数", INT), ("mem_total_gb", "内存(GB)", DEC),
    ("swap_total_gb", "Swap(GB)", DEC), ("sr_mem_limit", "SR内存上限", STR),
    ("disk_n", "文件系统数", INT), ("disk_total_gb", "磁盘总量(GB)", DEC),
    ("disk_avail_gb", "磁盘可用(GB)", DEC), ("nic", "网卡", STR),
    ("nic_mac", "MAC", STR), ("nic_mtu", "MTU", INT),
    ("uptime_days", "已运行(天)", DEC), ("exporter_ver", "exporter版本", STR),
    ("collect_status", "采集状态", STR), ("snapshot_ts", "采集时间", STR),
]

DISK_COLS = [
    ("role", "角色", STR), ("hostname", "主机名", STR), ("node_ip", "IP", STR),
    ("mountpoint", "挂载点", STR), ("device", "设备", STR),
    ("fstype", "文件系统", STR), ("size_gb", "容量(GB)", DEC),
    ("avail_gb", "可用(GB)", DEC), ("used_pct", "使用率(%)", DEC),
    ("disk_model", "磁盘型号", STR), ("snapshot_ts", "采集时间", STR),
]

HW_SHOW = [
    "role", "hostname", "node_ip", "sr_role", "cpu_cores", "mem_total_gb",
    "swap_total_gb", "sr_mem_limit", "disk_total_gb", "disk_avail_gb",
    "product", "os_name", "kernel", "uptime_days", "sr_version", "sr_alive",
    "snapshot_ts",
]
DISK_SHOW = [
    "role", "hostname", "mountpoint", "device", "fstype", "size_gb",
    "avail_gb", "used_pct", "disk_model",
]

HW_DESC = (
    "整机规格清单。StarRocks 自身只报 CN 的核数和内存上限，FE 侧没有任何硬件字段，"
    "所以机型 / 系统 / 内存 / 磁盘来自各节点 :9100 的 node_exporter，每天采集一次。"
    "「SR内存上限」是 StarRocks 进程的内存配额（mem_limit 75%），与整机内存不是一回事。"
)
DISK_DESC = (
    "每个节点的真实挂载点（已剔除 tmpfs 等伪文件系统）。CN 的 /data1、/data2 "
    "装的是 DataCache，使用率长期接近写满属正常，缓存靠淘汰工作。"
)


def table_params(ds_id, columns, order_by):
    return {
        "datasource": "%s__table" % ds_id,
        "viz_type": "table",
        "query_mode": "raw",
        "all_columns": list(columns),
        "order_by_cols": [json.dumps(o) for o in order_by],
        "groupby": [],
        "metrics": [],
        "percent_metrics": [],
        "adhoc_filters": [],
        "row_limit": 1000,
        "server_pagination": False,
        "page_length": 50,
        "include_search": False,
        "show_cell_bars": False,
        "color_pn": False,
        "allow_rearrange_columns": True,
        "table_timestamp_format": "smart_date",
        "temporal_columns_lookup": {},
    }


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with app.app_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable, TableColumn
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice
        from flask_appbuilder.security.sqla.models import User

        admin = db.session.query(User).filter_by(username="admin").first()
        dash = db.session.query(Dashboard).filter_by(slug=SLUG).one()

        os.makedirs(BACKUP_DIR, exist_ok=True)
        bpath = os.path.join(BACKUP_DIR, "dash38_hardware_%s.json" % ts)
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump({"position_json": dash.position_json,
                       "json_metadata": dash.json_metadata,
                       "slice_ids": sorted(s.id for s in dash.slices)},
                      f, ensure_ascii=False, indent=1)
        print("BACKUP|%s" % bpath)

        # the rest of this tab is served by database of the live SHOW datasets
        ref = db.session.query(SqlaTable).filter_by(
            table_name="v_show_frontends").one()
        database = ref.database
        print("DB|%s|id=%s" % (database.database_name, database.id))

        # ------------------------------------------------------- datasets
        def upsert_dataset(name, sql, cols, desc):
            ds = db.session.query(SqlaTable).filter_by(
                table_name=name, database_id=database.id).first()
            if ds is None:
                ds = SqlaTable(table_name=name, schema=SCHEMA,
                               database=database, is_sqllab_view=True)
                db.session.add(ds)
                db.session.flush()
                print("DS_NEW|%s|id=%s" % (name, ds.id))
            else:
                print("DS_UPD|%s|id=%s" % (name, ds.id))
            ds.sql = sql
            ds.schema = SCHEMA
            ds.description = desc
            if admin and not ds.owners:
                ds.owners = [admin]

            have = {c.column_name: c for c in list(ds.columns)}
            for col_name, verbose, col_type in cols:
                col = have.get(col_name)
                if col is None:
                    col = TableColumn(column_name=col_name)
                    ds.columns.append(col)
                col.type = col_type
                col.verbose_name = verbose
                col.is_dttm = False
                col.groupby = True
                col.filterable = True
            wanted = {c[0] for c in cols}
            for col in list(ds.columns):
                if col.column_name not in wanted:
                    ds.columns.remove(col)
                    db.session.delete(col)
                    print("  DS_COL_DROP|%s" % col.column_name)
            db.session.flush()

            with database.get_sqla_engine() as eng, eng.connect() as conn:
                n = len(conn.execute(text(sql)).fetchall())
            print("  SMOKE|%s|rows=%s" % (name, n))
            return ds

        ds_hw = upsert_dataset("v_sr_node_hw", HW_SQL, HW_COLS, HW_DESC)
        ds_disk = upsert_dataset("v_sr_node_disk", DISK_SQL, DISK_COLS,
                                 DISK_DESC)

        # ------------------------------------------------------- charts
        def upsert_chart(name, ds, columns, order_by, desc):
            sl = db.session.query(Slice).filter_by(slice_name=name).first()
            if sl is None:
                sl = Slice(slice_name=name, viz_type="table",
                           datasource_type="table")
                db.session.add(sl)
                db.session.flush()
                print("SLICE_NEW|%s|id=%s" % (name, sl.id))
            else:
                print("SLICE_UPD|%s|id=%s" % (name, sl.id))
            sl.datasource_id = ds.id
            sl.viz_type = "table"
            sl.description = desc
            params = table_params(ds.id, columns, order_by)
            params["slice_id"] = sl.id
            sl.params = json.dumps(params, ensure_ascii=False)
            sl.query_context = None
            if admin and not sl.owners:
                sl.owners = [admin]
            flag_modified(sl, "params")
            if sl not in dash.slices:
                dash.slices.append(sl)
            db.session.flush()
            return sl

        sl_hw = upsert_chart(
            "节点硬件", ds_hw, HW_SHOW,
            [["role", False], ["hostname", True]], HW_DESC)
        sl_disk = upsert_chart(
            "磁盘与挂载", ds_disk, DISK_SHOW,
            [["role", False], ["hostname", True], ["mountpoint", True]],
            DISK_DESC)

        # ------------------------------------------------------- layout
        pos = json.loads(dash.position_json or "{}")
        tab = pos[TAB]
        parents = list(pos[ANCHOR_ROW]["parents"])

        def have_chart(chart_id):
            return any(isinstance(v, dict) and v.get("type") == "CHART"
                       and (v.get("meta") or {}).get("chartId") == chart_id
                       for v in pos.values())

        def new_row(child_id, child_node):
            row_id = "ROW-%s" % uuid.uuid4().hex[:10]
            child_node["parents"] = parents + [row_id]
            pos[child_id] = child_node
            pos[row_id] = {
                "id": row_id, "type": "ROW", "children": [child_id],
                "parents": parents,
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            return row_id

        def markdown_row(title):
            node_id = "MARKDOWN-%s" % uuid.uuid4().hex[:10]
            return new_row(node_id, {
                "id": node_id, "type": "MARKDOWN", "children": [],
                "meta": {"code": SECTION_CSS % title, "height": 8,
                         "width": 12, "hideBackground": True},
            })

        def chart_row(sl, height):
            node_id = "CHART-%s" % uuid.uuid4().hex[:10]
            return new_row(node_id, {
                "id": node_id, "type": "CHART", "children": [],
                "meta": {"chartId": sl.id, "sliceName": sl.slice_name,
                         "uuid": str(sl.uuid), "width": 12, "height": height},
            })

        if have_chart(sl_hw.id) or have_chart(sl_disk.id):
            print("LAYOUT_SKIP|charts already placed")
        else:
            new_rows = [
                markdown_row("硬件"),
                chart_row(sl_hw, 40),
                chart_row(sl_disk, 74),
                markdown_row("集群节点"),
            ]
            at = tab["children"].index(ANCHOR_ROW) + 1
            tab["children"][at:at] = new_rows
            print("LAYOUT|inserted %s rows after %s" % (len(new_rows),
                                                        ANCHOR_ROW))
            print("LAYOUT|tab children=%s" % tab["children"])
            dash.position_json = json.dumps(pos, ensure_ascii=False)
            flag_modified(dash, "position_json")

        db.session.commit()
        print("COMMIT_OK|hw=%s|disk=%s" % (sl_hw.id, sl_disk.id))


if __name__ == "__main__":
    main()
