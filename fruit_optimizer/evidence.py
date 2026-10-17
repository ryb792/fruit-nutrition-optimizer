"""Import source evidence collected by a web-capable Agent; no network or API key.

Validation covers structure, units and accounting basis. The host must actually
open and check the primary source; a valid JSON file is not proof of its truth.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .core import (UNITS, catalog_from_rows, finite_nonnegative, fraction,
                   read_json, write_json)


def read_web_evidence(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f'证据 JSON 存在重复字段: {key}')
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} 必须是非空文本')
    return value.strip()


def _object(value, fields, required, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} 必须是对象')
    unknown = set(value) - set(fields)
    missing = set(required) - set(value)
    if unknown or missing:
        raise ValueError(f'{label} 字段错误：未知 {sorted(unknown)}；缺少 {sorted(missing)}')


def _url(value):
    url = _text(value, 'source.url')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('source.url 必须是无登录凭据的完整 HTTPS 来源网址')
    if any(c.isspace() for c in url):
        raise ValueError('source.url 不可含空白')
    return url


def _amount(value, unit, key, basis_g):
    unit = _text(unit, f'{key}.unit').casefold().replace('μ', 'u').replace('µ', 'u')
    target = UNITS[key].replace('µ', 'u')
    mass = {'g': 1.0, 'mg': 0.001, 'ug': 0.000001}
    if target == 'kcal':
        if unit not in ('kcal', 'kj'):
            raise ValueError(f'{key} 只接受 kcal 或 kJ')
        factor = 1.0 if unit == 'kcal' else 1 / 4.184
    else:
        if unit not in mass:
            raise ValueError(f'{key} 单位须为 g、mg 或 µg，不能使用 {unit}')
        factor = mass[unit] / mass[target]
    if value is None:
        return None
    n = finite_nonnegative(value, key)
    return finite_nonnegative(n * factor * (100 / basis_g), f'{key}.归一值')


def import_web_record(evidence, fid, name, aliases, edible_fraction, shelf_days=5,
                      *, yield_note='用户或 Agent 明确给定的规划假设；非营养来源确认'):
    """Normalize one explicitly identified raw fruit; retain all original evidence."""
    _object(evidence, ('schema_version', 'source', 'basis', 'nutrients'),
            ('schema_version', 'source', 'basis', 'nutrients'), 'evidence')
    if type(evidence['schema_version']) is not int or evidence['schema_version'] != 1:
        raise ValueError('schema_version 必须为整数 1')
    source = evidence['source']
    required = ('publisher', 'dataset', 'record_id', 'url', 'accessed_on',
                'food_description', 'food_state', 'edible_portion')
    _object(source, (*required, 'publication_date'), required, 'source')
    for field in required:
        _text(source[field], f'source.{field}')
    _url(source['url'])
    try:
        accessed = dt.date.fromisoformat(source['accessed_on'])
    except ValueError:
        raise ValueError('source.accessed_on 必须是 YYYY-MM-DD 日期') from None
    if accessed.isoformat() != source['accessed_on'] or accessed > dt.date.today():
        raise ValueError('source.accessed_on 必须为非未来的 YYYY-MM-DD 日期')
    if source['food_state'] != 'raw':
        raise ValueError('仅可导入已确认的生鲜 raw 条目；加工品不可冒充鲜果')
    if 'publication_date' in source:
        _text(source['publication_date'], 'source.publication_date')
    basis = evidence['basis']
    _object(basis, ('amount_g', 'portion'), ('amount_g', 'portion'), 'basis')
    basis_g = finite_nonnegative(basis['amount_g'], 'basis.amount_g', allow_zero=False)
    if basis['portion'] != 'edible':
        raise ValueError('basis.portion 必须为 edible，禁止将购入总重或干物质冒充可食部')
    rows = evidence['nutrients']
    if not isinstance(rows, list) or not rows:
        raise ValueError('nutrients 必须是非空数组')
    nutrition = dict.fromkeys(UNITS)
    seen = set()
    for row in rows:
        fields = ('key', 'value', 'unit', 'source_label', 'locator')
        _object(row, fields, fields, 'nutrient')
        key = _text(row['key'], 'nutrient.key')
        if key not in UNITS:
            raise ValueError(f'不支持的营养素字段: {key}')
        if key in seen:
            raise ValueError(f'营养素重复或冲突: {key}；先核验定义，不可平均合并')
        seen.add(key)
        _text(row['source_label'], f'{key}.source_label')
        _text(row['locator'], f'{key}.locator')
        nutrition[key] = _amount(row['value'], row['unit'], key, basis_g)
    if all(v is None for v in nutrition.values()):
        raise ValueError('没有可用的已确认营养值')
    fraction(edible_fraction, 'edible_fraction', positive=True)
    if type(shelf_days) is not int or shelf_days < 1:
        raise ValueError('shelf_days 必须为正整数')
    if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() for a in aliases):
        raise ValueError('aliases 必须为非空文本的数组')
    src = copy.deepcopy(source)
    src['description'] = src.pop('food_description')
    src['retrieval_method'] = 'agent_web_evidence'
    src['original_basis'] = copy.deepcopy(basis)
    src['nutrient_evidence'] = copy.deepcopy(rows)
    src['validation_note'] = '程序校验结构、单位和口径；来源真实性及品种匹配须由宿主查证'
    return {'id': _text(fid, 'id'), 'name': _text(name, 'name'),
            'aliases': [a.strip() for a in aliases],
            'nutrition_per_100g_edible': nutrition,
            'edible_fraction': edible_fraction, 'extra_waste_fraction': 0.0,
            'shelf_days': shelf_days, 'source': src,
            'yield_source': {'type': 'user_assumption', 'note': _text(yield_note, 'yield_note')},
            'shelf_source': {'type': 'planning_assumption', 'note': '显式规划参数，非营养数据来源确认'}}


def append_catalog(catalog_path, output_path, row, *, protected_paths=()):
    """Validate the merged catalog before atomically replacing a separate output."""
    output = Path(output_path)
    if output.resolve() in {Path(p).resolve() for p in (catalog_path, *protected_paths)}:
        raise ValueError('输出目录文件必须与输入目录及原始证据文件不同')
    rows = read_json(catalog_path)
    if not isinstance(rows, list):
        raise ValueError('水果目录须为数组')
    merged = [*rows, row]
    catalog_from_rows(merged)  # Detect ID/alias collisions before touching output.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.fruit-import-',
                                         suffix='.json', delete=False) as handle:
            temp_path = Path(handle.name)
        write_json(temp_path, merged)
        os.replace(temp_path, output)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return hashlib.sha256(output.read_bytes()).hexdigest()
