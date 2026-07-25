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
import { ChartProps, SqlaFormData, supersetTheme } from '@superset-ui/core';
import { EchartsTimeseriesChartProps } from '../../../src/types';
import { areaGradientTransformProps } from '../../../src/Timeseries/AreaGradient';
import { DEFAULT_FORM_DATA } from '../../../src/Timeseries/constants';

describe('AreaGradient transformProps', () => {
  const formData: SqlaFormData = {
    ...DEFAULT_FORM_DATA,
    colorScheme: 'bnbColors',
    datasource: '3__table',
    granularity_sqla: '__timestamp',
    metric: ['Sales'],
    groupby: [],
    viz_type: 'echarts_area_gradient',
  };
  const chartProps = new ChartProps({
    formData,
    width: 800,
    height: 600,
    queriesData: [
      {
        data: [
          { Sales: 100, __timestamp: 1609459200000 },
          { Sales: 150, __timestamp: 1612137600000 },
        ],
        colnames: ['Sales', '__timestamp'],
        coltypes: ['BIGINT', 'TIMESTAMP'],
      },
    ],
    theme: supersetTheme,
  });

  it('should fill series areas with a linear gradient of the series color', () => {
    const props = areaGradientTransformProps(
      chartProps as EchartsTimeseriesChartProps,
    );
    const series = props.echartOptions.series as Record<string, any>[];
    const mainSeries = series.filter(
      s => s.type === 'line' && s.areaStyle?.color,
    );
    expect(mainSeries.length).toBeGreaterThan(0);
    mainSeries.forEach(s => {
      expect(s.areaStyle.color.colorStops).toHaveLength(2);
      expect(s.areaStyle.color.colorStops[0].offset).toBe(0);
      expect(s.areaStyle.color.colorStops[1].offset).toBe(1);
      expect(s.emphasis.focus).toBe('series');
    });
  });
});
