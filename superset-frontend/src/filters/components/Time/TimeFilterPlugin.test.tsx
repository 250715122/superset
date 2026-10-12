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
import { useReducer, useState } from 'react';
import { DataMask, FilterState } from '@superset-ui/core';
import { act, render, waitFor } from 'spec/helpers/testing-library';
import { fetchTimeRangeDetails } from 'src/explore/components/controls/DateFilterControl/utils';
import { TimeRangeLimitUnit } from 'src/explore/components/controls/DateFilterControl/types';
import TimeFilterPlugin from './TimeFilterPlugin';

jest.mock('src/explore/components/controls/DateFilterControl/utils', () => ({
  ...jest.requireActual(
    'src/explore/components/controls/DateFilterControl/utils',
  ),
  fetchTimeRangeDetails: jest.fn(),
}));

const mockedFetchTimeRangeDetails = fetchTimeRangeDetails as jest.Mock;

const UnstableSetDataMaskParent = ({
  onSetDataMask,
  maxTimeRangeValue,
  maxTimeRangeUnit,
}: {
  onSetDataMask: (dataMask: DataMask) => void;
  maxTimeRangeValue?: number;
  maxTimeRangeUnit?: TimeRangeLimitUnit;
}) => {
  const [filterState, setFilterState] = useState<FilterState>({
    value: 'Last week',
  });
  const [, forceUpdate] = useReducer((count: number) => count + 1, 0);
  return (
    <TimeFilterPlugin
      // @ts-ignore
      formData={{ inView: true, maxTimeRangeValue, maxTimeRangeUnit }}
      filterState={filterState}
      width={220}
      height={20}
      behaviors={[]}
      data={[]}
      inputRef={{ current: null }}
      setDataMask={dataMask => {
        onSetDataMask(dataMask);
        setFilterState({ ...dataMask.filterState });
        forceUpdate();
      }}
      setHoveredFilter={jest.fn()}
      unsetHoveredFilter={jest.fn()}
      setFocusedFilter={jest.fn()}
      unsetFocusedFilter={jest.fn()}
      setFilterActive={jest.fn()}
    />
  );
};

beforeEach(() => {
  mockedFetchTimeRangeDetails.mockReset();
  mockedFetchTimeRangeDetails.mockResolvedValue({
    value: '2026-10-05 ≤ col < 2026-10-12',
    since: '2026-10-05T00:00:00',
    until: '2026-10-12T00:00:00',
  });
});

test('does not loop when the parent passes a new setDataMask on every render', async () => {
  const onSetDataMask = jest.fn();
  render(<UnstableSetDataMaskParent onSetDataMask={onSetDataMask} />, {
    useRedux: true,
  });

  await waitFor(() => expect(onSetDataMask).toHaveBeenCalled());
  await act(() => new Promise(resolve => setTimeout(resolve, 200)));
  expect(onSetDataMask).toHaveBeenCalledTimes(1);
});

test('validates the time range limit once without looping', async () => {
  const onSetDataMask = jest.fn();
  render(
    <UnstableSetDataMaskParent
      onSetDataMask={onSetDataMask}
      maxTimeRangeValue={1}
      maxTimeRangeUnit="day"
    />,
    { useRedux: true },
  );

  await waitFor(() => expect(onSetDataMask).toHaveBeenCalled());
  await act(() => new Promise(resolve => setTimeout(resolve, 200)));
  expect(onSetDataMask).toHaveBeenCalledTimes(1);
  expect(onSetDataMask.mock.calls[0][0].filterState.validateStatus).toBe(
    'error',
  );
});
