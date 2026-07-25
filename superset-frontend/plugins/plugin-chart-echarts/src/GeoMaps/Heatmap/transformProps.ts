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
  getColumnLabel,
  getMetricLabel,
  getSequentialSchemeRegistry,
} from '@superset-ui/core';

export default function transformProps(chartProps: ChartProps) {
  const { width, height, formData, queriesData } = chartProps;
  const {
    lonCol,
    latCol,
    metric = '',
    mapScope = 'china',
    pointRadius = 14,
    linearColorScheme,
  } = formData as any;

  const lonName = getColumnLabel(lonCol);
  const latName = getColumnLabel(latCol);
  const metricLabel = getMetricLabel(metric);
  const data = (queriesData[0]?.data || []) as Record<string, unknown>[];

  const points: [number, number, number][] = [];
  data.forEach(row => {
    const lon = Number(row[lonName]);
    const lat = Number(row[latName]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return;
    const w = Number(row[metricLabel]);
    points.push([lon, lat, Number.isFinite(w) && w > 0 ? w : 1]);
  });

  const colors = getSequentialSchemeRegistry().get(linearColorScheme)
    ?.colors ?? ['#c6dbef', '#4292c6', '#08306b'];

  return {
    width,
    height,
    mapScope,
    points,
    pointRadius: Number(pointRadius) || 14,
    colors,
  };
}
