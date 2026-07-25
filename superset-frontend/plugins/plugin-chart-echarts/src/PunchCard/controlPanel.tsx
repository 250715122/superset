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
  getStandardizedControls,
} from '@superset-ui/chart-controls';
import { xAxisLabelRotation } from '../controls';

const sortAxisChoices = [
  ['alpha_asc', t('Axis ascending')],
  ['alpha_desc', t('Axis descending')],
  ['value_asc', t('Metric ascending')],
  ['value_desc', t('Metric descending')],
];

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
        [
          {
            name: 'sort_x_axis',
            config: {
              type: 'SelectControl',
              label: t('Sort X Axis'),
              choices: sortAxisChoices,
              renderTrigger: false,
              clearable: true,
            },
          },
        ],
        [
          {
            name: 'sort_y_axis',
            config: {
              type: 'SelectControl',
              label: t('Sort Y Axis'),
              choices: sortAxisChoices,
              renderTrigger: false,
              clearable: true,
            },
          },
        ],
      ],
    },
    {
      label: t('Chart Options'),
      expanded: true,
      controlSetRows: [
        ['color_scheme'],
        [
          {
            name: 'max_symbol_size',
            config: {
              type: 'SliderControl',
              label: t('Max point size'),
              renderTrigger: true,
              min: 10,
              max: 100,
              default: 40,
              step: 1,
              description: t(
                'Diameter, in pixels, of the point representing the largest metric value',
              ),
            },
          },
        ],
        ['y_axis_format'],
        ['x_axis_time_format'],
        [xAxisLabelRotation],
        ['currency_format'],
      ],
    },
  ],
  controlOverrides: {
    groupby: {
      label: t('Y-Axis'),
      description: t('Dimension to use on y-axis.'),
      multi: false,
      validators: [validateNonEmpty],
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
