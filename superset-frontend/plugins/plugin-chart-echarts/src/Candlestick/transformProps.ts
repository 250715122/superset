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
  GenericDataType,
  getMetricLabel,
  getTimeFormatter,
  getValueFormatter,
  tooltipHtml,
} from '@superset-ui/core';
import type { ComposeOption } from 'echarts/core';
import type { CandlestickSeriesOption } from 'echarts/charts';
import type { CallbackDataParams } from 'echarts/types/src/util/types';
import { CandlestickChartProps, CandlestickTransformedProps } from './types';
import { getDefaultTooltip } from '../utils/tooltip';
import { Refs } from '../types';
import { defaultGrid } from '../defaults';

type EChartsOption = ComposeOption<CandlestickSeriesOption>;

const UP_COLOR = '#ec0000';
const UP_BORDER_COLOR = '#8A0000';
const DOWN_COLOR = '#00da3c';
const DOWN_BORDER_COLOR = '#008F28';

// Mirrors the ECharts "candlestick-sh" example: OHLC candles over a time
// axis with optional data zooming.
// https://echarts.apache.org/examples/zh/editor.html?c=candlestick-sh
export default function transformProps(
  chartProps: CandlestickChartProps,
): CandlestickTransformedProps {
  const refs: Refs = {};
  const { width, height, formData, queriesData, datasource } = chartProps;
  const {
    currencyFormat,
    metricOpen,
    metricClose,
    metricLow,
    metricHigh,
    xAxisTimeFormat,
    yAxisFormat,
    zoomable = true,
  } = formData;
  const { data, colnames, coltypes } = queriesData[0];
  const { columnFormats = {}, currencyFormats = {} } = datasource;

  const xAxisColumnName = colnames[0];
  const openLabel = getMetricLabel(metricOpen);
  const closeLabel = getMetricLabel(metricClose);
  const lowLabel = getMetricLabel(metricLow);
  const highLabel = getMetricLabel(metricHigh);

  const xAxisFormatter =
    coltypes[0] === GenericDataType.Temporal
      ? (value: string | number) =>
          getTimeFormatter(xAxisTimeFormat)(
            typeof value === 'string' ? Number.parseInt(value, 10) : value,
          ) as string
      : (value: string | number) => String(value);

  const valueFormatter = getValueFormatter(
    metricClose,
    currencyFormats,
    columnFormats,
    yAxisFormat,
    currencyFormat,
  );

  const categories: string[] = [];
  const seriesData: [number, number, number, number][] = [];
  data.forEach(row => {
    const open = row[openLabel];
    const close = row[closeLabel];
    const low = row[lowLabel];
    const high = row[highLabel];
    if (
      typeof open !== 'number' ||
      typeof close !== 'number' ||
      typeof low !== 'number' ||
      typeof high !== 'number'
    ) {
      return;
    }
    categories.push(xAxisFormatter(row[xAxisColumnName] as string | number));
    // ECharts candlestick dimension order: [open, close, lowest, highest]
    seriesData.push([open, close, low, high]);
  });

  const series: CandlestickSeriesOption[] = [
    {
      name: closeLabel,
      type: 'candlestick',
      data: seriesData,
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_BORDER_COLOR,
        borderColor0: DOWN_BORDER_COLOR,
      },
    },
  ];

  const echartOptions: EChartsOption = {
    grid: {
      ...defaultGrid,
      bottom: zoomable ? 80 : undefined,
      containLabel: true,
    },
    series,
    tooltip: {
      ...getDefaultTooltip(refs),
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
      },
      formatter: (params: CallbackDataParams[]) => {
        const param = params[0];
        // value[0] is the data index added by ECharts for category axes
        const values = (param.value as number[]).slice(1);
        return tooltipHtml(
          [
            [openLabel, valueFormatter(values[0])],
            [closeLabel, valueFormatter(values[1])],
            [lowLabel, valueFormatter(values[2])],
            [highLabel, valueFormatter(values[3])],
          ],
          param.name,
        );
      },
    },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: true,
      axisLine: { onZero: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        formatter: (value: number) => valueFormatter(value),
      },
    },
    dataZoom: zoomable
      ? [
          {
            type: 'inside',
            start: 0,
            end: 100,
          },
          {
            type: 'slider',
            show: true,
            bottom: 20,
            start: 0,
            end: 100,
          },
        ]
      : [],
  };
  return {
    refs,
    echartOptions,
    width,
    height,
    formData,
  };
}
