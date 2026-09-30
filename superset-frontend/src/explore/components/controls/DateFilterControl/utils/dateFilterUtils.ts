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
import rison from 'rison';
import {
  NO_TIME_RANGE,
  JsonObject,
  customTimeRangeDecode,
  SupersetClient,
  getClientErrorObject,
  t,
} from '@superset-ui/core';
import { extendedDayjs } from '@superset-ui/core/utils/dates';
import { useSelector } from 'react-redux';
import {
  COMMON_RANGE_VALUES_SET,
  CALENDAR_RANGE_VALUES_SET,
  CURRENT_RANGE_VALUES_SET,
} from '.';
import { FrameType, TimeRangeLimitUnit } from '../types';

export const guessFrame = (timeRange: string): FrameType => {
  if (COMMON_RANGE_VALUES_SET.has(timeRange)) {
    return 'Common';
  }
  if (CALENDAR_RANGE_VALUES_SET.has(timeRange)) {
    return 'Calendar';
  }
  if (CURRENT_RANGE_VALUES_SET.has(timeRange)) {
    return 'Current';
  }
  if (timeRange === NO_TIME_RANGE) {
    return 'No filter';
  }
  if (customTimeRangeDecode(timeRange).matchedFlag) {
    return 'Custom';
  }
  return 'Advanced';
};

export function useDefaultTimeFilter() {
  return (
    useSelector(
      (state: JsonObject) => state?.common?.conf?.DEFAULT_TIME_FILTER,
    ) ?? NO_TIME_RANGE
  );
}

const TIME_RANGE_SEPARATOR = ' : ';

const buildTimeRangeString = (since: string, until: string): string =>
  `${since}${TIME_RANGE_SEPARATOR}${until}`;

const formatDateEndpoint = (dttm: string, isStart?: boolean): string =>
  dttm.replace('T00:00:00', '') || (isStart ? '-∞' : '∞');

const formatEvaluatedTimeRange = (
  timeRange: string,
  columnPlaceholder = 'col',
) => {
  const splitDateRange = timeRange.split(TIME_RANGE_SEPARATOR);
  if (splitDateRange.length === 1) {
    return timeRange;
  }
  return `${formatDateEndpoint(
    splitDateRange[0],
    true,
  )} ≤ ${columnPlaceholder} < ${formatDateEndpoint(splitDateRange[1])}`;
};

export const fetchTimeRangeDetails = async (
  timeRange: string,
  columnPlaceholder = 'col',
) => {
  const query = rison.encode_uri(timeRange);
  const endpoint = `/api/v1/time_range/?q=${query}`;

  try {
    const response = await SupersetClient.get({ endpoint });
    const since = response?.json?.result[0]?.since || '';
    const until = response?.json?.result[0]?.until || '';
    const value = formatEvaluatedTimeRange(
      buildTimeRangeString(since, until),
      columnPlaceholder,
    );

    return {
      value,
      since,
      until,
    };
  } catch (response) {
    const clientError = await getClientErrorObject(response);
    return {
      error: clientError.message || clientError.error || response.statusText,
    };
  }
};

const TIME_RANGE_LIMIT_LABELS: Record<
  TimeRangeLimitUnit,
  { singular: string; plural: string }
> = {
  day: { singular: t('day'), plural: t('days') },
  week: { singular: t('week'), plural: t('weeks') },
  month: { singular: t('month'), plural: t('months') },
  year: { singular: t('year'), plural: t('years') },
};

const getTimeRangeLimitValidationMessage = (maxRangeLabel: string) =>
  t('Select a bounded time range no longer than %(max_range)s.', {
    max_range: maxRangeLabel,
  });

const normalizeTimeRangeLimitUnit = (unit: TimeRangeLimitUnit) => {
  if (unit === 'week') {
    return { amount: 1, unit: 'week' as const };
  }
  if (unit === 'month') {
    return { amount: 1, unit: 'month' as const };
  }
  if (unit === 'year') {
    return { amount: 1, unit: 'year' as const };
  }
  return { amount: 1, unit: 'day' as const };
};

export const formatTimeRangeLimit = (
  maxTimeRangeValue?: number | null,
  maxTimeRangeUnit?: TimeRangeLimitUnit | null,
) => {
  if (!maxTimeRangeValue || !maxTimeRangeUnit) {
    return null;
  }

  const labels = TIME_RANGE_LIMIT_LABELS[maxTimeRangeUnit];
  const unitLabel =
    maxTimeRangeValue === 1 ? labels.singular : labels.plural;
  return `${maxTimeRangeValue} ${unitLabel}`;
};

export const validateTimeRangeLimit = ({
  since,
  until,
  maxTimeRangeValue,
  maxTimeRangeUnit,
}: {
  since?: string;
  until?: string;
  maxTimeRangeValue?: number | null;
  maxTimeRangeUnit?: TimeRangeLimitUnit | null;
}) => {
  const maxRangeLabel = formatTimeRangeLimit(
    maxTimeRangeValue,
    maxTimeRangeUnit,
  );
  if (!maxRangeLabel || !maxTimeRangeValue || !maxTimeRangeUnit) {
    return { isValid: true, validationMessage: '' };
  }

  if (!since || !until) {
    return {
      isValid: false,
      validationMessage: getTimeRangeLimitValidationMessage(maxRangeLabel),
    };
  }

  const start = extendedDayjs.utc(since);
  const end = extendedDayjs.utc(until);
  if (!start.isValid() || !end.isValid()) {
    return {
      isValid: false,
      validationMessage: getTimeRangeLimitValidationMessage(maxRangeLabel),
    };
  }

  const normalizedUnit = normalizeTimeRangeLimitUnit(maxTimeRangeUnit);
  const maxEnd = start.add(
    maxTimeRangeValue * normalizedUnit.amount,
    normalizedUnit.unit,
  );
  if (end.isSameOrBefore(maxEnd)) {
    return { isValid: true, validationMessage: '' };
  }

  return {
    isValid: false,
    validationMessage: getTimeRangeLimitValidationMessage(maxRangeLabel),
  };
};
