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
  render,
  screen,
  userEvent,
  waitFor,
} from 'spec/helpers/testing-library';
import fetchMock from 'fetch-mock';
import TabRolesControl from './TabRolesControl';

const TABS_ENDPOINT = 'glob:*/api/v1/dashboard/1/tabs';
const ROLES_ENDPOINT = 'glob:*/api/v1/dashboard/related/roles*';

const mockTabs = (allTabs: Record<string, string>) =>
  fetchMock.get(TABS_ENDPOINT, { result: { all_tabs: allTabs } }, {
    overwriteRoutes: true,
  });

beforeEach(() => {
  fetchMock.get(
    ROLES_ENDPOINT,
    { result: [{ text: 'Admin' }, { text: '运维' }, { text: '分析师' }] },
    { overwriteRoutes: true },
  );
});

afterEach(() => {
  fetchMock.restore();
});

const setup = (props = {}) =>
  render(
    <TabRolesControl
      dashboardId={1}
      value={{}}
      onChange={jest.fn()}
      {...props}
    />,
  );

test('renders nothing when the dashboard has no tabs', async () => {
  mockTabs({});
  const { container } = setup();

  await waitFor(() => expect(fetchMock.called(TABS_ENDPOINT)).toBe(true));
  expect(container).toBeEmptyDOMElement();
});

test('renders one role picker per tab, labelled with the tab title', async () => {
  mockTabs({ 'TAB-aaa': '总览', 'TAB-bbb': '运维明细' });
  setup();

  expect(await screen.findByText('总览')).toBeInTheDocument();
  expect(screen.getByText('运维明细')).toBeInTheDocument();
  expect(screen.getAllByRole('combobox')).toHaveLength(2);
});

test('an unrestricted tab reads as visible to everyone', async () => {
  mockTabs({ 'TAB-aaa': '总览' });
  setup();

  expect(await screen.findByText('Visible to everyone')).toBeInTheDocument();
});

test('shows the roles a tab is already restricted to', async () => {
  mockTabs({ 'TAB-aaa': '总览', 'TAB-bbb': '运维明细' });
  setup({ value: { 'TAB-bbb': ['运维'] } });

  expect(await screen.findByText('运维')).toBeInTheDocument();
  expect(screen.getByText('Visible to everyone')).toBeInTheDocument();
});

test('granting a role reports it back by name', async () => {
  mockTabs({ 'TAB-aaa': '总览' });
  const onChange = jest.fn();
  setup({ onChange });

  userEvent.click(await screen.findByRole('combobox'));
  userEvent.click(await screen.findByTitle('分析师'));

  await waitFor(() =>
    expect(onChange).toHaveBeenCalledWith({ 'TAB-aaa': ['分析师'] }),
  );
});

test('clearing a tab drops its key rather than leaving it empty', async () => {
  // An empty list would be indistinguishable from "restricted to no role",
  // so the tab has to disappear from the mapping to become public again.
  mockTabs({ 'TAB-aaa': '总览', 'TAB-bbb': '运维明细' });
  const onChange = jest.fn();
  setup({ value: { 'TAB-aaa': ['运维'], 'TAB-bbb': ['分析师'] }, onChange });

  await screen.findByText('运维');
  userEvent.click(screen.getAllByLabelText('close')[0]);

  await waitFor(() =>
    expect(onChange).toHaveBeenCalledWith({ 'TAB-bbb': ['分析师'] }),
  );
});

test('is read only when the user may not edit the dashboard', async () => {
  mockTabs({ 'TAB-aaa': '总览' });
  setup({ disabled: true });

  await waitFor(() =>
    expect(screen.getByRole('combobox')).toBeDisabled(),
  );
});
