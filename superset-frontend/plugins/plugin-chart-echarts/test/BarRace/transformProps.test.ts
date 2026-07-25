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
import transformProps from '../../src/BarRace/transformProps';
import { BarRaceChartProps } from '../../src/BarRace/types';

describe('BarRace transformProps', () => {
  const formData: SqlaFormData = {
    colorScheme: 'bnbColors',
    datasource: '3__table',
    metric: 'count',
    x_axis: 'year',
    // the control panel overrides groupby to be single-valued
    groupby: 'country' as unknown as QueryFormColumn[],
    max_bars: 5,
    frame_duration: 2000,
    loop: false,
    viz_type: 'bar_race',
  };
  const chartProps = new ChartProps({
    formData,
    width: 800,
    height: 600,
    queriesData: [
      {
        colnames: ['year', 'country', 'count'],
        coltypes: [
          GenericDataType.Numeric,
          GenericDataType.String,
          GenericDataType.Numeric,
        ],
        data: [
          { year: 2000, country: 'China', count: 10 },
          { year: 2000, country: 'USA', count: 20 },
          { year: 2001, country: 'China', count: 30 },
        ],
      },
    ],
    theme: supersetTheme,
  });

  it('should group rows into one frame per x-axis value', () => {
    const props = transformProps(chartProps as BarRaceChartProps);

    expect(props.categories).toEqual(['China', 'USA']);
    expect(props.frames).toHaveLength(2);
    expect(props.frames[0].title).toBe('2000');
    expect(props.frames[0].values).toEqual([10, 20]);
    // missing category values are filled with null
    expect(props.frames[1].title).toBe('2001');
    expect(props.frames[1].values).toEqual([30, null]);
  });

  it('should pass through animation settings', () => {
    const props = transformProps(chartProps as BarRaceChartProps);

    expect(props.maxBars).toBe(5);
    expect(props.frameDuration).toBe(2000);
    expect(props.loop).toBe(false);
    expect(props.colors).toHaveLength(2);
  });
});
