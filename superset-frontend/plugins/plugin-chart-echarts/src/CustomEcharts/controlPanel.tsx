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
import { t, validateNonEmpty } from '@superset-ui/core';
import { ControlPanelConfig } from '@superset-ui/chart-controls';

export const DEFAULT_OPTION_CODE = `// Available variables:
//   echarts - the full ECharts namespace (echarts.graphic, echarts.registerMap, ...)
//   data    - query result rows, as an array of objects
// Return an ECharts option object, or a Promise resolving to one.
return {
  tooltip: {},
  xAxis: {
    type: 'category',
    data: data.map(row => String(Object.values(row)[0])),
  },
  yAxis: { type: 'value' },
  series: [
    {
      type: 'bar',
      data: data.map(row => Number(Object.values(row)[1])),
    },
  ],
};
`;

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Query'),
      expanded: true,
      controlSetRows: [
        ['groupby'],
        ['metrics'],
        ['adhoc_filters'],
        ['row_limit'],
      ],
    },
    {
      label: t('ECharts Option'),
      expanded: true,
      controlSetRows: [
        [
          {
            name: 'echarts_option_code',
            config: {
              type: 'TextAreaControl',
              language: 'javascript',
              label: t('ECharts option code'),
              description: t(
                'JavaScript code that returns an ECharts option object. The full "echarts" namespace and the query result "data" are in scope. Only trusted editors should modify this, as the code is executed in the browser of every viewer.',
              ),
              height: 400,
              default: DEFAULT_OPTION_CODE,
              renderTrigger: true,
              validators: [validateNonEmpty],
            },
          },
        ],
      ],
    },
  ],
  controlOverrides: {
    groupby: {
      validators: [],
      description: t(
        'Optional dimensions exposed to the code as columns of "data"',
      ),
    },
    metrics: {
      validators: [],
      description: t(
        'Optional metrics exposed to the code as columns of "data"',
      ),
    },
  },
};

export default config;
