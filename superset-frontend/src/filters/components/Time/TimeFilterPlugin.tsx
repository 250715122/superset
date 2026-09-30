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
  styled,
  NO_TIME_RANGE,
  getExtensionsRegistry,
  t,
} from '@superset-ui/core';
import { useCallback, useEffect, useMemo } from 'react';
import {
  FormItem,
  type FormItemProps,
} from '@superset-ui/core/components';
import DateFilterControl from 'src/explore/components/controls/DateFilterControl';
import {
  fetchTimeRangeDetails,
  formatTimeRangeLimit,
  validateTimeRangeLimit,
} from 'src/explore/components/controls/DateFilterControl/utils';
import { PluginFilterTimeProps } from './types';
import { FilterPluginStyle, StatusMessage } from '../common';

const TimeFilterStyles = styled(FilterPluginStyle)`
  display: flex;
  align-items: center;
  overflow-x: visible;

  & .ant-tag {
    margin-right: 0;
  }
`;

const ControlContainer = styled.div<{
  validateStatus?: 'error' | 'warning' | 'info';
}>`
  display: flex;
  height: 100%;
  max-width: 100%;
  width: 100%;
  & > div,
  & > div:hover {
    ${({ validateStatus, theme }) => {
      if (!validateStatus) return '';
      switch (validateStatus) {
        case 'error':
          return `border-color: ${theme.colorError}`;
        case 'warning':
          return `border-color: ${theme.colorWarning}`;
        case 'info':
          return `border-color: ${theme.colorInfo}`;
        default:
          return `border-color: ${theme.colorError}`;
      }
    }}
  }
  & > div {
    width: 100%;
  }

  &:focus > div {
    border-color: ${({ theme }) => theme.colorPrimary};
    box-shadow: ${({ theme }) => `0 0 0 2px ${theme.controlOutline}`};
    outline: 0;
  }
`;

export default function TimeFilterPlugin(props: PluginFilterTimeProps) {
  const {
    setDataMask,
    setHoveredFilter,
    unsetHoveredFilter,
    setFocusedFilter,
    unsetFocusedFilter,
    setFilterActive,
    width,
    height,
    filterState,
    inputRef,
    isOverflowingFilterBar = false,
  } = props;
  const { maxTimeRangeUnit, maxTimeRangeValue } = props.formData;
  const extensionsRegistry = getExtensionsRegistry();
  const maxTimeRangeLabel = useMemo(
    () => formatTimeRangeLimit(maxTimeRangeValue, maxTimeRangeUnit),
    [maxTimeRangeUnit, maxTimeRangeValue],
  );

  const DateFilterControlExtension = extensionsRegistry.get(
    'filter.dateFilterControl',
  );
  const DateFilterComponent = DateFilterControlExtension ?? DateFilterControl;

  const handleTimeRangeChange = useCallback(
    async (timeRange?: string): Promise<void> => {
      const isSet = timeRange && timeRange !== NO_TIME_RANGE;
      const validationMessage = maxTimeRangeLabel
        ? t('Select a bounded time range no longer than %(max_range)s.', {
            max_range: maxTimeRangeLabel,
          })
        : '';

      if (maxTimeRangeLabel) {
        if (!isSet) {
          setDataMask({
            extraFormData: {},
            filterState: {
              value: timeRange || NO_TIME_RANGE,
              validateStatus: 'error',
              validateMessage: validationMessage,
            },
          });
          return;
        }

        const { error, since, until } = await fetchTimeRangeDetails(timeRange);
        if (error) {
          setDataMask({
            extraFormData: {},
            filterState: {
              value: timeRange,
              validateStatus: 'error',
              validateMessage: error,
            },
          });
          return;
        }

        const validationResult = validateTimeRangeLimit({
          since,
          until,
          maxTimeRangeValue,
          maxTimeRangeUnit,
        });
        if (!validationResult.isValid) {
          setDataMask({
            extraFormData: {},
            filterState: {
              value: timeRange,
              validateStatus: 'error',
              validateMessage: validationResult.validationMessage,
            },
          });
          return;
        }
      }

      setDataMask({
        extraFormData: isSet
          ? {
              time_range: timeRange,
            }
          : {},
        filterState: {
          value: isSet ? timeRange : undefined,
          validateStatus: undefined,
          validateMessage: '',
        },
      });
    },
    [
      maxTimeRangeLabel,
      maxTimeRangeUnit,
      maxTimeRangeValue,
      setDataMask,
    ],
  );

  useEffect(() => {
    void handleTimeRangeChange(filterState.value);
  }, [filterState.value, handleTimeRangeChange]);

  const formItemData: FormItemProps = {};
  if (filterState.validateMessage) {
    formItemData.extra = (
      <StatusMessage status={filterState.validateStatus}>
        {filterState.validateMessage}
      </StatusMessage>
    );
  }

  return props.formData?.inView ? (
    <TimeFilterStyles width={width} height={height}>
      <FormItem validateStatus={filterState.validateStatus} {...formItemData}>
        <ControlContainer
          ref={inputRef}
          validateStatus={filterState.validateStatus}
          onFocus={setFocusedFilter}
          onBlur={unsetFocusedFilter}
          onMouseEnter={setHoveredFilter}
          onMouseLeave={unsetHoveredFilter}
          tabIndex={-1}
        >
          <DateFilterComponent
            value={filterState.value || NO_TIME_RANGE}
            name={props.formData.nativeFilterId || 'time_range'}
            onChange={timeRange => {
              void handleTimeRangeChange(timeRange);
            }}
            onOpenPopover={() => setFilterActive(true)}
            onClosePopover={() => {
              setFilterActive(false);
              unsetHoveredFilter();
              unsetFocusedFilter();
            }}
            isOverflowingFilterBar={isOverflowingFilterBar}
            maxTimeRangeValue={maxTimeRangeValue}
            maxTimeRangeUnit={maxTimeRangeUnit}
            validationMessage={filterState.validateMessage}
            validateStatus={filterState.validateStatus}
          />
        </ControlContainer>
      </FormItem>
    </TimeFilterStyles>
  ) : null;
}
