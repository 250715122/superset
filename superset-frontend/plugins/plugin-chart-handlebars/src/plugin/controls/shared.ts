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
  ControlPanelsContainerProps,
  ControlStateMapping,
} from '@superset-ui/chart-controls';
import {
  ensureIsArray,
  QueryFormColumn,
  QueryMode,
  t,
} from '@superset-ui/core';

type DatasourceLike = ControlPanelsContainerProps['datasource'];

export function isCommandDataset(datasource?: DatasourceLike): boolean {
  let extra = datasource?.extra ?? {};
  if (typeof extra === 'string') {
    try {
      extra = JSON.parse(extra || '{}');
    } catch {
      extra = {};
    }
  }
  const parsedExtra = extra as {
    command_dataset?: { enabled?: boolean };
  };
  return Boolean(parsedExtra?.command_dataset?.enabled);
}

export function getQueryMode(
  controls: ControlStateMapping,
  datasource?: DatasourceLike,
): QueryMode {
  if (isCommandDataset(datasource)) {
    return QueryMode.Raw;
  }
  const mode = controls?.query_mode?.value;
  if (mode === QueryMode.Aggregate || mode === QueryMode.Raw) {
    return mode as QueryMode;
  }
  const rawColumns = controls?.all_columns?.value as
    | QueryFormColumn[]
    | undefined;
  const hasRawColumns = rawColumns && rawColumns.length > 0;
  return hasRawColumns ? QueryMode.Raw : QueryMode.Aggregate;
}

/**
 * Visibility check
 */
export function isQueryMode(mode: QueryMode) {
  return ({ controls, datasource }: ControlPanelsContainerProps) =>
    getQueryMode(controls || {}, datasource) === mode;
}

export const isAggMode = isQueryMode(QueryMode.Aggregate);
export const isRawMode = isQueryMode(QueryMode.Raw);
export const isNotCommandDataset = ({
  datasource,
}: ControlPanelsContainerProps) => !isCommandDataset(datasource);

export const validateAggControlValues = (
  controls: ControlStateMapping,
  values: any[],
  datasource?: DatasourceLike,
) => {
  const areControlsEmpty = values.every(val => ensureIsArray(val).length === 0);
  return (
    areControlsEmpty &&
    getQueryMode(controls, datasource) === QueryMode.Aggregate
  )
    ? [t('Group By, Metrics or Percentage Metrics must have a value')]
    : [];
};
