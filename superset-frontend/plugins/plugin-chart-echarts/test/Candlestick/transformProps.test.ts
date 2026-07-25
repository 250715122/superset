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
  GenericDataType,
  SqlaFormData,
  supersetTheme,
} from '@superset-ui/core';
import transformProps from '../../src/Candlestick/transformProps';
import { CandlestickChartProps } from '../../src/Candlestick/types';

describe('Candlestick transformProps', () => {
  const formData: SqlaFormData = {
    datasource: '3__table',
    metric_open: 'open',
    metric_close: 'close',
    metric_low: 'low',
    metric_high: 'high',
    x_axis: 'ds',
    x_axis_time_format: '%Y-%m-%d',
    zoomable: true,
    viz_type: 'candlestick',
  };
  const chartProps = new ChartProps({
    formData,
    width: 800,
    height: 600,
    queriesData: [
      {
        colnames: ['ds', 'open', 'close', 'low', 'high'],
        coltypes: [
          GenericDataType.Temporal,
          GenericDataType.Numeric,
          GenericDataType.Numeric,
          GenericDataType.Numeric,
          GenericDataType.Numeric,
        ],
        data: [
          {
            ds: 1735689600000, // 2025-01-01
            open: 10,
            close: 12,
            low: 9,
            high: 13,
          },
          {
            ds: 1735776000000, // 2025-01-02
            open: 12,
            close: 11,
            low: 10,
            high: 14,
          },
        ],
      },
    ],
    theme: supersetTheme,
  });

  it('should map OHLC metrics to candlestick series data', () => {
    const props = transformProps(chartProps as CandlestickChartProps);
    const series = props.echartOptions.series as Record<string, any>[];

    expect(series).toHaveLength(1);
    expect(series[0].type).toBe('candlestick');
    // ECharts candlestick dimension order: [open, close, lowest, highest]
    expect(series[0].data).toEqual([
      [10, 12, 9, 13],
      [12, 11, 10, 14],
    ]);
  });

  it('should format the time axis and enable data zoom', () => {
    const props = transformProps(chartProps as CandlestickChartProps);
    const xAxis = props.echartOptions.xAxis as Record<string, any>;
    const dataZoom = props.echartOptions.dataZoom as Record<string, any>[];

    expect(xAxis.type).toBe('category');
    expect(xAxis.data).toEqual(['2025-01-01', '2025-01-02']);
    expect(dataZoom).toHaveLength(2);
    expect(dataZoom.map(({ type }) => type)).toEqual(['inside', 'slider']);
  });
});
