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
import { AnnotationType, Behavior, t } from '@superset-ui/core';
import type { SeriesOption } from 'echarts';
import {
  EchartsTimeseriesChartProps,
  EchartsTimeseriesFormData,
  EchartsTimeseriesSeriesType,
} from '../../types';
import { EchartsChartPlugin } from '../../../types';
import buildQuery from '../../buildQuery';
import controlPanel from '../Bar/controlPanel';
import transformProps from '../../transformProps';
import thumbnail from './images/thumbnail.png';

// Mirrors the ECharts "bar-animation-delay" example: bars pop in with a
// staggered elasticOut entrance instead of rendering all at once.
// https://echarts.apache.org/examples/zh/editor.html?c=bar-animation-delay
const animatedBarTransformProps = (chartProps: EchartsTimeseriesChartProps) => {
  const props = transformProps({
    ...chartProps,
    formData: {
      ...chartProps.formData,
      seriesType: EchartsTimeseriesSeriesType.Bar,
    },
  });
  const series = (props.echartOptions.series ?? []) as SeriesOption[];
  return {
    ...props,
    echartOptions: {
      ...props.echartOptions,
      animation: true,
      animationEasing: 'elasticOut',
      animationDelayUpdate: (idx: number) => idx * 5,
      series: series.map(s => ({
        ...s,
        animationDelay: (idx: number) => idx * 10,
      })),
    },
  };
};

export default class EchartsTimeseriesBarAnimatedChartPlugin extends EchartsChartPlugin<
  EchartsTimeseriesFormData,
  EchartsTimeseriesChartProps
> {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('../../EchartsTimeseries'),
      metadata: {
        behaviors: [
          Behavior.InteractiveChart,
          Behavior.DrillToDetail,
          Behavior.DrillBy,
        ],
        category: t('Evolution'),
        credits: ['https://echarts.apache.org'],
        description: t(
          'Bar Chart with a staggered entrance animation, where each bar pops in with an elastic effect and an index-based delay.',
        ),
        supportedAnnotationTypes: [
          AnnotationType.Event,
          AnnotationType.Formula,
          AnnotationType.Interval,
          AnnotationType.Timeseries,
        ],
        name: t('Bar Chart (Animated)'),
        tags: [
          t('ECharts'),
          t('Predictive'),
          t('Advanced-Analytics'),
          t('Time'),
          t('Transformable'),
          t('Stacked'),
          t('Bar'),
        ],
        thumbnail,
      },
      transformProps: animatedBarTransformProps,
    });
  }
}
