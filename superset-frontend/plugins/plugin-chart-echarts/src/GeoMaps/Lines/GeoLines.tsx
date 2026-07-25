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
import { EffectScatterChart, LinesChart } from 'echarts/charts';
import { GeoComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { ensureMap } from '../common';
import { GeoLine } from './transformProps';

use([
  LinesChart,
  EffectScatterChart,
  GeoComponent,
  TooltipComponent,
  CanvasRenderer,
]);

interface Props {
  width: number;
  height: number;
  mapScope: string;
  lines: GeoLine[];
  metricLabel: string;
  curveness: number;
}

export default function GeoLines(props: Props) {
  const { width, height, mapScope, lines, metricLabel, curveness } = props;
  const divRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType>();
  const [error, setError] = useState<string | null>(null);

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
        const fmt = getNumberFormatter('SMART_NUMBER');
        const targets = new Map<string, { coord: [number, number]; v: number }>();
        lines.forEach(l => {
          const key = l.coords[1].join(',');
          const prev = targets.get(key);
          targets.set(key, {
            coord: l.coords[1],
            v: (prev?.v || 0) + l.value,
          });
        });
        chart.setOption(
          {
            geo: {
              map: mapScope,
              roam: true,
              itemStyle: { areaColor: '#10182f', borderColor: '#3b4a6b' },
              emphasis: {
                label: { show: false },
                itemStyle: { areaColor: '#182342' },
              },
              select: { disabled: true },
            },
            backgroundColor: '#0b1226',
            tooltip: {
              trigger: 'item',
              formatter: (p: any) => {
                if (p.seriesType === 'lines') {
                  const head = p.data?.label ? `${p.data.label}<br/>` : '';
                  return `${head}${metricLabel}：${fmt(p.data?.value)}`;
                }
                return `${metricLabel}：${fmt(p.value?.[2])}`;
              },
            },
            series: [
              {
                type: 'lines',
                coordinateSystem: 'geo',
                data: lines.map(l => ({
                  coords: l.coords,
                  value: l.value,
                  label: l.label,
                })),
                effect: {
                  show: true,
                  symbol: 'arrow',
                  symbolSize: 6,
                  trailLength: 0.2,
                  period: 5,
                },
                lineStyle: {
                  color: '#5b8ff9',
                  width: 1.2,
                  opacity: 0.5,
                  curveness,
                },
              },
              {
                type: 'effectScatter',
                coordinateSystem: 'geo',
                data: Array.from(targets.values()).map(tp => ({
                  value: [tp.coord[0], tp.coord[1], tp.v],
                })),
                symbolSize: 8,
                rippleEffect: { brushType: 'stroke', scale: 3.5 },
                itemStyle: { color: '#ffd666' },
              },
            ],
          },
          true,
        );
      })
      .catch(e => {
        if (alive) setError(String(e?.message || e));
      });
    return () => {
      alive = false;
    };
  }, [mapScope, lines, metricLabel, curveness]);

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
