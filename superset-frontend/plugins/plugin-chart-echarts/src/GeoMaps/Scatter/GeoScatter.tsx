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
import { EffectScatterChart, ScatterChart } from 'echarts/charts';
import { GeoComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { ensureMap, sizeScale } from '../common';
import { GeoPoint } from './transformProps';

use([
  ScatterChart,
  EffectScatterChart,
  GeoComponent,
  TooltipComponent,
  CanvasRenderer,
]);

interface Props {
  width: number;
  height: number;
  mapScope: string;
  points: GeoPoint[];
  dimName: string | null;
  metricLabel: string;
  rippleEffect: boolean;
  maxPointSize: number;
  numberFormat: string;
  emitCrossFilters?: boolean;
  setDataMask: (mask: unknown) => void;
  filterState?: { selectedValues?: unknown[] | null };
}

export default function GeoScatter(props: Props) {
  const {
    width,
    height,
    mapScope,
    points,
    dimName,
    metricLabel,
    rippleEffect,
    maxPointSize,
    numberFormat,
    emitCrossFilters,
    setDataMask,
    filterState,
  } = props;
  const divRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType>();
  const [error, setError] = useState<string | null>(null);
  const latest = useRef<any>({});
  latest.current = { dimName, emitCrossFilters, setDataMask, filterState };

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
    let alive = true;
    ensureMap(mapScope)
      .then(() => {
        const chart = chartRef.current;
        if (!alive || !chart) return;
        setError(null);
        const fmt = getNumberFormatter(numberFormat);
        const maxV = Math.max(1, ...points.map(p => p.value));
        const seriesData = points.map(p => ({
          name: p.label,
          value: [p.lon, p.lat, p.value],
          raw: p.raw,
        }));
        chart.setOption(
          {
            geo: {
              map: mapScope,
              roam: true,
              itemStyle: { areaColor: '#f5f6f8', borderColor: '#c6c9cf' },
              emphasis: {
                label: { show: false },
                itemStyle: { areaColor: '#eef2f7' },
              },
              select: { disabled: true },
            },
            tooltip: {
              trigger: 'item',
              formatter: (p: any) => {
                const v = Array.isArray(p.value) ? p.value[2] : p.value;
                const head = p.name ? `${p.name}<br/>` : '';
                return `${head}${metricLabel}：${fmt(v)}<br/>坐标：${
                  p.value[1]
                }°N, ${p.value[0]}°E`;
              },
            },
            series: [
              {
                type: rippleEffect ? 'effectScatter' : 'scatter',
                coordinateSystem: 'geo',
                data: seriesData,
                symbolSize: (val: number[]) =>
                  sizeScale(val[2], maxV, 5, maxPointSize),
                rippleEffect: { brushType: 'stroke', scale: 3 },
                itemStyle: { color: '#1f5fbf', opacity: 0.75 },
                emphasis: { itemStyle: { color: '#e6742a', opacity: 1 } },
              },
            ],
          },
          true,
        );

        chart.off('click');
        chart.on('click', (params: any) => {
          const st = latest.current;
          if (
            !st.emitCrossFilters ||
            !st.dimName ||
            params.componentType !== 'series'
          )
            return;
          const raw = params.data?.raw;
          if (raw === null || raw === undefined) return;
          const selected = st.filterState?.selectedValues || [];
          if (selected.length && String(selected[0]) === String(raw)) {
            st.setDataMask({
              extraFormData: { filters: [] },
              filterState: { value: null, selectedValues: null },
            });
          } else {
            st.setDataMask({
              extraFormData: {
                filters: [{ col: st.dimName, op: 'IN', val: [raw] }],
              },
              filterState: { value: [raw], selectedValues: [raw] },
            });
          }
        });
      })
      .catch(e => {
        if (alive) setError(String(e?.message || e));
      });
    return () => {
      alive = false;
    };
  }, [mapScope, points, rippleEffect, maxPointSize, numberFormat, metricLabel]);

  useEffect(() => {
    chartRef.current?.resize({ width, height });
  }, [width, height]);

  if (error) {
    return (
      <div style={{ width, height, padding: 16, color: '#c0392b' }}>
        {error}
      </div>
    );
  }
  return <div ref={divRef} style={{ width, height }} />;
}
