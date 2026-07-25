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
  CategoricalColorNamespace,
  DataRecordValue,
  GenericDataType,
  getMetricLabel,
  getTimeFormatter,
  getValueFormatter,
} from '@superset-ui/core';
import {
  BarRaceChartProps,
  BarRaceFrame,
  BarRaceTransformedProps,
} from './types';

const DEFAULT_FRAME_DURATION = 1000;
const DEFAULT_MAX_BARS = 10;

// Mirrors the ECharts "bar-race-country" example: bars are re-sorted in place
// as the animation steps through the values of the frame (time) column.
// https://echarts.apache.org/examples/zh/editor.html?c=bar-race-country
export default function transformProps(
  chartProps: BarRaceChartProps,
): BarRaceTransformedProps {
  const { width, height, formData, queriesData, datasource } = chartProps;
  const {
    colorScheme,
    currencyFormat,
    frameDuration,
    loop = true,
    maxBars,
    metric = '',
    sliceId,
    xAxisTimeFormat,
    yAxisFormat,
  } = formData;
  const metricLabel = getMetricLabel(metric);
  const { data, colnames, coltypes } = queriesData[0];
  const { columnFormats = {}, currencyFormats = {} } = datasource;

  const frameColumnName = colnames[0];
  const categoryColumnName = colnames[1];

  const frameFormatter =
    coltypes[0] === GenericDataType.Temporal
      ? (value: DataRecordValue) => {
          const temporal =
            value instanceof Date || typeof value === 'number'
              ? value
              : Number(value);
          return getTimeFormatter(xAxisTimeFormat)(temporal) as string;
        }
      : (value: DataRecordValue) => String(value);

  const frameKeys: DataRecordValue[] = [];
  const frameKeySet = new Set<DataRecordValue>();
  const categories: string[] = [];
  const categoryIndexMap = new Map<string, number>();
  data.forEach(row => {
    const frameKey = row[frameColumnName];
    if (frameKey !== null && frameKey !== undefined) {
      if (!frameKeySet.has(frameKey)) {
        frameKeySet.add(frameKey);
        frameKeys.push(frameKey);
      }
    }
    const category = String(row[categoryColumnName]);
    if (!categoryIndexMap.has(category)) {
      categoryIndexMap.set(category, categories.length);
      categories.push(category);
    }
  });

  const frames: BarRaceFrame[] = frameKeys.map(frameKey => ({
    title: frameFormatter(frameKey),
    values: categories.map(() => null),
  }));
  const frameIndexMap = new Map<DataRecordValue, number>(
    frameKeys.map((key, index) => [key, index]),
  );
  data.forEach(row => {
    const frameIndex = frameIndexMap.get(row[frameColumnName]);
    const categoryIndex = categoryIndexMap.get(String(row[categoryColumnName]));
    const value = row[metricLabel];
    if (
      frameIndex !== undefined &&
      categoryIndex !== undefined &&
      typeof value === 'number'
    ) {
      frames[frameIndex].values[categoryIndex] = value;
    }
  });

  const colorScale = CategoricalColorNamespace.getScale(colorScheme as string);
  const colors = categories.map(category => colorScale(category, sliceId));

  const valueFormatter = getValueFormatter(
    metric,
    currencyFormats,
    columnFormats,
    yAxisFormat,
    currencyFormat,
  );

  return {
    width,
    height,
    categories,
    colors,
    frames,
    frameDuration: Number(frameDuration) || DEFAULT_FRAME_DURATION,
    loop: Boolean(loop),
    maxBars: maxBars || DEFAULT_MAX_BARS,
    valueFormatter,
    formData,
  };
}
