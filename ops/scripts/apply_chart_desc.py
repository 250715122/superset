# -*- coding: utf-8 -*-
"""Write metric-calculation descriptions into chart `description` for both
dashboards (truck battery + CS ops). Hovering the info icon next to the chart
title on the dashboard shows the text.

Dev & prod compatible (config path auto-detect). Idempotent (overwrites).
"""
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

# ---------- 卡车电池设备分析 ----------
PB = {
    "设备总数": "口径：COUNT(*)，每台设备取最新一条上报快照。统计接入过平台的全部设备（含长期离线设备）。数据源：设备最新状态表 ads_tb_device_latest_geo。",
    "有GPS定位设备": "口径：SUM(has_geo)，最新快照中经纬度有效（可定位到省市）的设备数。",
    "覆盖省份数": "口径：COUNT(DISTINCT province_name)，按设备最新GPS位置解析出的省份去重计数。",
    "覆盖城市数": "口径：COUNT(DISTINCT nearest_city)，按设备最新GPS坐标匹配的最近城市去重计数。",
    "型号分布": "口径：各型号有GPS定位设备的数量（COUNT(*)，条件 has_geo=1），按每台设备最新快照统计。",
    "设备明细(随省份/城市联动)": "有GPS定位设备的最新状态明细（SOC/SOH/电压/温度等）。随左侧地图下钻联动：点击省份/城市后仅显示对应区域设备。",
    "设备地图(逐级下钻至设备)": "口径：各省有GPS定位设备数（COUNT(*)）。点击省份下钻到城市，再下钻到设备点位；点位可查看设备号及最新状态。",
    "设备型号数": "口径：COUNT(DISTINCT device_model)，全部设备最新快照中的型号去重数。",
    "近7天活跃设备": "口径：最新上报时间在近7天内的设备数，SUM(CASE WHEN last_time >= now()-7天 THEN 1 END)。",
    "近30天活跃设备": "口径：最新上报时间在近30天内的设备数，SUM(CASE WHEN last_time >= now()-30天 THEN 1 END)。",
    "平均SOC(%)": "口径：AVG(battery_soc)，全部设备最新快照的剩余电量平均值。",
    "今日活跃设备数": "口径：COUNT(DISTINCT device_sn)，今日0点至今有数据上报的设备去重数。数据源：分钟级历史明细 ads_tb_history。",
    "平均SOH": "口径：AVG(battery_soh)，设备最新快照的健康度平均值。仅统计上报了SOH的设备（未上报的不计入分母）。",
    "活跃设备日趋势": "口径：每日有数据上报的设备去重数 COUNT(DISTINCT device_sn)。数据源：设备×日活跃聚合表 ads_tb_active_geo。",
    "各型号设备数": "口径：各型号设备数量 COUNT(*)，按每台设备最新快照统计（含长期离线设备）。",
    "各型号活跃趋势": "口径：按型号分组的每日活跃设备去重数 COUNT(DISTINCT device_sn)。",
    "充电状态分布": "口径：各设备最新快照的充电状态占比（COUNT(*) 按状态分组）。状态码已翻译为中文：待机/充电中/放电中等。",
    "平均SOH(%)": "口径：AVG(battery_soh)，设备最新快照的健康度平均值。仅统计上报了SOH的设备（未上报的不计入分母）。",
    "SOH数据覆盖率": "口径：COUNT(battery_soh)/COUNT(*)，上报了SOH字段的设备占全部设备的比例。",
    "低SOH设备数(<90%)": "口径：SUM(CASE WHEN battery_soh<90 THEN 1 END)，最新快照SOH低于90%的设备数。",
    "平均包温(℃)": "口径：AVG((pack_average_temp-32)*5/9)。原始数据为华氏度，已换算为摄氏度。取设备最新快照。",
    "SOC分布": "口径：按SOC区间（10%一档）分组的设备数，取每台设备最新快照。",
    "SOH分布": "口径：按SOH区间分组的设备数，取每台设备最新快照（仅含上报SOH的设备）。",
    "各型号平均包温(℃)": "口径：按型号 AVG((pack_average_temp-32)*5/9)，华氏度已换算为摄氏度。取设备最新快照。",
    "各型号平均电压(V)": "口径：按型号 AVG(vpack)，取设备最新快照的电池包电压平均值。",
    "SOH最低设备TOP50": "SOH升序排列的前50台设备最新状态明细（仅含上报SOH的设备），用于排查健康度异常设备。",
    "累计充电量(kWh)": "口径：SUM(pack_total_chg_energy)。每台设备取生命周期累计充电量（计数器最新值），再对全部设备求和。单位kWh（上游确认）。",
    "累计放电量(kWh)": "口径：SUM(pack_total_dsg_energy)。每台设备取生命周期累计放电量（计数器最新值），再对全部设备求和。单位kWh（上游确认）。",
    "平均单台放电量(kWh)": "口径：全部设备累计放电量之和 / 设备总数，即平均每台设备生命周期放电量。",
    "各型号累计充电量(kWh)": "口径：按型号 SUM(pack_total_chg_energy)，每台设备取生命周期累计值再按型号求和。",
    "各型号累计放电量(kWh)": "口径：按型号 SUM(pack_total_dsg_energy)，每台设备取生命周期累计值再按型号求和。",
    "各省累计放电量排行(kWh)": "口径：有GPS定位设备按省份 SUM(pack_total_dsg_energy)，每台设备取生命周期累计值。",
    "各型号平均SOC(%)": "口径：按型号 AVG(battery_soc)，取设备最新快照。",
    "SOC历史曲线": "口径：按时间聚合的 AVG(battery_soc)，默认近7天。配合上方设备号筛选器可查看单台设备的SOC曲线。数据源：分钟级历史 ads_tb_history。",
    "电压/电流历史曲线": "口径：AVG(vpack) 与 AVG(battery_current)，默认近7天。电流为负表示放电、为正表示充电。建议筛选单台设备查看。",
    "温度历史曲线": "口径：包平均温度/单体最高温/单体最低温的时间曲线（单位℃，视图层已从华氏度换算），默认近7天。建议筛选单台设备查看。",
    "累计充放电量趋势(kWh)": "口径：每个时间点取 MAX(累计充电量)/MAX(累计放电量)。累计值为只增计数器，取最大值而非求和；曲线斜率反映充放电速率。默认近7天。",
    "设备数据明细(按设备/时间调取)": "分钟级历史明细原始记录（SOC/SOH/电压/电流/温度/累计电量等），默认近7天。用上方设备号+时间范围筛选器调取指定设备数据。",
}

