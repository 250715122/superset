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
import { NestedPieChartProps, NestedPieFormData } from './types';
import { EchartsChartPlugin } from '../types';

export default class EchartsNestedPieChartPlugin extends EchartsChartPlugin<
  NestedPieFormData,
  NestedPieChartProps
> {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('./NestedPie'),
      metadata: {
        behaviors: [Behavior.InteractiveChart],
        category: t('Part of a Whole'),
        credits: ['https://echarts.apache.org'],
        description: t(
          'Two-level pie chart where an inner ring shows the totals of a coarse dimension and an outer ring breaks them down by a finer dimension.',
        ),
        name: t('Nested Pie Chart'),
        tags: [
          t('ECharts'),
          t('Categorical'),
          t('Circular'),
          t('Proportional'),
        ],
        thumbnail,
      },
      transformProps,
    });
  }
}
