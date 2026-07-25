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
import { useEffect, useRef, useState } from 'react';
import { styled, DataRecord } from '@superset-ui/core';
// Full ECharts build on purpose: user-provided options may use any chart type,
// component or the graphic/geo APIs that the tree-shaken shared Echart
// component does not register. This module is lazy-loaded via loadChart, so
// the cost is only paid when a Custom ECharts chart is actually rendered.
// eslint-disable-next-line no-restricted-syntax
import * as echarts from 'echarts';
import { CustomEchartsTransformedProps } from './types';

type OptionFactory = (
  echartsNamespace: typeof echarts,
  data: DataRecord[],
) => unknown;

const Styles = styled.div<{ height: number; width: number }>`
  position: relative;
  height: ${({ height }) => height}px;
  width: ${({ width }) => width}px;
`;

const ErrorMessage = styled.pre`
  position: absolute;
  inset: 0;
  margin: 0;
  padding: ${({ theme }) => theme.sizeUnit * 4}px;
  overflow: auto;
  white-space: pre-wrap;
  color: ${({ theme }) => theme.colorError};
  background-color: ${({ theme }) => theme.colorBgContainer};
`;

export default function CustomEcharts(props: CustomEchartsTransformedProps) {
  const { width, height, echartsOptionCode, data } = props;
  const divRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.EChartsType>();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (divRef.current) {
      chartRef.current = echarts.init(divRef.current);
    }
    return () => {
      chartRef.current?.dispose();
      chartRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const evaluate = async () => {
      try {
        // eslint-disable-next-line no-new-func
        const factory = new Function(
          'echarts',
          'data',
          echartsOptionCode,
        ) as OptionFactory;
        const option = await factory(echarts, data);
        if (cancelled) {
          return;
        }
        if (!option || typeof option !== 'object') {
          setError(
            'The code must return an ECharts option object (or a Promise resolving to one).',
          );
          return;
        }
        setError(null);
        chartRef.current?.setOption(option as echarts.EChartsCoreOption, true);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? `${e.name}: ${e.message}` : String(e));
        }
      }
    };
    evaluate();
    return () => {
      cancelled = true;
    };
  }, [echartsOptionCode, data]);

  useEffect(() => {
    chartRef.current?.resize({ width, height });
  }, [width, height]);

  return (
    <Styles height={height} width={width}>
      <div ref={divRef} style={{ height: '100%', width: '100%' }} />
      {error && <ErrorMessage>{error}</ErrorMessage>}
    </Styles>
  );
}
