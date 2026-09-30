/* eslint-disable camelcase */
/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 */

import {
  ControlPanelConfig,
  ControlPanelsContainerProps,
  ControlState,
  CustomControlItem,
} from '@superset-ui/chart-controls';
import config from '../src/controlPanel';

type VisibilityFn = (
  props: ControlPanelsContainerProps,
  control?: ControlState,
) => boolean;

function isControlWithVisibility(
  controlItem: unknown,
): controlItem is CustomControlItem & {
  config: Required<CustomControlItem['config']> & { visibility: VisibilityFn };
} {
  return (
    typeof controlItem === 'object' &&
    controlItem !== null &&
    'name' in controlItem &&
    'config' in controlItem &&
    typeof (controlItem as CustomControlItem).config?.visibility === 'function'
  );
}

function getVisibility(
  panel: ControlPanelConfig,
  controlName: string,
): VisibilityFn {
  const item = (panel.controlPanelSections || [])
    .flatMap(section => section?.controlSetRows || [])
    .flat()
    .find(c => isControlWithVisibility(c) && c.name === controlName);

  if (!isControlWithVisibility(item)) {
    throw new Error(`Control "${controlName}" with visibility not found`);
  }
  return item.config.visibility;
}

function mkProps(
  groupbyValue: string[],
  options = [
    { column_name: 'ORDERDATE', is_dttm: true },
    { column_name: 'some_other_col', is_dttm: false },
  ],
  extra = {},
): ControlPanelsContainerProps {
  return {
    datasource: {
      extra,
    },
    controls: {
      groupby: { value: groupbyValue, options },
      query_mode: { value: 'aggregate' },
      server_pagination: { value: false },
    },
  } as unknown as ControlPanelsContainerProps;
}

test('time_grain_sqla visibility should be case-insensitive', () => {
  const vis = getVisibility(config, 'time_grain_sqla');
  const controlState = {} as ControlState;

  expect(vis(mkProps(['orderdate']), controlState)).toBe(true);
  expect(vis(mkProps(['ORDERDATE']), controlState)).toBe(true);
  expect(vis(mkProps(['some_other_col']), controlState)).toBe(false);
});

test('query mode and ordering controls are hidden for command datasets', () => {
  const queryModeVisibility = getVisibility(config, 'query_mode');
  const orderByVisibility = getVisibility(config, 'order_by_cols');
  const controlState = {} as ControlState;
  const commandExtra = { command_dataset: { enabled: true } };

  expect(queryModeVisibility(mkProps([], undefined, commandExtra), controlState)).toBe(
    false,
  );
  expect(orderByVisibility(mkProps([], undefined, commandExtra), controlState)).toBe(
    false,
  );
});

test('row limit is hidden for command datasets', () => {
  const rowLimitVisibility = getVisibility(config, 'row_limit');
  const controlState = {} as ControlState;

  expect(
    rowLimitVisibility(
      mkProps([], undefined, { command_dataset: { enabled: true } }),
      controlState,
    ),
  ).toBe(false);
});
