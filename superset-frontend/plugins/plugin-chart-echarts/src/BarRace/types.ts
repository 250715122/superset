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
import {
  Currency,
  QueryFormColumn,
  QueryFormData,
  QueryFormMetric,
} from '@superset-ui/core';
import { BaseChartProps } from '../types';

export interface BarRaceFormData extends QueryFormData {
  currencyFormat?: Currency;
  frameDuration: number;
  loop?: boolean;
  maxBars: number;
  metric: QueryFormMetric;
  xAxis: QueryFormColumn;
  xAxisTimeFormat?: string;
  yAxisFormat?: string;
}

export interface BarRaceChartProps extends BaseChartProps<BarRaceFormData> {
  formData: BarRaceFormData;
}

export interface BarRaceFrame {
  title: string;
  values: (number | null)[];
}

export interface BarRaceTransformedProps {
  width: number;
  height: number;
  categories: string[];
  colors: string[];
  frames: BarRaceFrame[];
  frameDuration: number;
  loop: boolean;
  maxBars: number;
  valueFormatter: (value: number | null | undefined) => string;
  formData: BarRaceFormData;
}
