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

export interface GeoLine {
  coords: [[number, number], [number, number]];
  value: number;
  label: string;
}

export default function transformProps(chartProps: ChartProps) {
  const { width, height, formData, queriesData } = chartProps;
  const {
    srcLonCol,
    srcLatCol,
    dstLonCol,
    dstLatCol,
    groupby,
    metric = '',
    mapScope = 'china',
    curveness = 0.3,
  } = formData as any;

  const cols = [srcLonCol, srcLatCol, dstLonCol, dstLatCol].map(getColumnLabel);
  const dimNames = ensureIsArray(groupby).map(getColumnLabel);
  const metricLabel = getMetricLabel(metric);
  const data = (queriesData[0]?.data || []) as Record<string, unknown>[];

  const lines: GeoLine[] = [];
  data.forEach(row => {
    const nums = cols.map(c => Number(row[c]));
    if (nums.some(n => !Number.isFinite(n))) return;
    const value = Number(row[metricLabel]);
    lines.push({
      coords: [
        [nums[0], nums[1]],
        [nums[2], nums[3]],
      ],
      value: Number.isFinite(value) ? value : 0,
      label: dimNames.map(d => String(row[d] ?? '')).join(' / '),
    });
  });

  return {
    width,
    height,
    mapScope,
    lines,
    metricLabel,
    curveness: Number(curveness) || 0.3,
  };
}
