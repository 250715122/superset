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
import { labelOverlapTransformProps } from '../../../src/Graph/LabelOverlap';
import { EchartsGraphChartProps } from '../../../src/Graph/types';

describe('GraphLabelOverlap transformProps', () => {
  const formData: SqlaFormData = {
    colorScheme: 'bnbColors',
    datasource: '3__table',
    granularity_sqla: 'ds',
    metric: 'count',
    source: 'source_column',
    target: 'target_column',
    category: null,
    viz_type: 'graph_chart_label_overlap',
  };
  const chartProps = new ChartProps({
    formData,
    width: 800,
    height: 600,
    queriesData: [
      {
        colnames: ['source_column', 'target_column', 'count'],
        data: [
          {
            source_column: 'source_value_1',
            target_column: 'target_value_1',
            count: 6,
          },
        ],
      },
    ],
    theme: supersetTheme,
  });

  it('should always show labels and hide overlapping ones', () => {
    const props = labelOverlapTransformProps(
      chartProps as EchartsGraphChartProps,
    );
    const series = props.echartOptions.series as Record<string, any>[];
    expect(series).toHaveLength(1);
    expect(series[0].label.show).toBe(true);
    expect(series[0].label.position).toBe('right');
    expect(series[0].labelLayout).toEqual({ hideOverlap: true });
    expect(series[0].scaleLimit).toEqual({ min: 0.4, max: 2 });
  });
});
