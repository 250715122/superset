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
import { EchartsChartPlugin } from '../../types';

export default class EchartsGeoHeatmapChartPlugin extends EchartsChartPlugin {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('./GeoHeatmap'),
      metadata: {
        behaviors: [Behavior.DrillToDetail],
        category: t('Map'),
        credits: ['https://echarts.apache.org'],
        description: t(
          'ECharts 地理热力图：按经纬度点位的密度/权重渲染热力，直观展示地理聚集程度。',
        ),
        name: t('ECharts 地理热力图'),
        tags: [t('ECharts'), t('Geo'), t('2D'), t('Density')],
        thumbnail,
      },
      transformProps,
    });
  }
}
