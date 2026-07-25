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
  const { width, height, formData, queriesData, hooks, filterState } =
    chartProps;
  const {
    entity,
    cityColumn,
    lonCol,
    latCol,
    detailColumns,
    metric = '',
    mapScope = 'china',
    initialZoom = 1,
    initialCenter = '',
    showLabels = true,
    showRanking = false,
    rankPageSize = 10,
    rankWidth = 180,
    rankHeight = 0,
    rankPosition = 'left',
    rankMarginX = 8,
    rankMarginTop = 8,
    enableDrill = true,
    allowRoam = true,
    labelFontSize = 10,
    pointSize = 9,
    numberFormat = 'SMART_NUMBER',
    linearColorScheme,
  } = formData as any;
  const { setDataMask = () => {} } = hooks;
  const emitCrossFilters = (chartProps as any).emitCrossFilters;

  const entityName = getColumnLabel(entity);
  const cityName = cityColumn ? getColumnLabel(cityColumn) : null;
  const lonName = lonCol ? getColumnLabel(lonCol) : null;
  const latName = latCol ? getColumnLabel(latCol) : null;
  const detailNames: string[] = (
    Array.isArray(detailColumns) ? detailColumns : []
  ).map(getColumnLabel);
  const metricLabel = getMetricLabel(metric);
  const data = (queriesData[0]?.data || []) as Record<string, unknown>[];
  const rows = data
    .map(row => ({
      region: row[entityName],
      city: cityName ? row[cityName] : null,
      lon: lonName ? Number(row[lonName]) : NaN,
      lat: latName ? Number(row[latName]) : NaN,
      value: Number(row[metricLabel]),
      detail: Object.fromEntries(detailNames.map(c => [c, row[c]])),
    }))
    .filter(p => p.region !== null && p.region !== undefined);

  const colors = getSequentialSchemeRegistry().get(linearColorScheme)
    ?.colors ?? ['#dbe9ff', '#5b8ff9', '#1f3f8f'];

  // "104,38" -> [104, 38]；非法输入按未设置处理
  let centerPair: [number, number] | null = null;
  if (typeof initialCenter === 'string' && initialCenter.trim()) {
    const parts = initialCenter.split(/[,，]/).map(s => Number(s.trim()));
    if (parts.length === 2 && parts.every(Number.isFinite)) {
      centerPair = [parts[0], parts[1]];
    }
  }

  return {
    width,
    height,
    mapScope,
    initialZoom: Number(initialZoom) > 0 ? Number(initialZoom) : 1,
    initialCenter: centerPair,
    entityName,
    cityName,
    detailNames,
    hasCoords: Boolean(lonName && latName),
    rows,
    showLabels: Boolean(showLabels),
    showRanking: Boolean(showRanking),
    rankPageSize: Math.max(1, Number(rankPageSize) || 10),
    rankWidth: Number(rankWidth) || 180,
    rankHeight: Math.max(0, Number(rankHeight) || 0),
    rankPosition: rankPosition === 'right' ? 'right' : 'left',
    rankMarginX: Math.max(0, Number(rankMarginX) || 0),
    rankMarginTop: Math.max(0, Number(rankMarginTop) || 0),
    enableDrill: Boolean(enableDrill),
    allowRoam: Boolean(allowRoam),
    labelFontSize: Number(labelFontSize) || 10,
    pointSize: Number(pointSize) || 9,
    numberFormat,
    colors,
    emitCrossFilters,
    setDataMask,
    filterState,
  };
}
