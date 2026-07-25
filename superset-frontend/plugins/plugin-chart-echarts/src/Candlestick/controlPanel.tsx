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
import {
  ControlPanelConfig,
  sharedControls,
} from '@superset-ui/chart-controls';

const ohlcMetric = (name: string, label: string, description: string) => ({
  name,
  config: {
    ...sharedControls.metric,
    label,
    description,
    validators: [validateNonEmpty],
  },
});

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Query'),
      expanded: true,
      controlSetRows: [
        ['x_axis'],
        ['time_grain_sqla'],
        [
          ohlcMetric(
            'metric_open',
            t('Open metric'),
            t('Metric for the opening value of each period'),
          ),
        ],
        [
          ohlcMetric(
            'metric_close',
            t('Close metric'),
            t('Metric for the closing value of each period'),
          ),
        ],
        [
          ohlcMetric(
            'metric_low',
            t('Low metric'),
            t('Metric for the lowest value of each period'),
          ),
        ],
        [
          ohlcMetric(
            'metric_high',
            t('High metric'),
            t('Metric for the highest value of each period'),
          ),
        ],
        ['adhoc_filters'],
        ['row_limit'],
      ],
    },
    {
      label: t('Chart Options'),
      expanded: true,
      controlSetRows: [
        [
          {
            name: 'zoomable',
            config: {
              type: 'CheckboxControl',
              label: t('Data Zoom'),
              renderTrigger: true,
              default: true,
              description: t('Enable data zooming controls'),
            },
          },
        ],
        ['x_axis_time_format'],
        ['y_axis_format'],
        ['currency_format'],
      ],
    },
  ],
  controlOverrides: {
    x_axis: {
      description: t('The time column of the OHLC periods.'),
    },
    y_axis_format: {
      label: t('Value Format'),
    },
  },
};

export default config;
