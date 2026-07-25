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
  QueryFormData,
  QueryFormOrderBy,
  buildQueryContext,
  ensureIsArray,
  getMetricLabel,
  getXAxisColumn,
} from '@superset-ui/core';

export default function buildQuery(formData: QueryFormData) {
  const { groupby, sort_x_axis, sort_y_axis } = formData;
  const metric = getMetricLabel(formData.metric);
  const columns = [
    ...ensureIsArray(getXAxisColumn(formData)),
    ...ensureIsArray(groupby),
  ];
  const orderby: QueryFormOrderBy[] = [];
  if (sort_x_axis) {
    orderby.push([
      sort_x_axis.includes('value') ? metric : columns[0],
      sort_x_axis.includes('asc'),
    ]);
  }
  if (sort_y_axis) {
    orderby.push([
      sort_y_axis.includes('value') ? metric : columns[1],
      sort_y_axis.includes('asc'),
    ]);
  }
  return buildQueryContext(formData, baseQueryObject => [
    {
      ...baseQueryObject,
      columns,
      orderby,
    },
  ]);
}
