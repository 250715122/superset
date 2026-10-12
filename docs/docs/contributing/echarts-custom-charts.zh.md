---
title: 新增 ECharts 自定义图表插件（中文）
sidebar_position: 5
---

<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# 新增 ECharts 自定义图表插件

本文档记录本 fork 在 `@superset-ui/plugin-chart-echarts` 中新增的一批图表插件，并以 **K 线图（Candlestick）** 为典型示例，完整记录“从一个 ECharts 官方示例到 Superset 可视化插件”的源码改造过程。

适用读者：需要把 [ECharts 官方示例](https://echarts.apache.org/examples) 移植成 Superset 原生图表类型的开发者。

> 构建与部署（`npm run build` + 打 wheel + 发布到云服务器）流程见 [把 Fork 后的 Superset 部署到远程云服务器](./production-deployment.zh.md)，本文不再重复。

## 一、已新增的 8 个图表

| viz_type | 图表名 | 分类 | 来源 ECharts 示例 | 实现方式 |
|---|---|---|---|---|
| `echarts_timeseries_bar_animated` | Bar Chart (Animated) | Evolution | `bar-animation-delay` | 包装型：复用 Bar 的 `transformProps`，注入动画项 |
| `echarts_area_gradient` | Area Chart (Gradient) | Evolution | `area-stack-gradient` | 包装型：复用 Area 的 `transformProps`，注入渐变 `areaStyle` |
| `graph_chart_label_overlap` | Graph Chart (Smart Labels) | Flow | `graph-label-overlap` | 包装型：复用 Graph 的 `transformProps`，开启 `labelLayout.hideOverlap` |
| `punch_card` | Punch Card Chart | Correlation | `scatter-punchCard` | 全新插件：散点 + 按值映射 `symbolSize` |
| `bar_race` | Bar Chart Race | Evolution | `bar-race-country` | 全新插件：自定义渲染组件，逐帧 `setOption` + `realtimeSort` |
| `nested_pie` | Nested Pie Chart | Part of a Whole | `pie-nest` | 全新插件：内外双环 `pie` series |
| `candlestick` | Candlestick Chart | Evolution | `candlestick-sh` | 全新插件：OHLC 四指标 + `dataZoom` |
| `custom_echarts` | Custom ECharts | Advanced-Analytics | `graphic-stroke-animation`、`geo-svg-lines` 等 | 通用插件：直接粘贴 ECharts option 的 JS 代码 |

三种实现方式的取舍：

- **包装型**：目标效果只是在某个现有图表上叠加少量 ECharts 配置（动画、渐变、防重叠）。直接复用现有 `transformProps`，在其产出的 `echartOptions` 上做后处理即可，成本最低。
- **全新插件**：查询结构或渲染逻辑与现有图表不同（如 K 线图需要固定 4 个指标、Bar Race 需要逐帧动画），需要完整编写 6 个文件。下文以 Candlestick 为例详述。
- **通用插件 `custom_echarts`**：把 ECharts option 的编写权交给使用者。配好数据源后在控件里粘贴 JS 代码即可出图，**无需改源码、无需重新构建**。适合一次性、长尾的可视化需求，详见[第五节](#五通用方案custom-echarts免构建)。

## 二、ECharts 插件的标准结构

一个完整的 ECharts 图表插件位于 `superset-frontend/plugins/plugin-chart-echarts/src/<图表名>/`，由 6 个文件组成：

```
Candlestick/
├── index.ts            # 插件入口：声明元数据，串联其余文件
├── types.ts            # FormData / ChartProps / TransformedProps 类型
├── buildQuery.ts       # 定义向后端请求什么数据（列、指标、排序）
├── controlPanel.tsx    # Explore 左侧控件面板
├── transformProps.ts   # 核心：把查询结果转成 ECharts option
├── Candlestick.tsx     # React 渲染组件
└── images/
    └── thumbnail.png   # 图表选择器里的缩略图（1200×1200）
```

数据流向：

```mermaid
flowchart LR
    cp["controlPanel.tsx<br/>用户配置"] --> fd["formData"]
    fd --> bq["buildQuery.ts<br/>生成查询"]
    bq --> be["后端执行 SQL"]
    be --> qd["queriesData"]
    qd --> tp["transformProps.ts<br/>转成 echartOptions"]
    fd --> tp
    tp --> rc["Candlestick.tsx<br/>渲染"]
```

完成插件目录后，还需要在 **3 处全局注册**它，才能在图表选择器里出现（见[第四节](#四注册插件3-处)）。

## 三、典型示例：从零新增 K 线图（Candlestick）

目标：移植 ECharts 官方示例 [`candlestick-sh`](https://echarts.apache.org/examples/zh/editor.html?c=candlestick-sh)。该图每个时间周期需要 4 个值——开盘、收盘、最低、最高（OHLC），并支持 `dataZoom` 缩放。

### 3.1 types.ts —— 定义类型

`FormData` 描述控件面板会产出哪些字段；`TransformedProps` 直接复用基类。

```ts
import {
  Currency,
  QueryFormColumn,
  QueryFormData,
  QueryFormMetric,
} from '@superset-ui/core';
import { BaseChartProps, BaseTransformedProps } from '../types';

export interface CandlestickFormData extends QueryFormData {
  currencyFormat?: Currency;
  metricOpen: QueryFormMetric;
  metricClose: QueryFormMetric;
  metricLow: QueryFormMetric;
  metricHigh: QueryFormMetric;
  xAxis: QueryFormColumn;
  xAxisTimeFormat?: string;
  yAxisFormat?: string;
  zoomable?: boolean;
}

export interface CandlestickChartProps
  extends BaseChartProps<CandlestickFormData> {
  formData: CandlestickFormData;
}

export type CandlestickTransformedProps =
  BaseTransformedProps<CandlestickFormData>;
```

### 3.2 buildQuery.ts —— 请求 OHLC 四个指标

关键点：把 4 个指标放进一次查询的 `metrics`，并按 X 轴时间列升序排列。

```ts
import {
  QueryFormData,
  buildQueryContext,
  ensureIsArray,
  getColumnLabel,
  getXAxisColumn,
} from '@superset-ui/core';

export default function buildQuery(formData: QueryFormData) {
  const { metric_open, metric_close, metric_low, metric_high } = formData;
  const xAxisColumn = getXAxisColumn(formData);
  return buildQueryContext(formData, baseQueryObject => [
    {
      ...baseQueryObject,
      columns: ensureIsArray(xAxisColumn),
      metrics: [metric_open, metric_close, metric_low, metric_high],
      orderby: xAxisColumn ? [[getColumnLabel(xAxisColumn), true]] : [],
    },
  ]);
}
```

### 3.3 controlPanel.tsx —— 4 个指标控件 + 缩放开关

用一个小工厂 `ohlcMetric` 复用 `sharedControls.metric`，避免重复声明 4 个几乎一样的指标控件。

```tsx
import { t, validateNonEmpty } from '@superset-ui/core';
import { ControlPanelConfig, sharedControls } from '@superset-ui/chart-controls';

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
        [ohlcMetric('metric_open', t('Open metric'), t('Metric for the opening value of each period'))],
        [ohlcMetric('metric_close', t('Close metric'), t('Metric for the closing value of each period'))],
        [ohlcMetric('metric_low', t('Low metric'), t('Metric for the lowest value of each period'))],
        [ohlcMetric('metric_high', t('High metric'), t('Metric for the highest value of each period'))],
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
    x_axis: { description: t('The time column of the OHLC periods.') },
    y_axis_format: { label: t('Value Format') },
  },
};

export default config;
```

### 3.4 transformProps.ts —— 转成 ECharts option（核心）

这是最关键的一步。要点：

- 从 `queriesData[0]` 取出 `data / colnames / coltypes`；
- 每行抽取 4 个指标值，组装成 ECharts K 线要求的维度顺序 **`[open, close, lowest, highest]`**；
- 涨用红、跌用绿，通过 `itemStyle.color / color0` 控制；
- `tooltip.formatter` 里注意：分类轴下 ECharts 会在 `value[0]` 插入数据下标，真实 OHLC 从 `value[1]` 开始，故 `.slice(1)`；
- 根据 `zoomable` 决定是否输出 `dataZoom`。

```ts
import {
  GenericDataType,
  getMetricLabel,
  getTimeFormatter,
  getValueFormatter,
  tooltipHtml,
} from '@superset-ui/core';
import type { ComposeOption } from 'echarts/core';
import type { CandlestickSeriesOption } from 'echarts/charts';
import type { CallbackDataParams } from 'echarts/types/src/util/types';
import { CandlestickChartProps, CandlestickTransformedProps } from './types';
import { getDefaultTooltip } from '../utils/tooltip';
import { Refs } from '../types';
import { defaultGrid } from '../defaults';

type EChartsOption = ComposeOption<CandlestickSeriesOption>;

const UP_COLOR = '#ec0000';
const UP_BORDER_COLOR = '#8A0000';
const DOWN_COLOR = '#00da3c';
const DOWN_BORDER_COLOR = '#008F28';

export default function transformProps(
  chartProps: CandlestickChartProps,
): CandlestickTransformedProps {
  const refs: Refs = {};
  const { width, height, formData, queriesData, datasource } = chartProps;
  const {
    currencyFormat, metricOpen, metricClose, metricLow, metricHigh,
    xAxisTimeFormat, yAxisFormat, zoomable = true,
  } = formData;
  const { data, colnames, coltypes } = queriesData[0];
  const { columnFormats = {}, currencyFormats = {} } = datasource;

  const xAxisColumnName = colnames[0];
  const openLabel = getMetricLabel(metricOpen);
  const closeLabel = getMetricLabel(metricClose);
  const lowLabel = getMetricLabel(metricLow);
  const highLabel = getMetricLabel(metricHigh);

  const xAxisFormatter =
    coltypes[0] === GenericDataType.Temporal
      ? (value: string | number) =>
          getTimeFormatter(xAxisTimeFormat)(
            typeof value === 'string' ? Number.parseInt(value, 10) : value,
          ) as string
      : (value: string | number) => String(value);

  const valueFormatter = getValueFormatter(
    metricClose, currencyFormats, columnFormats, yAxisFormat, currencyFormat,
  );

  const categories: string[] = [];
  const seriesData: [number, number, number, number][] = [];
  data.forEach(row => {
    const open = row[openLabel];
    const close = row[closeLabel];
    const low = row[lowLabel];
    const high = row[highLabel];
    if (
      typeof open !== 'number' || typeof close !== 'number' ||
      typeof low !== 'number' || typeof high !== 'number'
    ) {
      return;
    }
    categories.push(xAxisFormatter(row[xAxisColumnName] as string | number));
    // ECharts 维度顺序：[open, close, lowest, highest]
    seriesData.push([open, close, low, high]);
  });

  const series: CandlestickSeriesOption[] = [
    {
      name: closeLabel,
      type: 'candlestick',
      data: seriesData,
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_BORDER_COLOR,
        borderColor0: DOWN_BORDER_COLOR,
      },
    },
  ];

  const echartOptions: EChartsOption = {
    grid: { ...defaultGrid, bottom: zoomable ? 80 : undefined, containLabel: true },
    series,
    tooltip: {
      ...getDefaultTooltip(refs),
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: CallbackDataParams[]) => {
        const param = params[0];
        const values = (param.value as number[]).slice(1); // 跳过下标位
        return tooltipHtml(
          [
            [openLabel, valueFormatter(values[0])],
            [closeLabel, valueFormatter(values[1])],
            [lowLabel, valueFormatter(values[2])],
            [highLabel, valueFormatter(values[3])],
          ],
          param.name,
        );
      },
    },
    xAxis: { type: 'category', data: categories, boundaryGap: true, axisLine: { onZero: false } },
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v: number) => valueFormatter(v) } },
    dataZoom: zoomable
      ? [
          { type: 'inside', start: 0, end: 100 },
          { type: 'slider', show: true, bottom: 20, start: 0, end: 100 },
        ]
      : [],
  };
  return { refs, echartOptions, width, height, formData };
}
```

### 3.5 Candlestick.tsx —— 渲染组件

绝大多数插件直接复用共享的 `Echart` 组件即可，无需自己管理 ECharts 实例。

```tsx
import { CandlestickTransformedProps } from './types';
import Echart from '../components/Echart';

export default function Candlestick(props: CandlestickTransformedProps) {
  const { height, width, echartOptions, refs, formData } = props;
  return (
    <Echart
      refs={refs}
      height={height}
      width={width}
      echartOptions={echartOptions}
      vizType={formData.vizType}
    />
  );
}
```

> 例外：若图表需要逐帧动画或自管生命周期（如 `bar_race`），则不复用共享组件，而是自己 `init` 一个 ECharts 实例并用 `setInterval` 驱动 `setOption`。

### 3.6 index.ts —— 插件入口与元数据

`metadata` 决定它在图表选择器里的展示：名称、分类、标签、缩略图、描述。

```ts
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
```

### 3.7 缩略图

`images/thumbnail.png` 建议为 1200×1200，且**画的就是该图表本身的样式**，方便在选择器里一眼区分。可以用 ECharts 服务端渲染（SSR，`renderer: 'svg'` + `@resvg/resvg-js`）批量生成，避免手工截图。切勿直接复制其他图表的缩略图。

## 四、注册插件（3 处）

插件目录写完后，必须在以下 3 处登记，缺一不可：

**① 导出插件** —— `superset-frontend/plugins/plugin-chart-echarts/src/index.ts`

```ts
export { default as EchartsCandlestickChartPlugin } from './Candlestick';
```

**② 声明 viz_type 枚举** —— `superset-frontend/packages/superset-ui-core/src/chart/types/VizType.ts`

```ts
Candlestick = 'candlestick',
```

**③ 注册到主预设** —— `superset-frontend/src/visualizations/presets/MainPreset.js`（先在顶部 import，再在数组里 `configure`）

```js
import {
  // ...
  EchartsCandlestickChartPlugin,
  // ...
} from '@superset-ui/plugin-chart-echarts';

// ... 在插件数组中：
new EchartsCandlestickChartPlugin().configure({ key: VizType.Candlestick }),
```

### 4.1 额外一步：注册 ECharts 图表类型

共享的 `Echart` 组件按需 `use()` 注册 ECharts 模块以做摇树优化。若新图表用到的 series 类型尚未被注册，必须在 `superset-frontend/plugins/plugin-chart-echarts/src/components/Echart.tsx` 补充，否则运行时图表为空白。K 线图用到 `candlestick`，因此新增了 `CandlestickChart`：

```diff
  import {
    SankeyChart,
    PieChart,
    BarChart,
+   CandlestickChart,
    FunnelChart,
    // ...
  } from 'echarts/charts';

  use([
    CanvasRenderer,
    BarChart,
    BoxplotChart,
+   CandlestickChart,
    CustomChart,
    // ...
  ]);
```

> 提示：如果新图表复用的是已注册过的 series（如 `bar`、`line`、`pie`、`scatter`、`graph`），则这一步可跳过。

## 五、通用方案：Custom ECharts（免构建）

如果只是临时需要某个 ECharts 效果、不值得为它写一个插件，使用内置的 **Custom ECharts** 图表类型即可，**无需改源码、无需重新构建**：

1. 新建图表时选择 **Custom ECharts**；
2. 在左侧 Query 区正常配置数据源、维度（Dimensions）、指标（Metrics）、过滤器；
3. 滚动到 **ECharts Option** 区块，在代码框中粘贴 JS 代码。运行时会注入两个变量：
   - `data`：查询结果的**行对象数组**，key 即维度/指标的列名；
   - `echarts`：完整的 ECharts 命名空间（可用 `echarts.graphic`、`echarts.registerMap` 等）；
4. 代码最后 `return` 一个 option 对象（支持返回 Promise）。

```javascript
// data 形如 [{ device_model: 'AC200', 'COUNT(*)': 1234 }, ...]
return {
  tooltip: {},
  xAxis: { type: 'category', data: data.map(row => row.device_model) },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: data.map(row => row['COUNT(*)']) }],
};
```

把官方示例改造为可用代码时，只需把 `option = {...}` 改成 `return {...}`。

> **安全提示**：该代码会在**每个查看者的浏览器中执行**，因此编辑权限只应授予可信用户。这是为内网环境特意接受的权衡。

### Custom ECharts 的能力边界

以下场景仍需开发专用插件并重新构建，无法用 Custom ECharts 覆盖：

| 场景 | 原因 |
|---|---|
| 需要特定查询结构 | 如 K 线图固定 4 指标、Bar Race 按时间帧分组——通用面板只有泛化的维度+指标 |
| 让不懂 JS 的用户零代码配置 | 专用插件提供可视化控件；Custom ECharts 要求会写 JS |
| 定时器驱动的连续动画 | Custom ECharts 只执行一次、返回一个 option（ECharts 自带的 `timeline` 动画仍可用） |
| 需要 ECharts v6 新特性 | 当前打包版本为 5.6.0 |
| 与 Superset 深度联动 | 如点击触发仪表板交叉过滤，需要插件注册行为（behaviors） |

## 六、自检清单

新增一个图表插件后，依次确认：

- [ ] 插件目录 6 个文件齐全，`images/thumbnail.png` 为该图表专属样式；
- [ ] 已完成第四节的 3 处注册；
- [ ] 若用到新 series 类型，已在 `Echart.tsx` 的 `use([...])` 中注册；
- [ ] `npx tsc --noEmit` 类型检查通过；
- [ ] `npx eslint <插件目录>` 通过；
- [ ] 为 `transformProps` 补充 Jest 单测（参考 `plugins/plugin-chart-echarts/test/Candlestick/`）并通过；
- [ ] `npx jest .../VizTypeControl.test.tsx` 注册测试通过；
- [ ] `npm run build` 成功，再按[部署文档](./production-deployment.zh.md)打 wheel 发布。
