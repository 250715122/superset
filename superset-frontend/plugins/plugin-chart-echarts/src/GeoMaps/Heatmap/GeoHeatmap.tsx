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
import { use, init, EChartsType } from 'echarts/core';
import { HeatmapChart } from 'echarts/charts';
import {
  GeoComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { ensureMap } from '../common';

use([HeatmapChart, GeoComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

interface Props {
  width: number;
  height: number;
  mapScope: string;
  points: [number, number, number][];
  pointRadius: number;
  colors: string[];
}

export default function GeoHeatmap(props: Props) {
  const { width, height, mapScope, points, pointRadius, colors } = props;
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
        const maxW = Math.max(1, ...points.map(p => p[2]));
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
            tooltip: { show: false },
            visualMap: {
              min: 0,
              max: maxW,
              left: 8,
              bottom: 8,
              calculable: true,
              inRange: { color: colors },
            },
            series: [
              {
                type: 'heatmap',
                coordinateSystem: 'geo',
                data: points,
                pointSize: pointRadius,
                blurSize: Math.round(pointRadius * 1.6),
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
  }, [mapScope, points, pointRadius, colors]);

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
