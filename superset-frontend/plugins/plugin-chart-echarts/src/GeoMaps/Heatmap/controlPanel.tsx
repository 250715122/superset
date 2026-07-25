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
            name: 'point_radius',
            config: {
              type: 'SliderControl',
              label: t('热力点半径'),
              renderTrigger: true,
              min: 4,
              max: 40,
              step: 2,
              default: 14,
            },
          },
        ],
        ['linear_color_scheme'],
      ],
    },
  ],
  formDataOverrides: formData => ({
    ...formData,
    metric: getStandardizedControls().shiftMetric(),
  }),
};

export default config;
