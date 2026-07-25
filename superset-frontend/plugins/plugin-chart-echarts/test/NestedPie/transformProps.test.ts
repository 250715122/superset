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
import transformProps from '../../src/NestedPie/transformProps';
import { NestedPieChartProps } from '../../src/NestedPie/types';

describe('NestedPie transformProps', () => {
  const formData: SqlaFormData = {
    colorScheme: 'bnbColors',
    datasource: '3__table',
    metric: 'count',
    groupby: ['category', 'subcategory'],
    viz_type: 'nested_pie',
  };
  const chartProps = new ChartProps({
    formData,
    width: 800,
    height: 600,
    queriesData: [
      {
        colnames: ['category', 'subcategory', 'count'],
        coltypes: [
          GenericDataType.String,
          GenericDataType.String,
          GenericDataType.Numeric,
        ],
        data: [
          { category: 'Search', subcategory: 'Google', count: 100 },
          { category: 'Search', subcategory: 'Bing', count: 30 },
          { category: 'Direct', subcategory: 'Direct', count: 50 },
        ],
      },
    ],
    theme: supersetTheme,
  });

  it('should build inner and outer pie series', () => {
    const props = transformProps(chartProps as NestedPieChartProps);
    const series = props.echartOptions.series as Record<string, any>[];

    expect(series).toHaveLength(2);
    expect(series[0].type).toBe('pie');
    expect(series[1].type).toBe('pie');

    // inner ring aggregates the first dimension
    const innerData = series[0].data as { name: string; value: number }[];
    expect(innerData.map(({ name, value }) => [name, value])).toEqual([
      ['Search', 130],
      ['Direct', 50],
    ]);

    // outer ring keeps the second dimension breakdown
    const outerData = series[1].data as { name: string; value: number }[];
    expect(outerData.map(({ name, value }) => [name, value])).toEqual([
      ['Google', 100],
      ['Bing', 30],
      ['Direct', 50],
    ]);
  });

  it('should render the rings as concentric circles', () => {
    const props = transformProps(chartProps as NestedPieChartProps);
    const series = props.echartOptions.series as Record<string, any>[];

    expect(series[0].radius).toEqual(['0%', '35%']);
    expect(series[1].radius).toEqual(['45%', '60%']);
  });
});
