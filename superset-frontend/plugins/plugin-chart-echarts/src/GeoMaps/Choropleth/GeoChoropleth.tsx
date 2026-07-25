/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { useEffect, useRef, useState } from 'react';
import { getNumberFormatter } from '@superset-ui/core';
import { use, init, EChartsType } from 'echarts/core';
import { EffectScatterChart, MapChart } from 'echarts/charts';
import {
  GeoComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { buildRegionMatcher, ensureMap, shortRegionName } from '../common';

use([
  MapChart,
  EffectScatterChart,
  GeoComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

interface DataRow {
  region: unknown;
  city: unknown;
  lon: number;
  lat: number;
  value: number;
  detail: Record<string, unknown>;
}

interface Level {
  scope: string; // 行政区 adcode
  feature: string; // geojson feature 名
  raw: unknown; // 原始数据值（cross-filter 用）
}

interface Props {
  width: number;
  height: number;
  mapScope: string;
  initialZoom: number;
  initialCenter: [number, number] | null;
  entityName: string;
  cityName: string | null;
  detailNames: string[];
  hasCoords: boolean;
  rows: DataRow[];
  showLabels: boolean;
  showRanking: boolean;
  rankPageSize: number;
  rankWidth: number;
  rankHeight: number;
  rankPosition: 'left' | 'right';
  rankMarginX: number;
  rankMarginTop: number;
  enableDrill: boolean;
  allowRoam: boolean;
  labelFontSize: number;
  pointSize: number;
  numberFormat: string;
  colors: string[];
  emitCrossFilters?: boolean;
  setDataMask: (mask: unknown) => void;
  filterState?: { selectedValues?: unknown[] | null };
}

/** 明细值展示：毫秒时间戳转本地时间，其余原样 */
function fmtDetail(v: unknown): string {
  if (typeof v === 'number' && v > 1e11) {
    return new Date(v).toLocaleString('zh-CN', { hour12: false });
  }
  if (v === null || v === undefined) return '-';
  return String(v);
}

export default function GeoChoropleth(props: Props) {
  const {
    width,
    height,
    mapScope,
    initialZoom,
    initialCenter,
    entityName,
    cityName,
    detailNames,
    hasCoords,
    rows,
    showLabels,
    showRanking,
    rankPageSize,
    rankWidth,
    rankHeight,
    rankPosition,
    rankMarginX,
    rankMarginTop,
    enableDrill,
    allowRoam,
    labelFontSize,
    pointSize,
    numberFormat,
    colors,
    emitCrossFilters,
    setDataMask,
    filterState,
  } = props;
  const divRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType>();
  const [error, setError] = useState<string | null>(null);
  const [drill, setDrill] = useState<Level[]>([]);
  const [panelRows, setPanelRows] = useState<DataRow[] | null>(null);
  // 设备级视图中当前高亮的设备（点列表或点地图点位均可触发）
  const [hlDevice, setHlDevice] = useState<unknown>(null);
  // 设备级视图当前渲染的点位，供高亮联动局部刷新
  const ptsRef = useRef<DataRow[] | null>(null);
  const [rank, setRank] = useState<
    { name: string; label: string; pct: number }[] | null
  >(null);
  const [rankPage, setRankPage] = useState(0);
  // 窄图表默认折叠侧栏，避免遮挡地图
  const [rankCollapsed, setRankCollapsed] = useState(width < 480);
  // 排行侧栏点击与地图区域点击共用的处理函数
  const regionClickRef = useRef<(featureName: string) => void>(() => {});
  const idCol = detailNames[0] || null;

  // 当前生效的高亮设备：本地点击优先，其次取 cross-filter 选中值
  const selectedVals = filterState?.selectedValues || [];
  const filterDevice =
    panelRows && selectedVals.length === drill.length + 1
      ? selectedVals[selectedVals.length - 1]
      : null;
  const effSel =
    hlDevice !== null && hlDevice !== undefined ? hlDevice : filterDevice;

  // 供点击回调读取最新状态，避免闭包过期
  const latest = useRef<any>({});
  latest.current = {
    entityName,
    cityName,
    detailNames,
    emitCrossFilters,
    setDataMask,
    filterState,
    drill,
    effSel,
  };

  /** 设备点位系列数据；存在高亮设备时选中点放大着色、其余淡化 */
  const buildPointData = (pts: DataRow[], sel: unknown) => {
    const selStr = sel === null || sel === undefined ? null : String(sel);
    return pts.map(r => {
      const id = idCol ? String(r.detail[idCol] ?? '') : '';
      const isSel = selStr !== null && id === selStr;
      return {
        name: id,
        value: [r.lon, r.lat, r.value],
        detail: r.detail,
        raw: idCol ? r.detail[idCol] : null,
        ...(selStr !== null
          ? {
              symbolSize: isSel
                ? Math.max(16, pointSize * 2)
                : Math.max(4, Math.round(pointSize * 0.75)),
              itemStyle: {
                color: isSel ? '#e6742a' : 'rgba(31,95,191,0.35)',
                ...(isSel
                  ? {
                      borderColor: '#fff',
                      borderWidth: 2,
                      shadowBlur: 12,
                      shadowColor: 'rgba(230,116,42,0.9)',
                    }
                  : {}),
              },
              label: isSel
                ? {
                    show: Boolean(idCol),
                    position: 'right',
                    fontSize: 11,
                    fontWeight: 'bold',
                    color: '#e6742a',
                    formatter: (p: any) => p.name,
                  }
                : { show: false },
            }
          : {}),
      };
    });
  };

  useEffect(() => {
    if (divRef.current) {
      chartRef.current = init(divRef.current);
    }
    return () => {
      chartRef.current?.dispose();
      chartRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    setDrill([]);
  }, [mapScope]);

  // 切换层级/范围时排行侧栏回到第一页，并清除设备高亮
  useEffect(() => {
    setRankPage(0);
    setHlDevice(null);
  }, [drill, mapScope]);

  const canDrillCity = enableDrill && mapScope === 'china' && Boolean(cityName);
  const canDrillDevice = enableDrill && (detailNames.length > 0 || hasCoords);

  const applyFilter = (vals: unknown[], cols: (string | null)[]) => {
    const st = latest.current;
    if (!st.emitCrossFilters) return;
    if (!vals.length) {
      st.setDataMask({
        extraFormData: { filters: [] },
        filterState: { value: null, selectedValues: null },
      });
      return;
    }
    st.setDataMask({
      extraFormData: {
        filters: vals.map((v, i) => ({ col: cols[i], op: 'IN', val: [v] })),
      },
      filterState: { value: vals, selectedValues: vals },
    });
  };

  useEffect(() => {
    let alive = true;
    const level = drill.length;
    const scope = level ? drill[level - 1].scope : mapScope;
    const parentScope = level > 1 ? drill[level - 2].scope : mapScope;
    const fmt = getNumberFormatter(numberFormat);

    // 该层的数据行：逐级用名称匹配器过滤
    const rowsOfLevel = (): DataRow[] => {
      let out = rows;
      if (level >= 1) {
        const pm = buildRegionMatcher([drill[0].feature]);
        out = out.filter(r => pm(r.region) === drill[0].feature);
      }
      if (level >= 2) {
        const cm = buildRegionMatcher([drill[1].feature]);
        out = out.filter(r => cm(r.city) === drill[1].feature);
      }
      return out;
    };

    /** 设备点位视图（末级）：geo 背景 + 点位 + 右侧明细面板 */
    const renderPoints = (gj: any, usedScope: string, data: DataRow[]) => {
      const chart = chartRef.current;
      if (!alive || !chart) return;
      setRank(null);
      const pts = data.filter(
        r => Number.isFinite(r.lon) && Number.isFinite(r.lat),
      );
      ptsRef.current = pts;
      setPanelRows(data);
      const geoExtra: any = {};
      if (usedScope !== scope && pts.length) {
        // 城市 geojson 缺失时退回上级地图，缩放到点位质心
        geoExtra.center = [
          pts.reduce((s, r) => s + r.lon, 0) / pts.length,
          pts.reduce((s, r) => s + r.lat, 0) / pts.length,
        ];
        geoExtra.zoom = 6;
      }
      chart.setOption(
        {
          geo: {
            map: usedScope,
            roam: allowRoam,
            itemStyle: { areaColor: '#f5f6f8', borderColor: '#c6c9cf' },
            label: { show: true, fontSize: labelFontSize, color: '#999' },
            emphasis: {
              label: { show: true, color: '#666' },
              itemStyle: { areaColor: '#eef2f7' },
            },
            select: { disabled: true },
            ...geoExtra,
          },
          tooltip: {
            trigger: 'item',
            // 选中设备的信息框保持常驻，避免重渲染后消失
            alwaysShowContent: true,
            formatter: (p: any) => {
              const d = p.data?.detail || {};
              const lines = latest.current.detailNames.map(
                (c: string) => `${c}：${fmtDetail(d[c])}`,
              );
              return lines.join('<br/>') || p.name;
            },
          },
          visualMap: { show: false, min: 0, max: 1 },
          series: [
            {
              type: 'effectScatter',
              coordinateSystem: 'geo',
              data: buildPointData(pts, latest.current.effSel),
              symbolSize: pointSize,
              rippleEffect: { brushType: 'stroke', scale: 2.5 },
              itemStyle: { color: '#1f5fbf' },
              label: {
                show: pts.length <= 30 && Boolean(idCol),
                position: 'right',
                fontSize: 9,
                color: '#555',
                formatter: (p: any) => p.name,
              },
              emphasis: { itemStyle: { color: '#e6742a' } },
            },
          ],
        },
        true,
      );
      chart.off('click');
      chart.on('click', (params: any) => {
        if (params.componentType !== 'series') return;
        const raw = params.data?.raw;
        if (raw !== null && raw !== undefined) toggleDevice(raw);
      });
      // 全量重绘会销毁已弹出的 tooltip：若有选中设备，渲染完成后补发一次
      const selNow = latest.current.effSel;
      if (selNow !== null && selNow !== undefined && idCol) {
        const idx = pts.findIndex(
          r => String(r.detail[idCol] ?? '') === String(selNow),
        );
        if (idx >= 0) {
          setTimeout(() => {
            if (alive && chartRef.current) {
              chartRef.current.dispatchAction({
                type: 'showTip',
                seriesIndex: 0,
                dataIndex: idx,
              });
            }
          }, 80);
        }
      }
    };

    const toggleDevice = (deviceRaw: unknown) => {
      const st = latest.current;
      const wasSel = String(st.effSel) === String(deviceRaw);
      setHlDevice(wasSel ? null : deviceRaw);
      if (!st.emitCrossFilters || !idCol) return;
      const base = st.drill.map((l: Level) => l.raw);
      const baseCols = [st.entityName, st.cityName].slice(0, st.drill.length);
      const selected = st.filterState?.selectedValues || [];
      if (
        selected.length === base.length + 1 &&
        String(selected[selected.length - 1]) === String(deviceRaw)
      ) {
        applyFilter(base, baseCols);
      } else {
        applyFilter([...base, deviceRaw], [...baseCols, idCol]);
      }
    };

    /** 区域着色视图（省/市级） */
    const renderChoropleth = (gj: any) => {
      const chart = chartRef.current;
      if (!alive || !chart) return;
      ptsRef.current = null;
      setPanelRows(null);
      const features: any[] = gj.features || [];
      const featureNames: string[] = features
        .map((f: any) => f?.properties?.name)
        .filter(Boolean);
      const adcodeByName = new Map<string, string>();
      features.forEach((f: any) => {
        const p = f?.properties;
        if (p?.name && p?.adcode) adcodeByName.set(p.name, String(p.adcode));
      });
      const match = buildRegionMatcher(featureNames);
      const data = rowsOfLevel();
      const byFeature = new Map<string, { value: number; raw: unknown }>();
      data.forEach(r => {
        const key = level === 0 ? r.region : r.city;
        const f = match(key);
        if (!f) return;
        const prev = byFeature.get(f);
        byFeature.set(f, {
          value: (prev?.value || 0) + (Number.isFinite(r.value) ? r.value : 0),
          raw: prev?.raw ?? key,
        });
      });

      // 市级视图匹配不到任何城市（如直辖市）且可设备下钻 → 直接显示点位
      if (level === 1 && byFeature.size === 0 && canDrillDevice && data.length) {
        renderPoints(gj, scope, data);
        return;
      }

      const values = Array.from(byFeature.values()).map(v => v.value);
      const maxV = Math.max(1, ...values);

      if (showRanking) {
        setRank(
          Array.from(byFeature.entries())
            .sort((a, b) => b[1].value - a[1].value)
            .map(([name, v]) => ({
              name,
              label: fmt(v.value) as string,
              pct: Math.round((v.value / maxV) * 100),
            })),
        );
      } else {
        setRank(null);
      }
      const drillHint =
        level === 0
          ? canDrillCity
            ? '点击下钻到城市'
            : ''
          : canDrillDevice
            ? '点击查看设备明细'
            : '';
      chart.setOption(
        {
          tooltip: {
            trigger: 'item',
            formatter: (p: any) => {
              const v =
                p.value === undefined || Number.isNaN(p.value)
                  ? '无数据'
                  : fmt(p.value);
              const hint =
                drillHint && byFeature.has(p.name)
                  ? `<br/><span style="color:#888">${drillHint}</span>`
                  : '';
              return `${p.name}：${v}${hint}`;
            },
          },
          visualMap: {
            show: true,
            min: 0,
            max: maxV,
            calculable: true,
            // 渐变图例放在排行侧栏的另一侧，避免拥挤
            ...(showRanking && rankPosition === 'left'
              ? { right: 8 }
              : { left: 8 }),
            bottom: 8,
            text: ['多', '少'],
            inRange: { color: colors },
          },
          series: [
            {
              type: 'map',
              map: scope,
              roam: allowRoam,
              selectedMode: false,
              // 顶层视图应用初始缩放/中心（如聚焦中国大陆，弱化南海留白）
              ...(level === 0
                ? {
                    zoom: initialZoom,
                    ...(initialCenter ? { center: initialCenter } : {}),
                  }
                : {}),
              // 内嵌排行侧栏展开时地图主体向另一侧避让
              ...(showRanking && !rankCollapsed
                ? {
                    layoutCenter: [
                      rankPosition === 'left' ? '58%' : '42%',
                      '50%',
                    ],
                    layoutSize: '92%',
                  }
                : {}),
              label: {
                show: showLabels,
                fontSize: labelFontSize,
                color: '#333',
                formatter: (p: any) =>
                  p.value === undefined || Number.isNaN(p.value)
                    ? ''
                    : `${shortRegionName(p.name)}\n${fmt(p.value)}`,
              },
              emphasis: {
                label: { show: true, fontSize: labelFontSize + 1 },
                itemStyle: { areaColor: '#ffd666' },
              },
              itemStyle: { areaColor: '#f5f5f5', borderColor: '#bbb' },
              data: Array.from(byFeature.entries()).map(([name, v]) => ({
                name,
                value: v.value,
              })),
            },
          ],
        },
        true,
      );

      const onRegion = (featureName: string) => {
        const st = latest.current;
        const hit = byFeature.get(featureName);
        if (!hit) return;
        if (level === 0 && canDrillCity) {
          const adcode = adcodeByName.get(featureName);
          if (adcode) {
            applyFilter([hit.raw], [st.entityName]);
            setDrill([{ scope: adcode, feature: featureName, raw: hit.raw }]);
            return;
          }
        }
        if (level === 1 && canDrillDevice) {
          const adcode = adcodeByName.get(featureName) || scope;
          applyFilter(
            [st.drill[0].raw, hit.raw],
            [st.entityName, st.cityName],
          );
          setDrill([
            st.drill[0],
            { scope: adcode, feature: featureName, raw: hit.raw },
          ]);
          return;
        }
        // 无下钻能力时：单级 cross-filter 开关
        const selected = st.filterState?.selectedValues || [];
        const col = level === 0 ? st.entityName : st.cityName;
        if (
          selected.length === 1 &&
          String(selected[0]) === String(hit.raw)
        ) {
          applyFilter([], []);
        } else {
          applyFilter([hit.raw], [col]);
        }
      };
      regionClickRef.current = onRegion;
      chart.off('click');
      chart.on('click', (params: any) => onRegion(params.name));
    };

    ensureMap(scope)
      .then(gj => {
        if (!alive) return;
        setError(null);
        if (level === 2) {
          renderPoints(gj, scope, rowsOfLevel());
        } else {
          renderChoropleth(gj);
        }
      })
      .catch(() => {
        if (!alive) return;
        if (level === 2) {
          // 城市级 geojson 缺失 → 用省级地图做背景显示点位
          ensureMap(parentScope)
            .then(gj => {
              if (alive) {
                setError(null);
                renderPoints(gj, parentScope, rowsOfLevel());
              }
            })
            .catch(e2 => alive && setError(String(e2?.message || e2)));
        } else if (level === 1) {
          setDrill([]);
        } else {
          setError('地图数据加载失败');
        }
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapScope, drill, rows, showLabels, showRanking, rankCollapsed,
      rankPosition, enableDrill, allowRoam, labelFontSize, pointSize,
      numberFormat, colors, cityName, initialZoom,
      initialCenter ? initialCenter.join(',') : '']);

  useEffect(() => {
    chartRef.current?.resize({ width, height });
  }, [width, height]);

  // 高亮联动：局部刷新点位样式，弹出选中点 tooltip，列表滚动到选中项
  useEffect(() => {
    const chart = chartRef.current;
    const pts = ptsRef.current;
    if (!chart || !pts) return undefined;
    chart.setOption({ series: [{ data: buildPointData(pts, effSel) }] });
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (effSel !== null && effSel !== undefined) {
      const idx = pts.findIndex(
        r => idCol && String(r.detail[idCol] ?? '') === String(effSel),
      );
      if (idx >= 0) {
        // 延迟到本帧渲染结束后弹出，避免与数据替换竞争导致信息框不显示
        timer = setTimeout(() => {
          chartRef.current?.dispatchAction({
            type: 'showTip',
            seriesIndex: 0,
            dataIndex: idx,
          });
        }, 80);
      }
      const nodes = wrapRef.current?.querySelectorAll('[data-dev]');
      if (nodes) {
        Array.from(nodes)
          .find(el => el.getAttribute('data-dev') === String(effSel))
          ?.scrollIntoView({ block: 'nearest' });
      }
    } else {
      chart.dispatchAction({ type: 'hideTip' });
    }
    return () => {
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effSel, panelRows]);

  if (error) {
    return (
      <div style={{ width, height, padding: 16, color: '#c0392b' }}>
        {error}
      </div>
    );
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative', width, height }}>
      {drill.length > 0 && (
        <div
          style={{
            position: 'absolute',
            zIndex: 2,
            top: 8,
            left: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            background: 'rgba(255,255,255,0.92)',
            borderRadius: 4,
            padding: '4px 8px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
            fontSize: 12,
          }}
        >
          <button
            type="button"
            onClick={() => {
              setDrill([]);
              applyFilter([], []);
            }}
            style={{
              border: '1px solid #d0d0d0',
              background: '#fff',
              borderRadius: 4,
              padding: '2px 10px',
              cursor: 'pointer',
            }}
          >
            ← 全国
          </button>
          {drill.length > 1 && (
            <button
              type="button"
              onClick={() => {
                const up = drill.slice(0, -1);
                setDrill(up);
                applyFilter(
                  up.map(l => l.raw),
                  [entityName, cityName].slice(0, up.length),
                );
              }}
              style={{
                border: '1px solid #d0d0d0',
                background: '#fff',
                borderRadius: 4,
                padding: '2px 10px',
                cursor: 'pointer',
              }}
            >
              ← 上级
            </button>
          )}
          <span style={{ color: '#555' }}>
            {drill.map(l => l.feature).join(' / ')}
          </span>
        </div>
      )}
      {rank && rank.length > 0 && (() => {
        const PAGE_SIZE = rankPageSize;
        const totalPages = Math.ceil(rank.length / PAGE_SIZE);
        const page = Math.min(rankPage, totalPages - 1);
        const pageRows = rank.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
        const badgeColor = (idx: number) =>
          ['#f5222d', '#fa8c16', '#faad14'][idx] || '#c8ccd4';
        const sideStyle =
          rankPosition === 'left'
            ? { left: rankMarginX }
            : { right: rankMarginX };
        // 下钻后左侧有面包屑，侧栏在左时额外下移避让
        const topOffset =
          (drill.length > 0 && rankPosition === 'left' ? 36 : 0) +
          rankMarginTop;
        // 高度：0 = 撑满到底部；>0 = 固定高度（不超出图表范围）
        const heightStyle =
          rankHeight > 0
            ? { height: Math.min(rankHeight, height - topOffset - 8) }
            : { bottom: 8 };
        if (rankCollapsed) {
          return (
            <button
              type="button"
              onClick={() => setRankCollapsed(false)}
              title="展开排行侧栏"
              style={{
                position: 'absolute',
                zIndex: 1,
                top: topOffset,
                ...sideStyle,
                border: '1px solid rgba(31,95,191,0.2)',
                background: 'rgba(255,255,255,0.95)',
                borderRadius: 6,
                padding: '4px 8px',
                fontSize: 12,
                color: '#1f5fbf',
                cursor: 'pointer',
                boxShadow: '0 1px 6px rgba(31,63,143,0.12)',
              }}
            >
              {drill.length === 0 ? '省份排行' : '城市排行'}{' '}
              {rankPosition === 'left' ? '»' : '«'}
            </button>
          );
        }
        return (
          <div
            className="geo-rank-panel"
            style={{
              position: 'absolute',
              zIndex: 1,
              top: topOffset,
              ...sideStyle,
              ...heightStyle,
              width: rankWidth,
              display: 'flex',
              flexDirection: 'column',
              background: 'rgba(255,255,255,0.95)',
              borderRadius: 8,
              boxShadow: '0 2px 10px rgba(31,63,143,0.12)',
              border: '1px solid rgba(31,95,191,0.08)',
              fontSize: 12,
              overflow: 'hidden',
            }}
          >
            <style>{`
              .geo-rank-panel .rank-item { transition: background .15s; }
              .geo-rank-panel .rank-item:hover { background: #eef4ff; }
              .geo-rank-panel .rank-item:hover .rank-name { color: #1f5fbf; }
              .geo-rank-panel .pg-btn { border: 1px solid #e0e4ea; background: #fff;
                border-radius: 4px; width: 22px; height: 20px; line-height: 1;
                cursor: pointer; color: #556; }
              .geo-rank-panel .pg-btn:hover:not(:disabled) { border-color: #1f5fbf; color: #1f5fbf; }
              .geo-rank-panel .pg-btn:disabled { color: #ccc; cursor: default; }
            `}</style>
            <div
              style={{
                padding: '7px 10px',
                fontWeight: 600,
                color: '#26324d',
                borderBottom: '1px solid #eef0f3',
                background: 'linear-gradient(180deg,#fbfcfe,#f3f6fb)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span>{drill.length === 0 ? '省份排行' : '城市排行'}</span>
              <span
                style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              >
                <span
                  style={{
                    fontWeight: 400,
                    fontSize: 11,
                    color: '#8a93a6',
                  }}
                >
                  共{rank.length}
                </span>
                <button
                  type="button"
                  onClick={() => setRankCollapsed(true)}
                  title="折叠侧栏"
                  style={{
                    border: 'none',
                    background: 'transparent',
                    cursor: 'pointer',
                    color: '#8a93a6',
                    fontSize: 13,
                    padding: '0 2px',
                    lineHeight: 1,
                  }}
                >
                  {rankPosition === 'left' ? '«' : '»'}
                </button>
              </span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto' }}>
              {pageRows.map((r, i) => {
                const idx = page * PAGE_SIZE + i;
                return (
                  <div
                    key={r.name}
                    className="rank-item"
                    onClick={() => regionClickRef.current(r.name)}
                    title={`${r.name}：${r.label}（点击下钻）`}
                    style={{ padding: '5px 10px 6px', cursor: 'pointer' }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        marginBottom: 3,
                      }}
                    >
                      <span
                        style={{
                          flex: 'none',
                          width: 16,
                          height: 16,
                          borderRadius: idx < 3 ? 4 : 8,
                          background: badgeColor(idx),
                          color: '#fff',
                          fontSize: 10,
                          fontWeight: 600,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        {idx + 1}
                      </span>
                      <span
                        className="rank-name"
                        style={{
                          flex: 1,
                          color: '#3a4560',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {shortRegionName(r.name)}
                      </span>
                      <span
                        style={{
                          fontWeight: 700,
                          color: '#1f5fbf',
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {r.label}
                      </span>
                    </div>
                    <div
                      style={{
                        height: 3,
                        borderRadius: 2,
                        background: '#edf0f5',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: `${Math.max(r.pct, 2)}%`,
                          height: '100%',
                          borderRadius: 2,
                          background:
                            'linear-gradient(90deg,#7aa6f5,#1f5fbf)',
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
            {totalPages > 1 && (
              <div
                style={{
                  padding: '5px 10px',
                  borderTop: '1px solid #eef0f3',
                  background: '#fbfcfe',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <button
                  type="button"
                  className="pg-btn"
                  disabled={page === 0}
                  onClick={() => setRankPage(page - 1)}
                >
                  ‹
                </button>
                <span style={{ color: '#8a93a6', fontSize: 11 }}>
                  {page + 1} / {totalPages}
                </span>
                <button
                  type="button"
                  className="pg-btn"
                  disabled={page >= totalPages - 1}
                  onClick={() => setRankPage(page + 1)}
                >
                  ›
                </button>
              </div>
            )}
          </div>
        );
      })()}
      {panelRows && panelRows.length > 0 && detailNames.length > 0 && (
        <div
          style={{
            position: 'absolute',
            zIndex: 2,
            top: 8,
            right: 8,
            bottom: 8,
            width: 250,
            overflowY: 'auto',
            background: 'rgba(255,255,255,0.95)',
            borderRadius: 6,
            boxShadow: '0 1px 6px rgba(0,0,0,0.18)',
            fontSize: 12,
          }}
        >
          <div
            style={{
              padding: '6px 10px',
              fontWeight: 600,
              borderBottom: '1px solid #eee',
              position: 'sticky',
              top: 0,
              background: '#fff',
            }}
          >
            设备明细（{panelRows.length}）
          </div>
          {panelRows.map((r, i) => {
            const id = idCol ? r.detail[idCol] : null;
            const isSel =
              effSel !== null &&
              effSel !== undefined &&
              String(effSel) === String(id);
            return (
              <div
                key={i}
                data-dev={id === null || id === undefined ? undefined : String(id)}
                onClick={() => {
                  if (!idCol || id === null || id === undefined) return;
                  setHlDevice(isSel ? null : id);
                  const base = drill.map(l => l.raw);
                  const baseCols = [entityName, cityName].slice(
                    0,
                    drill.length,
                  );
                  if (isSel) applyFilter(base, baseCols);
                  else applyFilter([...base, id], [...baseCols, idCol]);
                }}
                style={{
                  padding: '6px 10px',
                  borderBottom: '1px solid #f2f2f2',
                  cursor: idCol ? 'pointer' : 'default',
                  background: isSel ? '#fff3e8' : 'transparent',
                  borderLeft: isSel
                    ? '3px solid #e6742a'
                    : '3px solid transparent',
                }}
              >
                <div
                  style={{
                    fontWeight: 600,
                    color: isSel ? '#e6742a' : '#1f5fbf',
                  }}
                >
                  {fmtDetail(id)}
                </div>
                {detailNames.slice(1).map(c => (
                  <div key={c} style={{ color: '#666' }}>
                    {c}：{fmtDetail(r.detail[c])}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
      <div ref={divRef} style={{ width, height }} />
    </div>
  );
}
