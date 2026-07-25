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
import { useEffect, useRef } from 'react';
import { addAlpha, styled, useTheme } from '@superset-ui/core';
import { use, init, EChartsType } from 'echarts/core';
import { BarChart } from 'echarts/charts';
import {
  GridComponent,
  GraphicComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { CallbackDataParams } from 'echarts/types/src/util/types';
import { BarRaceTransformedProps } from './types';

use([
  BarChart,
  GridComponent,
  GraphicComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const Styles = styled.div<{ height: number; width: number }>`
  height: ${({ height }) => height}px;
  width: ${({ width }) => width}px;
`;

export default function BarRace(props: BarRaceTransformedProps) {
  const {
    width,
    height,
    categories,
    colors,
    frames,
    frameDuration,
    loop,
    maxBars,
    valueFormatter,
  } = props;
  const theme = useTheme();
  const divRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType>();

  useEffect(() => {
    if (divRef.current) {
      chartRef.current = init(divRef.current);
    }
    return () => {
      chartRef.current?.dispose();
      chartRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || frames.length === 0) {
      return undefined;
    }
    const frameOption = (frameIndex: number) => ({
      series: [
        {
          type: 'bar' as const,
          id: 'race',
          realtimeSort: true,
          data: frames[frameIndex].values,
          label: {
            show: true,
            position: 'right' as const,
            valueAnimation: true,
            formatter: (params: CallbackDataParams) =>
              valueFormatter(params.value as number | null),
          },
          itemStyle: {
            color: (params: CallbackDataParams) => colors[params.dataIndex],
          },
        },
      ],
      graphic: {
        elements: [
          {
            type: 'text' as const,
            right: 60,
            bottom: 60,
            style: {
              text: frames[frameIndex].title,
              font: 'bolder 60px monospace',
              fill: addAlpha(theme.colorText, 0.25),
            },
            z: 100,
          },
        ],
      },
    });

    chart.setOption(
      {
        grid: { left: 8, right: 80, top: 8, bottom: 8, containLabel: true },
        xAxis: {
          type: 'value',
          max: 'dataMax',
          axisLabel: {
            formatter: (value: number) => valueFormatter(value),
          },
        },
        yAxis: {
          type: 'category',
          data: categories,
          inverse: true,
          max: maxBars - 1,
          animationDuration: 300,
          animationDurationUpdate: 300,
        },
        tooltip: {
          trigger: 'item',
          valueFormatter: (value: unknown) =>
            valueFormatter(value as number | null),
        },
        animationDuration: 0,
        animationDurationUpdate: frameDuration,
        animationEasing: 'linear',
        animationEasingUpdate: 'linear',
        ...frameOption(0),
      },
      true,
    );

    let frameIndex = 0;
    const timer = setInterval(() => {
      frameIndex += 1;
      if (frameIndex >= frames.length) {
        if (!loop) {
          clearInterval(timer);
          return;
        }
        frameIndex = 0;
      }
      chart.setOption(frameOption(frameIndex));
    }, frameDuration);
    return () => clearInterval(timer);
  }, [
    categories,
    colors,
    frames,
    frameDuration,
    loop,
    maxBars,
    theme,
    valueFormatter,
  ]);

  useEffect(() => {
    chartRef.current?.resize({ width, height });
  }, [width, height]);

  return (
    <Styles height={height} width={width}>
      <div ref={divRef} style={{ height: '100%', width: '100%' }} />
    </Styles>
  );
}
