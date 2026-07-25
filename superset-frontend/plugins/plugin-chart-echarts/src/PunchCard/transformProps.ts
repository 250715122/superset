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
  getColumnLabel,
  getMetricLabel,
  getTimeFormatter,
  getValueFormatter,
  tooltipHtml,
  QueryFormColumn,
} from '@superset-ui/core';
import type { ComposeOption } from 'echarts/core';
import type { ScatterSeriesOption } from 'echarts/charts';
import type { CallbackDataParams } from 'echarts/types/src/util/types';
import { PunchCardChartProps, PunchCardTransformedProps } from './types';
import { getDefaultTooltip } from '../utils/tooltip';
import { Refs } from '../types';
import { defaultGrid } from '../defaults';

type EChartsOption = ComposeOption<ScatterSeriesOption>;

const DEFAULT_MAX_SYMBOL_SIZE = 40;
const MIN_SYMBOL_SIZE = 4;

function extractUniqueValues(
  data: Record<string, DataRecordValue>[],
  columnName: string,
): DataRecordValue[] {
  const uniqueSet = new Set<DataRecordValue>();
  data.forEach(row => {
    const value = row[columnName];
    if (value !== null && value !== undefined) {
      uniqueSet.add(value);
    }
  });
  return Array.from(uniqueSet);
}

function sortAxisValues(
  values: DataRecordValue[],
  data: Record<string, DataRecordValue>[],
  sortOption: string | undefined,
  metricLabel: string,
  axisColumn: string,
): DataRecordValue[] {
  if (!sortOption) {
    return values;
  }
  const isAscending = sortOption.includes('asc');
  if (sortOption.includes('value')) {
    const valueMap = new Map<DataRecordValue, number>();
    data.forEach(row => {
      const axisValue = row[axisColumn];
      const metricValue = row[metricLabel];
      if (
        axisValue !== null &&
        axisValue !== undefined &&
        typeof metricValue === 'number'
      ) {
        valueMap.set(axisValue, (valueMap.get(axisValue) || 0) + metricValue);
      }
    });
    return [...values].sort((a, b) => {
      const diff = (valueMap.get(a) || 0) - (valueMap.get(b) || 0);
      return isAscending ? diff : -diff;
    });
  }
  return [...values].sort((a, b) => {
    const comparison = String(a).localeCompare(String(b), undefined, {
      numeric: true,
    });
    return isAscending ? comparison : -comparison;
  });
}

// Mirrors the ECharts "scatter-punchCard" example: both axes are categorical
// and the metric value is encoded as the size of each point.
// https://echarts.apache.org/examples/zh/editor.html?c=scatter-punchCard
export default function transformProps(
  chartProps: PunchCardChartProps,
): PunchCardTransformedProps {
  const refs: Refs = {};
  const { width, height, formData, queriesData, datasource } = chartProps;
  const {
    colorScheme,
    currencyFormat,
    groupby,
    metric = '',
    maxSymbolSize = DEFAULT_MAX_SYMBOL_SIZE,
    sliceId,
    sortXAxis,
    sortYAxis,
    xAxisLabelRotation,
    xAxisTimeFormat,
    yAxisFormat,
  } = formData;
  const metricLabel = getMetricLabel(metric);
  const xAxisLabel = getColumnLabel(formData.xAxis);
  const yAxisLabel = getColumnLabel(groupby as unknown as QueryFormColumn);
  const { data, colnames, coltypes } = queriesData[0];
  const { columnFormats = {}, currencyFormats = {} } = datasource;

  const colorScale = CategoricalColorNamespace.getScale(colorScheme as string);
  const pointColor = colorScale(metricLabel, sliceId);

  const getAxisFormatter =
    (colType: GenericDataType) => (value: number | string) => {
      if (colType === GenericDataType.Temporal) {
        return getTimeFormatter(xAxisTimeFormat)(
          typeof value === 'string' ? Number.parseInt(value, 10) : value,
        );
      }
      return String(value);
    };
  const xAxisFormatter = getAxisFormatter(coltypes[0]);
  const yAxisFormatter = getAxisFormatter(coltypes[1]);
  const valueFormatter = getValueFormatter(
    metric,
    currencyFormats,
    columnFormats,
    yAxisFormat,
    currencyFormat,
  );

  const xAxisColumnName = colnames[0];
  const yAxisColumnName = colnames[1];

  const sortedXAxisValues = sortAxisValues(
    extractUniqueValues(data, xAxisColumnName),
    data,
    sortXAxis,
    metricLabel,
    xAxisColumnName,
  );
  const sortedYAxisValues = sortAxisValues(
    extractUniqueValues(data, yAxisColumnName),
    data,
    sortYAxis,
    metricLabel,
    yAxisColumnName,
  );
  const xAxisIndexMap = new Map<DataRecordValue, number>(
    sortedXAxisValues.map((value, index) => [value, index]),
  );
  const yAxisIndexMap = new Map<DataRecordValue, number>(
    sortedYAxisValues.map((value, index) => [value, index]),
  );

  const maxValue = data.reduce((acc, row) => {
    const value = row[metricLabel];
    return typeof value === 'number' && value > acc ? value : acc;
  }, 0);

  const seriesData = data.flatMap(row => {
    const xIndex = xAxisIndexMap.get(row[xAxisColumnName]);
    const yIndex = yAxisIndexMap.get(row[yAxisColumnName]);
    const value = row[metricLabel];
    if (xIndex === undefined || yIndex === undefined || value === null) {
      return [];
    }
    return [[xIndex, yIndex, value]];
  });

  const series: ScatterSeriesOption[] = [
    {
      name: metricLabel,
      type: 'scatter',
      data: seriesData as ScatterSeriesOption['data'],
      symbolSize: (val: number[]) => {
        if (!maxValue || typeof val?.[2] !== 'number') {
          return MIN_SYMBOL_SIZE;
        }
        return Math.max(MIN_SYMBOL_SIZE, (val[2] / maxValue) * maxSymbolSize);
      },
      itemStyle: {
        color: pointColor,
        opacity: 0.8,
      },
      emphasis: {
        itemStyle: {
          opacity: 1,
          shadowBlur: 10,
        },
      },
    },
  ];

  const echartOptions: EChartsOption = {
    grid: {
      ...defaultGrid,
      containLabel: true,
    },
    series,
    tooltip: {
      ...getDefaultTooltip(refs),
      formatter: (params: CallbackDataParams) => {
        const paramsValue = params.value as (string | number)[];
        const x = sortedXAxisValues[paramsValue?.[0] as number];
        const y = sortedYAxisValues[paramsValue?.[1] as number];
        const value = paramsValue?.[2] as number | null | undefined;
        const title = `${xAxisFormatter(x as number | string)} (${yAxisFormatter(y as number | string)})`;
        return tooltipHtml([[metricLabel, valueFormatter(value)]], title);
      },
    },
    xAxis: {
      type: 'category',
      data: sortedXAxisValues,
      boundaryGap: true,
      splitLine: {
        show: true,
        lineStyle: {
          type: 'dashed',
        },
      },
      axisLabel: {
        formatter: xAxisFormatter,
        rotate: xAxisLabelRotation,
      },
      name: xAxisLabel,
    },
    yAxis: {
      type: 'category',
      data: sortedYAxisValues,
      splitLine: {
        show: true,
        lineStyle: {
          type: 'dashed',
        },
      },
      axisLabel: {
        formatter: yAxisFormatter,
      },
      name: yAxisLabel,
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
