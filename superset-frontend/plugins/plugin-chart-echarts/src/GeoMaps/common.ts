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
import { registerMap } from 'echarts/core';

/** geojson 静态资源目录（部署于 Superset static，见 custom/pb_map/geojson） */
export const GEOJSON_BASE = '/static/assets/custom/pb_map/geojson/';

export interface ProvinceInfo {
  code: string; // DataV adcode
  name: string; // geojson 全名
  short: string;
  iso: string; // ISO 3166-2
}

export const PROVINCES: ProvinceInfo[] = [
  { code: '110000', name: '北京市', short: '北京', iso: 'CN-BJ' },
  { code: '120000', name: '天津市', short: '天津', iso: 'CN-TJ' },
  { code: '130000', name: '河北省', short: '河北', iso: 'CN-HE' },
  { code: '140000', name: '山西省', short: '山西', iso: 'CN-SX' },
  { code: '150000', name: '内蒙古自治区', short: '内蒙古', iso: 'CN-NM' },
  { code: '210000', name: '辽宁省', short: '辽宁', iso: 'CN-LN' },
  { code: '220000', name: '吉林省', short: '吉林', iso: 'CN-JL' },
  { code: '230000', name: '黑龙江省', short: '黑龙江', iso: 'CN-HL' },
  { code: '310000', name: '上海市', short: '上海', iso: 'CN-SH' },
  { code: '320000', name: '江苏省', short: '江苏', iso: 'CN-JS' },
  { code: '330000', name: '浙江省', short: '浙江', iso: 'CN-ZJ' },
  { code: '340000', name: '安徽省', short: '安徽', iso: 'CN-AH' },
  { code: '350000', name: '福建省', short: '福建', iso: 'CN-FJ' },
  { code: '360000', name: '江西省', short: '江西', iso: 'CN-JX' },
  { code: '370000', name: '山东省', short: '山东', iso: 'CN-SD' },
  { code: '410000', name: '河南省', short: '河南', iso: 'CN-HA' },
  { code: '420000', name: '湖北省', short: '湖北', iso: 'CN-HB' },
  { code: '430000', name: '湖南省', short: '湖南', iso: 'CN-HN' },
  { code: '440000', name: '广东省', short: '广东', iso: 'CN-GD' },
  { code: '450000', name: '广西壮族自治区', short: '广西', iso: 'CN-GX' },
  { code: '460000', name: '海南省', short: '海南', iso: 'CN-HI' },
  { code: '500000', name: '重庆市', short: '重庆', iso: 'CN-CQ' },
  { code: '510000', name: '四川省', short: '四川', iso: 'CN-SC' },
  { code: '520000', name: '贵州省', short: '贵州', iso: 'CN-GZ' },
  { code: '530000', name: '云南省', short: '云南', iso: 'CN-YN' },
  { code: '540000', name: '西藏自治区', short: '西藏', iso: 'CN-XZ' },
  { code: '610000', name: '陕西省', short: '陕西', iso: 'CN-SN' },
  { code: '620000', name: '甘肃省', short: '甘肃', iso: 'CN-GS' },
  { code: '630000', name: '青海省', short: '青海', iso: 'CN-QH' },
  { code: '640000', name: '宁夏回族自治区', short: '宁夏', iso: 'CN-NX' },
  { code: '650000', name: '新疆维吾尔自治区', short: '新疆', iso: 'CN-XJ' },
  { code: '710000', name: '台湾省', short: '台湾', iso: 'CN-71' },
  { code: '810000', name: '香港特别行政区', short: '香港', iso: 'CN-91' },
  { code: '820000', name: '澳门特别行政区', short: '澳门', iso: 'CN-92' },
];

export const MAP_CHOICES: [string, string][] = [
  ['china', '中国（省级）'],
  ['world', '世界（国家）'],
  ...PROVINCES.map(p => [p.code, `${p.short}（市级）`] as [string, string]),
];

const geoCache: Record<string, Promise<any>> = {};

export function mapUrl(scope: string): string {
  if (scope === 'china') return `${GEOJSON_BASE}100000_full.json`;
  if (scope === 'world') return `${GEOJSON_BASE}world.json`;
  return `${GEOJSON_BASE}${scope}_full.json`;
}

/** 加载 geojson 并 registerMap（带缓存），返回 geojson */
export function ensureMap(scope: string): Promise<any> {
  if (!geoCache[scope]) {
    geoCache[scope] = fetch(mapUrl(scope), { credentials: 'same-origin' })
      .then(r => {
        if (!r.ok) throw new Error(`加载地图 geojson 失败：HTTP ${r.status}`);
        return r.json();
      })
      .then(gj => {
        registerMap(scope, gj);
        return gj;
      });
    geoCache[scope].catch(() => {
      delete geoCache[scope];
    });
  }
  return geoCache[scope];
}

const SUFFIX_RE =
  /(维吾尔自治区|壮族自治区|回族自治区|特别行政区|自治区|自治州|地区|省|市|盟)$/;

export function shortRegionName(name: string): string {
  return String(name || '').replace(SUFFIX_RE, '');
}

const WORLD_ALIAS: Record<string, string> = {
  中国: 'China',
  美国: 'United States',
  日本: 'Japan',
  韩国: 'Korea',
  德国: 'Germany',
  法国: 'France',
  英国: 'United Kingdom',
  俄罗斯: 'Russia',
  加拿大: 'Canada',
  澳大利亚: 'Australia',
};

/**
 * 构造 数据列值 -> geojson feature 名 的匹配器。
 * 支持：完全一致、CN-XX ISO 编码、中文简称前缀（"广东"→"广东省"、"泉州"→"泉州市"）、
 * 常见国家中文名（世界地图）。
 */
export function buildRegionMatcher(
  featureNames: string[],
): (raw: unknown) => string | null {
  const exact = new Map<string, string>();
  const byShort = new Map<string, string>();
  featureNames.forEach(n => {
    exact.set(n, n);
    const s = shortRegionName(n);
    if (!byShort.has(s)) byShort.set(s, n);
  });
  const byIso = new Map<string, string>();
  PROVINCES.forEach(p => {
    const f = byShort.get(p.short) || exact.get(p.name);
    if (f) byIso.set(p.iso, f);
  });
  return (raw: unknown) => {
    if (raw === null || raw === undefined) return null;
    const s = String(raw).trim();
    if (!s) return null;
    return (
      exact.get(s) ||
      byIso.get(s.toUpperCase()) ||
      byShort.get(shortRegionName(s)) ||
      exact.get(WORLD_ALIAS[s] || '') ||
      null
    );
  };
}

/** 气泡半径映射：按值的平方根缩放到 [minSize, maxSize] */
export function sizeScale(
  value: number,
  maxValue: number,
  minSize: number,
  maxSize: number,
): number {
  if (!maxValue || !Number.isFinite(value) || value <= 0) return minSize;
  return minSize + Math.sqrt(value / maxValue) * (maxSize - minSize);
}
