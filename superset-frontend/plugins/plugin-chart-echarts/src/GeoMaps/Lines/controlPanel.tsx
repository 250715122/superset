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

function coordControl(name: string, label: string) {
  return {
    name,
    config: {
      ...sharedControls.entity,
      clearable: false,
      label: t(label),
    },
  };
}

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Query'),
      expanded: true,
      controlSetRows: [
        [coordControl('src_lon_col', '起点经度列')],
        [coordControl('src_lat_col', '起点纬度列')],
        [coordControl('dst_lon_col', '终点经度列')],
        [coordControl('dst_lat_col', '终点纬度列')],
        [
          {
            name: 'groupby',
            config: {
              ...sharedControls.groupby,
              label: t('明细维度'),
              description: t('悬停提示中展示的维度'),
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
            name: 'curveness',
            config: {
              type: 'SliderControl',
              label: t('飞线弧度'),
              renderTrigger: true,
              min: 0,
              max: 0.8,
              step: 0.1,
              default: 0.3,
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
