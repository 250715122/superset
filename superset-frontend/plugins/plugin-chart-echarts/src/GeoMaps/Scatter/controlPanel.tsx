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
import { t } from '@superset-ui/core';
import {
  ControlPanelConfig,
  getStandardizedControls,
  sharedControls,
} from '@superset-ui/chart-controls';
import { MAP_CHOICES } from '../common';

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Query'),
      expanded: true,
      controlSetRows: [
        [
          {
            name: 'lon_col',
            config: {
              ...sharedControls.entity,
              clearable: false,
              label: t('经度列'),
              description: t('十进制度经度（如 113.26）'),
            },
          },
        ],
        [
          {
            name: 'lat_col',
            config: {
              ...sharedControls.entity,
              clearable: false,
              label: t('纬度列'),
              description: t('十进制度纬度（如 23.13）'),
            },
          },
        ],
        [
          {
            name: 'groupby',
            config: {
              ...sharedControls.groupby,
              label: t('明细维度'),
              description: t(
                '悬停提示中展示的维度（如设备号、型号）；点击点位时以第一个维度联动',
              ),
            },
          },
        ],
        ['metric'],
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
            name: 'map_scope',
            config: {
              type: 'SelectControl',
              label: t('地图范围'),
              default: 'china',
              choices: MAP_CHOICES,
              clearable: false,
              renderTrigger: true,
            },
          },
        ],
        [
          {
            name: 'ripple_effect',
            config: {
              type: 'CheckboxControl',
              label: t('涟漪特效'),
              default: false,
              renderTrigger: true,
              description: t('点位带动态涟漪（effectScatter），适合强调活跃点'),
            },
          },
        ],
        [
          {
            name: 'max_point_size',
            config: {
              type: 'SliderControl',
              label: t('最大气泡尺寸'),
              renderTrigger: true,
              min: 6,
              max: 60,
              step: 2,
              default: 24,
            },
          },
        ],
        [
          {
            name: 'number_format',
            config: {
              ...sharedControls.y_axis_format,
              label: t('Number format'),
            },
          },
        ],
      ],
    },
  ],
  formDataOverrides: formData => ({
    ...formData,
    metric: getStandardizedControls().shiftMetric(),
  }),
};

export default config;
