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
  formatSelectOptions,
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
            name: 'entity',
            config: {
              ...sharedControls.entity,
              clearable: false,
              label: t('区域列'),
              description: t(
                '省份/城市/国家名称列，兼容中文简称（如“广东”）与 CN-XX ISO 编码',
              ),
            },
          },
        ],
        [
          {
            name: 'city_column',
            config: {
              ...sharedControls.entity,
              clearable: true,
              validators: [],
              label: t('城市列(下钻)'),
              description: t(
                '可选。地图范围为“中国（省级）”时，配置后点击省份可下钻到该省市级地图',
              ),
            },
          },
        ],
        [
          {
            name: 'lon_col',
            config: {
              ...sharedControls.entity,
              clearable: true,
              validators: [],
              label: t('经度列(设备级下钻)'),
              description: t('可选。配置后城市可继续下钻，在地图上标出明细点位'),
            },
          },
        ],
        [
          {
            name: 'lat_col',
            config: {
              ...sharedControls.entity,
              clearable: true,
              validators: [],
              label: t('纬度列(设备级下钻)'),
            },
          },
        ],
        [
          {
            name: 'detail_columns',
            config: {
              ...sharedControls.groupby,
              label: t('明细列(设备级下钻)'),
              description: t(
                '城市下钻后展示的明细字段；第一列作为标识用于点击联动（如设备号）',
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
              description: t('中国省级 / 指定省份市级 / 世界国家'),
            },
          },
        ],
        [
          {
            name: 'initial_zoom',
            config: {
              type: 'SliderControl',
              label: t('初始缩放'),
              min: 0.5,
              max: 3,
              step: 0.05,
              default: 1,
              renderTrigger: true,
              description: t(
                '中国地图因包含南海诸岛，默认大陆偏小；调大（如 1.6）可让大陆充满画面，缩放拖拽后仍可看到南海。仅作用于顶层视图',
              ),
            },
          },
        ],
        [
          {
            name: 'initial_center',
            config: {
              type: 'TextControl',
              label: t('初始中心(经度,纬度)'),
              default: '',
              renderTrigger: true,
              description: t(
                '如 104,38（聚焦中国大陆）；留空为自动居中。配合初始缩放使用',
              ),
            },
          },
        ],
        [
          {
            name: 'show_labels',
            config: {
              type: 'CheckboxControl',
              label: t('常显数值标签'),
              default: true,
              renderTrigger: true,
              description: t('在区域上直接显示名称与数值（无需悬停）'),
            },
          },
        ],
        [
          {
            name: 'show_ranking',
            config: {
              type: 'CheckboxControl',
              label: t('内嵌排行侧栏'),
              default: false,
              renderTrigger: true,
              description: t(
                '在地图左侧显示当前层级的排行榜（全国=省排行，省内=城市排行），点击条目可下钻',
              ),
            },
          },
        ],
        [
          {
            name: 'rank_page_size',
            config: {
              type: 'SelectControl',
              freeForm: true,
              clearable: false,
              label: t('排行每页条数'),
              choices: formatSelectOptions([5, 10, 15, 20, 30, 50]),
              default: 10,
              renderTrigger: true,
              description: t('排行侧栏分页大小，超出条数自动分页'),
            },
          },
        ],
        [
          {
            name: 'rank_width',
            config: {
              type: 'SliderControl',
              label: t('排行侧栏宽度'),
              min: 140,
              max: 300,
              step: 10,
              default: 180,
              renderTrigger: true,
            },
          },
        ],
        [
          {
            name: 'rank_height',
            config: {
              type: 'SliderControl',
              label: t('排行侧栏高度'),
              min: 0,
              max: 800,
              step: 20,
              default: 0,
              renderTrigger: true,
              description: t(
                '0 = 自动撑满地图高度；设为具体像素值则固定高度（超出图表范围时自动截断）',
              ),
            },
          },
        ],
        [
          {
            name: 'rank_position',
            config: {
              type: 'SelectControl',
              clearable: false,
              label: t('排行侧栏位置'),
              choices: [
                ['left', t('左侧')],
                ['right', t('右侧')],
              ],
              default: 'left',
              renderTrigger: true,
              description: t(
                '中国地图建议放左侧（东部数据密集区不被遮挡）；侧栏支持手动折叠',
              ),
            },
          },
        ],
        [
          {
            name: 'rank_margin_x',
            config: {
              type: 'SliderControl',
              label: t('排行侧栏侧边距'),
              min: 0,
              max: 80,
              step: 2,
              default: 8,
              renderTrigger: true,
              description: t('侧栏在左侧时为左边距，在右侧时为右边距'),
            },
          },
        ],
        [
          {
            name: 'rank_margin_top',
            config: {
              type: 'SliderControl',
              label: t('排行侧栏顶部边距'),
              min: 0,
              max: 120,
              step: 2,
              default: 8,
              renderTrigger: true,
              description: t('下钻后若与面包屑重叠，可适当调大'),
            },
          },
        ],
        [
          {
            name: 'enable_drill',
            config: {
              type: 'CheckboxControl',
              label: t('启用点击下钻'),
              default: true,
              renderTrigger: true,
              description: t('关闭后点击区域仅联动过滤，不切换地图层级'),
            },
          },
        ],
        [
          {
            name: 'allow_roam',
            config: {
              type: 'CheckboxControl',
              label: t('允许缩放拖拽'),
              default: true,
              renderTrigger: true,
            },
          },
        ],
        [
          {
            name: 'label_font_size',
            config: {
              type: 'SliderControl',
              label: t('区域标签字号'),
              min: 8,
              max: 16,
              step: 1,
              default: 10,
              renderTrigger: true,
            },
          },
        ],
        [
          {
            name: 'point_size',
            config: {
              type: 'SliderControl',
              label: t('设备点位大小'),
              min: 4,
              max: 20,
              step: 1,
              default: 9,
              renderTrigger: true,
              description: t('设备级下钻视图中点位的符号大小'),
            },
          },
        ],
        ['linear_color_scheme'],
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
