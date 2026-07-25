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
  formatSelectOptions,
  getStandardizedControls,
} from '@superset-ui/chart-controls';

const config: ControlPanelConfig = {
  controlPanelSections: [
    {
      label: t('Query'),
      expanded: true,
      controlSetRows: [
        ['x_axis'],
        ['time_grain_sqla'],
        ['groupby'],
        ['metric'],
        ['adhoc_filters'],
        ['row_limit'],
      ],
    },
    {
      label: t('Chart Options'),
      expanded: true,
      controlSetRows: [
        ['color_scheme'],
        [
          {
            name: 'max_bars',
            config: {
              type: 'SliderControl',
              label: t('Max bars'),
              renderTrigger: true,
              min: 3,
              max: 30,
              default: 10,
              step: 1,
              description: t(
                'Maximum number of bars displayed at the same time',
              ),
            },
          },
        ],
        [
          {
            name: 'frame_duration',
            config: {
              type: 'SelectControl',
              freeForm: true,
              clearable: false,
              label: t('Frame duration (ms)'),
              renderTrigger: true,
              choices: formatSelectOptions([500, 1000, 2000, 3000]),
              default: 1000,
              description: t(
                'Time, in milliseconds, between two animation frames',
              ),
            },
          },
        ],
        [
          {
            name: 'loop',
            config: {
              type: 'CheckboxControl',
              label: t('Loop'),
              renderTrigger: true,
              default: true,
              description: t(
                'Whether to restart the animation once the last frame is reached',
              ),
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
    groupby: {
      label: t('Dimension'),
      description: t('Dimension whose values race against each other.'),
      multi: false,
      validators: [validateNonEmpty],
    },
    x_axis: {
      description: t(
        'Column that drives the animation frames, typically a time column.',
      ),
    },
    y_axis_format: {
      label: t('Value Format'),
    },
  },
  formDataOverrides: formData => ({
    ...formData,
    metric: getStandardizedControls().shiftMetric(),
  }),
};

export default config;
