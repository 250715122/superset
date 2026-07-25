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
import { CandlestickChartProps, CandlestickFormData } from './types';
import { EchartsChartPlugin } from '../types';

export default class EchartsCandlestickChartPlugin extends EchartsChartPlugin<
  CandlestickFormData,
  CandlestickChartProps
> {
  constructor() {
    super({
      buildQuery,
      controlPanel,
      loadChart: () => import('./Candlestick'),
      metadata: {
        behaviors: [Behavior.InteractiveChart],
        category: t('Evolution'),
        credits: ['https://echarts.apache.org'],
        description: t(
          'Candlestick (K-line) chart showing open, close, lowest and highest values for each period. Commonly used for financial data.',
        ),
        name: t('Candlestick Chart'),
        tags: [t('ECharts'), t('Time'), t('Financial'), t('Trend')],
        thumbnail,
      },
      transformProps,
    });
  }
}
