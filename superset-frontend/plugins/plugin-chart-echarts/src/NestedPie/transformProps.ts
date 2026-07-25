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
  getMetricLabel,
  getValueFormatter,
  tooltipHtml,
} from '@superset-ui/core';
import type { ComposeOption } from 'echarts/core';
import type { PieSeriesOption } from 'echarts/charts';
import type { CallbackDataParams } from 'echarts/types/src/util/types';
import { NestedPieChartProps, NestedPieTransformedProps } from './types';
import { getDefaultTooltip } from '../utils/tooltip';
import { Refs } from '../types';

type EChartsOption = ComposeOption<PieSeriesOption>;

// Mirrors the ECharts "pie-nest" example: the first dimension forms an inner
// ring and the second dimension a more detailed outer ring.
// https://echarts.apache.org/examples/zh/editor.html?c=pie-nest
export default function transformProps(
  chartProps: NestedPieChartProps,
): NestedPieTransformedProps {
  const refs: Refs = {};
  const { width, height, formData, queriesData, datasource } = chartProps;
  const {
    colorScheme,
    currencyFormat,
    metric = '',
    showLabels = true,
    sliceId,
    yAxisFormat,
  } = formData;
  const metricLabel = getMetricLabel(metric);
  const { data, colnames } = queriesData[0];
  const { columnFormats = {}, currencyFormats = {} } = datasource;

  const dimensions = colnames.filter(col => col !== metricLabel);
  const innerColumn = dimensions[0];
  const outerColumn = dimensions[dimensions.length - 1];

  const colorScale = CategoricalColorNamespace.getScale(colorScheme as string);
  const valueFormatter = getValueFormatter(
    metric,
    currencyFormats,
    columnFormats,
    yAxisFormat,
    currencyFormat,
  );

  const innerTotals = new Map<string, number>();
  const outerData: { name: string; value: number; parent: string }[] = [];
  data.forEach(row => {
    const value = row[metricLabel];
    if (typeof value !== 'number') {
      return;
    }
    const innerName = String(row[innerColumn]);
    innerTotals.set(innerName, (innerTotals.get(innerName) || 0) + value);
    if (outerColumn !== innerColumn) {
      outerData.push({
        name: String(row[outerColumn]),
        value,
        parent: innerName,
      });
    }
  });

  const innerSeries: PieSeriesOption = {
    name: metricLabel,
    type: 'pie',
    selectedMode: 'single',
    radius: ['0%', '35%'],
    label: {
      show: showLabels,
      position: 'inner',
      fontSize: 12,
    },
    labelLine: {
      show: false,
    },
    data: [...innerTotals.entries()].map(([name, value]) => ({
      name,
      value,
      itemStyle: { color: colorScale(name, sliceId) },
    })),
  };

  const outerSeries: PieSeriesOption = {
    name: metricLabel,
    type: 'pie',
    radius: ['45%', '60%'],
    labelLine: {
      length: 20,
    },
    label: {
      show: showLabels,
    },
    data: outerData.map(({ name, value }) => ({
      name,
      value,
      itemStyle: { color: colorScale(name, sliceId) },
    })),
  };

  const series =
    outerData.length > 0 ? [innerSeries, outerSeries] : [innerSeries];

  const echartOptions: EChartsOption = {
    series,
    tooltip: {
      ...getDefaultTooltip(refs),
      trigger: 'item',
      formatter: (params: CallbackDataParams) =>
        tooltipHtml(
          [
            [
              metricLabel,
              valueFormatter(params.value as number),
              `${params.percent}%`,
            ],
          ],
          params.name,
        ),
    },
  };
  return {
    refs,
    echartOptions,
    width,
    height,
    formData,
  };
}
