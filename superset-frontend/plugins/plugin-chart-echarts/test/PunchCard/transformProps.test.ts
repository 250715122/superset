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
  QueryFormColumn,
  SqlaFormData,
  supersetTheme,
} from '@superset-ui/core';
import transformProps from '../../src/PunchCard/transformProps';
import { PunchCardChartProps } from '../../src/PunchCard/types';

describe('PunchCard transformProps', () => {
  const formData: SqlaFormData = {
    colorScheme: 'bnbColors',
    datasource: '3__table',
    granularity_sqla: 'ds',
    metric: 'count',
    x_axis: 'day',
    // the control panel overrides groupby to be single-valued
    groupby: 'hour' as unknown as QueryFormColumn[],
    max_symbol_size: 40,
    viz_type: 'punch_card',
  };
  const chartProps = new ChartProps({
    formData,
    width: 800,
    height: 600,
    queriesData: [
      {
        colnames: ['day', 'hour', 'count'],
        coltypes: [GenericDataType.String, GenericDataType.String],
        data: [
          { day: 'Monday', hour: '8a', count: 10 },
          { day: 'Monday', hour: '9a', count: 5 },
          { day: 'Tuesday', hour: '8a', count: 2 },
        ],
      },
    ],
    theme: supersetTheme,
  });

  it('should map both dimensions to categorical axes and metric to point size', () => {
    const props = transformProps(chartProps as PunchCardChartProps);
    const { echartOptions } = props;
    const xAxis = echartOptions.xAxis as Record<string, any>;
    const yAxis = echartOptions.yAxis as Record<string, any>;
    const series = echartOptions.series as Record<string, any>[];

    expect(xAxis.type).toBe('category');
    expect(xAxis.data).toEqual(['Monday', 'Tuesday']);
    expect(yAxis.type).toBe('category');
    expect(yAxis.data).toEqual(['8a', '9a']);

    expect(series).toHaveLength(1);
    expect(series[0].type).toBe('scatter');
    expect(series[0].data).toEqual([
      [0, 0, 10],
      [0, 1, 5],
      [1, 0, 2],
    ]);
  });

  it('should scale symbol size linearly against the max metric value', () => {
    const props = transformProps(chartProps as PunchCardChartProps);
    const series = props.echartOptions.series as Record<string, any>[];
    const { symbolSize } = series[0];

    expect(symbolSize([0, 0, 10])).toBe(40);
    expect(symbolSize([0, 1, 5])).toBe(20);
    // Tiny values are clamped to a readable minimum
    expect(symbolSize([1, 0, 0.1])).toBe(4);
  });
});
