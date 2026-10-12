/* eslint-disable camelcase */
/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 */

import {
  ControlPanelConfig,
  ControlPanelsContainerProps,
  ControlState,
} from '@superset-ui/chart-controls';
import config from '../../src/plugin/controlPanel';

type VisibilityFn = (
  props: ControlPanelsContainerProps,
  control?: ControlState,
) => boolean;

function isControlWithVisibility(
  controlItem: unknown,
): controlItem is {
  name: string;
  config?: { visibility?: VisibilityFn };
  override?: { visibility?: VisibilityFn };
} {
  return (
    typeof controlItem === 'object' &&
    controlItem !== null &&
    'name' in controlItem &&
    ('config' in controlItem || 'override' in controlItem) &&
    (typeof (controlItem as { config?: { visibility?: VisibilityFn } }).config
      ?.visibility === 'function' ||
      typeof (
        controlItem as { override?: { visibility?: VisibilityFn } }
      ).override?.visibility === 'function')
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
  const visibility = item.config?.visibility ?? item.override?.visibility;
  if (!visibility) {
    throw new Error(`Control "${controlName}" visibility is not a function`);
  }
  return visibility;
}

function mkProps(extra = {}): ControlPanelsContainerProps {
  return {
    datasource: {
      extra,
    },
    controls: {
      groupby: { value: [], options: [] },
      query_mode: { value: 'aggregate' },
      server_pagination: { value: false },
      timeseries_limit_metric: { value: null },
    },
  } as unknown as ControlPanelsContainerProps;
}

test('command datasets force raw display controls and hide unsupported controls', () => {
  const queryModeVisibility = getVisibility(config, 'query_mode');
  const groupByVisibility = getVisibility(config, 'groupby');
  const allColumnsVisibility = getVisibility(config, 'all_columns');
  const orderByVisibility = getVisibility(config, 'order_by_cols');
  const rowLimitVisibility = getVisibility(config, 'row_limit');
  const includeTimeVisibility = getVisibility(config, 'include_time');
  const adhocFiltersVisibility = getVisibility(config, 'adhoc_filters');
  const controlState = {} as ControlState;
  const props = mkProps({ command_dataset: { enabled: true } });

  expect(queryModeVisibility(props, controlState)).toBe(false);
  expect(groupByVisibility(props, controlState)).toBe(false);
  expect(allColumnsVisibility(props, controlState)).toBe(true);
  expect(orderByVisibility(props, controlState)).toBe(false);
  expect(rowLimitVisibility(props, controlState)).toBe(false);
  expect(includeTimeVisibility(props, controlState)).toBe(false);
  expect(adhocFiltersVisibility(props, controlState)).toBe(false);
});