# ---------- 全球AI客服·运营分析 ----------
CS = {
    "总用户消息数": "口径：SUM(chat_user_messages)，所选时间范围内全部站点用户发送的Chat消息总数（不含AI回复）。数据源：站点×日服务汇总 ads_cs_service_daily。",
    "用户消息数": "口径：SUM(chat_user_messages)，用户发送的Chat消息总数（不含AI回复）。",
    "Chat有效会话数": "口径：SUM(chat_sessions)。有效会话＝用户至少发送过1条消息的会话。",
    "Email工单数": "口径：SUM(email_tickets)，进入AI处理流程的邮件工单总数。",
    "Chat自动解决率": "口径：1 - 转人工会话数/有效会话数。未转人工即视为AI自动解决。",
    "Email自动回复率": "口径：可自动回复工单数 / 全部工单数（SUM(email_can_auto_reply)/SUM(email_tickets)）。",
    "邮件发送成功率": "口径：发送成功数 / 发送总数（SUM(email_send_success)/SUM(email_send_total)）。",
    "发送失败数": "口径：SUM(email_send_failed)，邮件发送失败的次数。",
    "每日服务量趋势(Chat消息/Email工单)": "口径：每日用户Chat消息数与Email工单数，双线对比两渠道服务量走势。",
    "Chat自动解决率/转人工率趋势": "口径：每日自动解决率（1-转人工/有效会话）与转人工率（转人工/有效会话），两者互补。",
    "站点Chat会话排行": "口径：各站点有效会话数合计 SUM(chat_sessions)，仅显示会话数>0的站点。",
    "去重用户数(周期)": "口径：COUNT(DISTINCT user_id)，所选周期内发过消息的独立用户数（跨天去重，不等于各日用户数之和）。数据源：会话宽表 dws_cs_chat_session_wide。",
    "导购PSH命中会话": "口径：SUM(chat_shopping_guide)，触发导购（PSH商品推荐）的会话数。",
    "用户消息量趋势(渐变面积)": "口径：每日用户Chat消息数 SUM(chat_user_messages)。",
    "各站点访问量(消息数)": "口径：各站点用户Chat消息总数 SUM(chat_user_messages)。",
    "小时×站点活跃分布": "口径：按小时×站点统计的用户消息记录数，点越大代表该站点该时段消息越多，用于识别各站点活跃时段（时区为数据入库时间）。",
    "Chat标签分类TOP": "口径：chat渠道各分类标签命中次数合计 SUM(tag_hits)。一条消息可命中多个标签。数据源：标签分类×渠道×日 ads_cs_label_category_daily。",
    "Chat分类趋势TOP10": "口径：chat渠道命中量TOP10分类的每日命中次数趋势 SUM(tag_hits)。",
    "邮件工单自动化漏斗": "口径：邮件处理各环节数量（工单接入→可自动回复→发起发送→发送成功），SUM(step_value) 按环节分组。",
    "Email自动回复率趋势": "口径：每日 可自动回复工单/全部工单。",
    "Chat/Email分类命中对比": "口径：chat与email两渠道各自的标签命中总量 SUM(tag_hits) 对比。",
    "Email分类趋势": "口径：email渠道各分类的每日标签命中次数 SUM(tag_hits)。",
    "高频分类明细表": "口径：渠道×分类维度的标签命中次数（tag_hits）与涉及案例数（case_count）明细。",
    "转人工状态分布": "口径：转人工流程各状态的数量 SUM(step_value)（如已触发/排队/已接入等），非严格单向漏斗。",
    "营业/非营业转人工对比": "口径：按营业时间/非营业时间分组的转人工会话数 SUM(transferred_count)。非营业时段转人工通常无人接待，是解释自动解决率波动的关键维度。",
    "转人工类型分布": "口径：按转人工触发类型分组的触发次数 SUM(handoff_triggered_count)。",
    "站点转人工率排行": "口径：转人工率＝转人工会话/有效会话。同时列出转人工量与会话数（样本量），避免小样本站点的率失真。",
    "高转人工标签TOP": "口径：各标签命中会话中发生转人工的数量与占比（转人工会话/命中会话），按转人工会话数降序，保留样本量列。",
    "平均首响(秒)": "口径：会话数加权平均首次响应时长 Σ(日均首响×测量会话数)/Σ测量会话数。仅统计能测量到首响的会话。",
    "10秒内首响率": "口径：会话数加权的10秒内首次响应占比 Σ(日内10秒率×测量会话数)/Σ测量会话数。",
    "回访用户占比": "口径：回访用户数/活跃用户数。回访用户＝当日活跃且历史上（当日前）出现过的用户。",
    "首响时延趋势(秒)": "口径：每日会话数加权平均首次响应时长。",
    "新客vs回访趋势": "口径：每日新用户数（首次出现）与回访用户数（历史出现过）。",
    "近7天用户消息": "口径：近7天用户消息总数，来自预计算的周期对比表（近7天vs前7天），底部显示环比变化。",
    "近7天Chat自动解决率": "口径：近7天 1-转人工/有效会话，来自预计算的周期对比表（近7天vs前7天），底部显示环比变化。",
    "近7天Email工单": "口径：近7天Email工单总数，来自预计算的周期对比表（近7天vs前7天），底部显示环比变化。",
    "近7天邮件自动回复率": "口径：近7天 可自动回复/全部工单，来自预计算的周期对比表（近7天vs前7天），底部显示环比变化。",
    "多周期规模指标对比": "口径：规模类（计数）指标在近7天/近30天等周期的当前值、上期值与变化率，来自预计算的周期对比表 ads_cs_kpi_period_compare。",
    "多周期效率指标对比": "口径：效率类（比率）指标在近7天/近30天等周期的当前值、上期值与变化率（百分点差）。",
    "周度服务量趋势": "口径：按自然周汇总的用户Chat消息数与Email工单数。数据源：周汇总 ads_cs_service_weekly。",
    "周度效率指标趋势": "口径：周度Chat自动解决率、邮件自动回复率、转人工率。",
    "站点服务量近7天变化率": "口径：（近7天总服务量-前7天）/前7天。总服务量＝Chat消息+Email工单。仅显示前7天有量的站点。",
    "站点经营对比明细": "口径：各站点近7天vs前7天的总服务量、变化率、Chat消息、Email工单、转人工率明细。",
    "近7天渠道服务量结构": "口径：近7天用户Chat消息数与Email工单数的占比构成。",
    "Chat对话明细": "逐条Chat消息明细（站点/会话/用户消息/AI回复/时间等），配合筛选器按站点、日期调取原始对话。数据源：dws_cs_chat_message_detail。",
    "Email工单明细": "邮件工单逐单明细（站点/主题/是否可自动回复/发送状态等）。数据源：dws_cs_email_ticket_detail。",
    "各站点首响明细": "口径：各站点会话数加权平均首响时长、10秒内首响率及测量会话数（样本量）。",
    "周报·标签分类命中(全站)": "周报专用：chat渠道各分类标签命中次数按日透视（SUM(tag_hits)），供周报数据摘取。",
    "周报·访问量/消息数/用户数/导购汇总": "周报专用：基于会话宽表按日汇总用户消息数、去重用户数（COUNT(DISTINCT user_id)）、转人工会话数、导购命中会话数。",
}

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    def find_dash(slug, kw):
        d = db.session.query(Dashboard).filter_by(slug=slug).first()
        if d:
            return d
        for dd in db.session.query(Dashboard).all():
            t = dd.dashboard_title or ""
            if all(k in t for k in kw):
                return dd
        return None

    jobs = [("PB", find_dash("pb-device-analysis", ["卡车电池"]), PB),
            ("CS", find_dash("cs-ops-analysis", ["AI", "运营"]), CS)]

    for tag, d, mapping in jobs:
        if not d:
            print("%s|DASH NOT FOUND" % tag)
            continue
        applied, missing = 0, []
        for s in d.slices:
            desc = mapping.get(s.slice_name)
            if desc:
                if s.description != desc:
                    s.description = desc
                applied += 1
            else:
                missing.append("%s:%s" % (s.id, s.slice_name))
        db.session.commit()
        print("%s|dash_id=%s|charts=%d|applied=%d|missing=%d"
              % (tag, d.id, len(d.slices), applied, len(missing)))
        for m in missing:
            print("  MISS|%s" % m.encode("unicode_escape").decode())
    print("DESC_DONE")
