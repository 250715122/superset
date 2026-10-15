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
import { useEffect, useState } from 'react';
import { SupersetClient, t } from '@superset-ui/core';
import { FormItem, Select, Typography } from '@superset-ui/core/components';

export type TabRoles = Record<string, string[]>;

type Props = {
  dashboardId: number;
  value: TabRoles;
  onChange: (next: TabRoles) => void;
  disabled?: boolean;
};

/**
 * Restricts individual dashboard tabs to roles.
 *
 * Leaving a tab empty keeps it visible to everyone who can open the dashboard,
 * so dashboards that never use this are unaffected. Roles are stored by name
 * rather than id so the setting survives an export into another environment.
 *
 * Owners and admins always see every tab - they have to, since saving the
 * dashboard writes back whatever layout their browser holds.
 */
const TabRolesControl = ({
  dashboardId,
  value,
  onChange,
  disabled = false,
}: Props) => {
  const [tabs, setTabs] = useState<{ id: string; title: string }[]>([]);
  const [roleNames, setRoleNames] = useState<string[]>([]);

  useEffect(() => {
    SupersetClient.get({
      endpoint: `/api/v1/dashboard/${dashboardId}/tabs`,
    }).then(
      response => {
        const allTabs = response.json.result?.all_tabs || {};
        setTabs(
          Object.entries(allTabs).map(([id, title]) => ({
            id,
            title: (title as string) || id,
          })),
        );
      },
      () => setTabs([]),
    );
  }, [dashboardId]);

  useEffect(() => {
    SupersetClient.get({
      endpoint: `/api/v1/dashboard/related/roles?q=(page_size:1000)`,
    }).then(
      response =>
        setRoleNames(
          (response.json.result || []).map(
            (item: { text: string }) => item.text,
          ),
        ),
      () => setRoleNames([]),
    );
  }, []);

  if (!tabs.length) {
    return null;
  }

  const handleChange = (tabId: string, selected: string[]) => {
    const next = { ...value };
    if (selected?.length) {
      next[tabId] = selected;
    } else {
      delete next[tabId];
    }
    onChange(next);
  };

  return (
    <>
      <Typography.Title level={4} style={{ marginTop: '1em' }}>
        {t('Tab access')}
      </Typography.Title>
      <Typography.Text type="secondary">
        {t(
          'Restrict a tab to roles. A tab left empty stays visible to everyone who can open this dashboard. Charts under a restricted tab are not readable by users without the role, not merely hidden.',
        )}
      </Typography.Text>
      {tabs.map(tab => (
        <FormItem key={tab.id} label={tab.title}>
          <Select
            allowClear
            ariaLabel={t('Roles allowed on %(tab)s', { tab: tab.title })}
            disabled={disabled}
            mode="multiple"
            onChange={selected =>
              handleChange(tab.id, selected as unknown as string[])
            }
            options={roleNames.map(name => ({ value: name, label: name }))}
            placeholder={t('Visible to everyone')}
            value={value[tab.id] || []}
          />
        </FormItem>
      ))}
    </>
  );
};

export default TabRolesControl;
