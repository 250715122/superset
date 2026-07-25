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
import { addAlpha, AnnotationType, Behavior, t } from '@superset-ui/core';
import { graphic } from 'echarts/core';
import type { SeriesOption } from 'echarts';
import type { LineSeriesOption } from 'echarts/charts';
import buildQuery from '../buildQuery';
import controlPanel from '../Area/controlPanel';
import transformProps from '../transformProps';
import thumbnail from './images/thumbnail.png';
import {
  EchartsTimeseriesChartProps,
  EchartsTimeseriesFormData,
} from '../types';
import { EchartsChartPlugin } from '../../types';

// Mirrors the ECharts "area-stack-gradient" example: each series' area is
// filled with a vertical gradient fading from the series color to transparent.
// https://echarts.apache.org/examples/zh/editor.html?c=area-stack-gradient
export const areaGradientTransformProps = (
  chartProps: EchartsTimeseriesChartProps,
) => {
  const props = transformProps({
    ...chartProps,
    formData: { ...chartProps.formData, area: true },
  });
  const series = (props.echartOptions.series ?? []) as SeriesOption[];
  return {
    ...props,
    echartOptions: {
      ...props.echartOptions,
      series: series.map(s => {
        if (s.type !== 'line') {
          return s;
        }
        const lineSeries = s as LineSeriesOption;
        const color = lineSeries.itemStyle?.color;
        if (!lineSeries.areaStyle || typeof color !== 'string') {
          return s;
        }
        return {
          ...lineSeries,
          areaStyle: {
            ...lineSeries.areaStyle,
            color: new graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: addAlpha(color, 0.8) },
              { offset: 1, color: addAlpha(color, 0.1) },
            ]),
          },
          emphasis: {
            ...lineSeries.emphasis,
            focus: 'series',
          },
        };
      }),
    },
  };
};

export default class EchartsAreaGradientChartPlugin extends EchartsChartPlugin<
  EchartsTimeseriesFormData,
  EchartsTimeseriesChartProps
> {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('../EchartsTimeseries'),
      metadata: {
        behaviors: [
          Behavior.InteractiveChart,
          Behavior.DrillToDetail,
          Behavior.DrillBy,
        ],
        category: t('Evolution'),
        credits: ['https://echarts.apache.org'],
        description: t(
          'Area chart variant where each stacked area is filled with a vertical gradient fading from the series color to transparent.',
        ),
        supportedAnnotationTypes: [
          AnnotationType.Event,
          AnnotationType.Formula,
          AnnotationType.Interval,
          AnnotationType.Timeseries,
        ],
        name: t('Area Chart (Gradient)'),
        tags: [
          t('ECharts'),
          t('Predictive'),
          t('Advanced-Analytics'),
          t('Time'),
          t('Line'),
          t('Transformable'),
          t('Stacked'),
        ],
        thumbnail,
      },
      transformProps: areaGradientTransformProps,
    });
  }
}
