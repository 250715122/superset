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
import { Behavior, t } from '@superset-ui/core';
import buildQuery from './buildQuery';
import controlPanel from './controlPanel';
import transformProps from './transformProps';
import thumbnail from './images/thumbnail.png';
import { PunchCardChartProps, PunchCardFormData } from './types';
import { EchartsChartPlugin } from '../types';

export default class EchartsPunchCardChartPlugin extends EchartsChartPlugin<
  PunchCardFormData,
  PunchCardChartProps
> {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('./PunchCard'),
      metadata: {
        behaviors: [Behavior.InteractiveChart],
        category: t('Correlation'),
        credits: ['https://echarts.apache.org'],
        description: t(
          'Visualizes a metric across two categorical dimensions as a grid of points, where the size of each point represents the metric value. Great for spotting patterns such as activity by day of week and hour of day.',
        ),
        name: t('Punch Card Chart'),
        tags: [
          t('ECharts'),
          t('Comparison'),
          t('Density'),
          t('Pattern'),
          t('Scatter'),
        ],
        thumbnail,
      },
      transformProps,
    });
  }
}
