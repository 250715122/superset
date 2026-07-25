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
import {
  ChartProps,
  ensureIsArray,
  getColumnLabel,
  getMetricLabel,
} from '@superset-ui/core';

export interface GeoPoint {
  lon: number;
  lat: number;
  value: number;
  label: string;
  raw: unknown; // 第一个维度的原始值，用于 cross-filter
}

export default function transformProps(chartProps: ChartProps) {
  const { width, height, formData, queriesData, hooks, filterState } =
    chartProps;
  const {
    lonCol,
    latCol,
    groupby,
    metric = '',
    mapScope = 'china',
    rippleEffect = false,
    maxPointSize = 24,
    numberFormat = 'SMART_NUMBER',
  } = formData as any;
  const { setDataMask = () => {} } = hooks;
  const emitCrossFilters = (chartProps as any).emitCrossFilters;

  const lonName = getColumnLabel(lonCol);
  const latName = getColumnLabel(latCol);
  const dimNames = ensureIsArray(groupby).map(getColumnLabel);
  const metricLabel = getMetricLabel(metric);
  const data = (queriesData[0]?.data || []) as Record<string, unknown>[];

  const points: GeoPoint[] = [];
  data.forEach(row => {
    const lon = Number(row[lonName]);
    const lat = Number(row[latName]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return;
    const value = Number(row[metricLabel]);
    points.push({
      lon,
      lat,
      value: Number.isFinite(value) ? value : 0,
      label: dimNames.map(d => String(row[d] ?? '')).join(' / '),
      raw: dimNames.length ? row[dimNames[0]] : null,
    });
  });

  return {
    width,
    height,
    mapScope,
    points,
    dimName: dimNames.length ? dimNames[0] : null,
    metricLabel,
    rippleEffect: Boolean(rippleEffect),
    maxPointSize: Number(maxPointSize) || 24,
    numberFormat,
    emitCrossFilters,
    setDataMask,
    filterState,
  };
}
