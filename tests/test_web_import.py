"""Keyless evidence imports, source preservation and developer API regression."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import requests

from fruit_optimizer import cli
from fruit_optimizer.core import load_catalog, load_prices, profile, ranking, read_json
from fruit_optimizer.evidence import append_catalog, import_web_record, read_web_evidence
from fruit_optimizer.fdc import fetch_fdc
from fruit_optimizer.optimization import plan

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data/fruits.usda-sr-legacy.snapshot.json'
EVIDENCE = ROOT / 'data/web-evidence.mango-tommy-atkins.json'


@pytest.fixture
def evidence():
    return read_json(EVIDENCE)


def imported(evidence):
    return import_web_record(evidence, 'mango_tommy', '芒果（Tommy Atkins）',
                             ['Tommy Atkins芒果'], .7, yield_note='测试规划假设70%')


def test_real_download_example_preserves_source_and_missing_values(evidence):
    original = copy.deepcopy(evidence)
    row = imported(evidence)
    nutrition = row['nutrition_per_100g_edible']
    assert nutrition['potassium_mg'] == 165
    assert nutrition['vitamin_c_mg'] == 25.5
    assert nutrition['fiber_g'] == 1.75
    assert nutrition['energy_kcal'] == 61.6  # Explicit Atwater Specific definition.
    assert nutrition['sugar_g'] is None and nutrition['folate_ug'] is None
    assert row['source']['record_id'] == '2710833'
    assert row['source']['nutrient_evidence'] == evidence['nutrients']
    assert row['source']['original_basis'] == evidence['basis']
    assert row['source']['retrieval_method'] == 'agent_web_evidence'
    row['source']['nutrient_evidence'][0]['value'] = 999
    assert evidence == original  # Import must not modify or share caller's evidence.


@pytest.mark.parametrize('key,value,unit,grams,expected', [
    ('potassium_mg', .33, 'g', 200, 165),
    ('fiber_g', 3500, 'mg', 200, 1.75),
    ('folate_ug', .02, 'mg', 100, 20),
    ('folate_ug', 20, 'μg', 100, 20),
    ('folate_ug', 20, 'µg', 100, 20),
    ('folate_ug', 20, 'ug', 100, 20),
    ('energy_kcal', 418.4, 'kJ', 200, 50),
    ('vitamin_c_mg', 0, 'mg', 100, 0),
])
def test_explicit_unit_and_edible_mass_conversion(evidence, key, value, unit, grams, expected):
    evidence['basis']['amount_g'] = grams
    evidence['nutrients'] = [{'key': key, 'value': value, 'unit': unit,
                              'source_label': 'Synthetic conversion case', 'locator': 'test table row'}]
    row = imported(evidence)
    assert row['nutrition_per_100g_edible'][key] == pytest.approx(expected)
    assert row['source']['nutrient_evidence'][0]['value'] == value
    assert row['source']['original_basis']['amount_g'] == grams


@pytest.mark.parametrize('section,key,value', [
    ('source', 'url', 'http://example.org/food'),
    ('source', 'url', 'https://user:secret@example.org/food'),
    ('source', 'url', 'https://example.org/a b'),
    ('source', 'publisher', ''),
    ('source', 'record_id', None),
    ('source', 'edible_portion', ''),
    ('source', 'food_state', 'cooked'),
    ('source', 'accessed_on', 'not-a-date'),
    ('source', 'accessed_on', '2999-01-01'),
    ('basis', 'amount_g', 0),
    ('basis', 'amount_g', True),
    ('basis', 'amount_g', float('nan')),
    ('basis', 'portion', 'purchased'),
    ('basis', 'portion', 'dry_matter'),
])
def test_incomplete_or_incompatible_source_rejected(evidence, section, key, value):
    evidence[section][key] = value
    with pytest.raises(ValueError):
        imported(evidence)


@pytest.mark.parametrize('key,value', [
    ('value', -1), ('value', float('inf')), ('value', True), ('value', '<0.1'),
    ('unit', 'IU'), ('unit', '%DV'), ('key', 'potasium_mg'),
    ('source_label', ''), ('locator', ''),
])
def test_bad_nutrient_data_rejected(evidence, key, value):
    evidence['nutrients'][0][key] = value
    with pytest.raises(ValueError):
        imported(evidence)


@pytest.mark.parametrize('bad', [None, [], {}, {'schema_version': 1}])
def test_bad_evidence_shape_rejected(bad):
    with pytest.raises(ValueError):
        imported(bad)


def test_missing_and_unknown_schema_fields_rejected(evidence):
    evidence['schema_version'] = True
    with pytest.raises(ValueError):
        imported(evidence)
    evidence['schema_version'] = 1
    evidence['source']['unrecognized'] = 'typo'
    with pytest.raises(ValueError):
        imported(evidence)
    del evidence['source']['unrecognized']
    del evidence['nutrients'][0]['unit']
    with pytest.raises(ValueError):
        imported(evidence)


def test_duplicate_or_conflicting_measurements_rejected(evidence):
    duplicate = copy.deepcopy(evidence['nutrients'][0])
    duplicate['value'] += 1
    evidence['nutrients'].append(duplicate)
    with pytest.raises(ValueError, match='重复或冲突'):
        imported(evidence)


def test_duplicate_json_field_rejected(tmp_path):
    path = tmp_path / 'duplicate.json'
    path.write_text('{"schema_version":1,"schema_version":2}')
    with pytest.raises(ValueError, match='重复字段'):
        read_web_evidence(path)


def test_missing_values_are_not_zero(evidence):
    evidence['nutrients'][0]['value'] = None
    assert imported(evidence)['nutrition_per_100g_edible']['magnesium_mg'] is None
    for n in evidence['nutrients']:
        n['value'] = None
    with pytest.raises(ValueError, match='没有可用'):
        imported(evidence)


@pytest.mark.parametrize('edible,shelf', [(0, 5), (1.1, 5), (.7, 0), (.7, True)])
def test_bad_planning_assumptions_rejected(evidence, edible, shelf):
    with pytest.raises(ValueError):
        import_web_record(evidence, 'm', 'Mango', [], edible, shelf)


def test_import_then_calculate_has_correct_yield_and_missing_exclusion(evidence, tmp_path):
    out = tmp_path / 'catalog.json'
    before = CATALOG.read_bytes()
    append_catalog(CATALOG, out, imported(evidence))
    fruits = load_catalog(out)
    assert len(fruits) == 9 and CATALOG.read_bytes() == before
    price_path = tmp_path / 'prices.json'
    price_path.write_text(json.dumps({'offers': [{'fruit_id': 'mango_tommy', 'amount_cny': 10,
        'measure': 'kg', 'kind': 'simulation', 'location': '测试模拟'}]}))
    prices = load_prices(price_path, fruits, allow_simulation=True)
    p = profile(fruits['mango_tommy'], prices['mango_tommy'])
    assert p['pricing']['nutrient_per_cny']['potassium_mg'] == pytest.approx(115.5)
    assert not ranking(fruits, prices, 'folate_ug')['ranked']
    result = plan(fruits, prices, days=1, nutrient_targets={'potassium_mg': 330},
                  max_daily_energy_kcal=124)
    assert result['total_edible_g'] == pytest.approx(200)
    assert result['total_cost_cny'] == pytest.approx(20 / 7)
    source = result['sources'][0]
    assert source['nutrition_source']['nutrient_evidence'] == evidence['nutrients']
    assert source['record_id'] == '2710833'


@pytest.mark.parametrize('collision', ['id', 'alias'])
def test_invalid_merge_preserves_existing_output(evidence, tmp_path, collision):
    out = tmp_path / 'catalog.json'
    out.write_text('existing output')
    row = imported(evidence)
    if collision == 'id':
        row['id'] = 'banana'
    else:
        row['aliases'].append('香蕉')
    with pytest.raises(ValueError):
        append_catalog(CATALOG, out, row)
    assert out.read_text() == 'existing output'
    assert not list(tmp_path.glob('.fruit-import-*'))


def test_input_and_evidence_cannot_be_overwritten(evidence, tmp_path):
    with pytest.raises(ValueError, match='不同'):
        append_catalog(CATALOG, CATALOG, imported(evidence))
    path = tmp_path / 'evidence.json'
    path.write_text('protected')
    with pytest.raises(ValueError, match='不同'):
        append_catalog(CATALOG, path, imported(evidence), protected_paths=[path])
    assert path.read_text() == 'protected'


def test_atomic_write_failure_cleans_temp_preserves_output(evidence, tmp_path, monkeypatch):
    out = tmp_path / 'catalog.json'
    out.write_text('original')
    def fail(*args):
        raise OSError('test interrupted replace')
    monkeypatch.setattr('fruit_optimizer.evidence.os.replace', fail)
    with pytest.raises(OSError):
        append_catalog(CATALOG, out, imported(evidence))
    assert out.read_text() == 'original'
    assert not list(tmp_path.glob('.fruit-import-*'))


def test_cli_keyless_import_profile_compare(tmp_path):
    out = tmp_path / 'catalog.json'
    env = {k: v for k, v in os.environ.items() if k != 'FDC_API_KEY'}
    def run(*args):
        r = subprocess.run([sys.executable, '-m', 'fruit_optimizer', *map(str, args)],
                           cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    result = run('import-web', EVIDENCE, '--id', 'mango_tommy', '--name', 'Tommy Atkins芒果',
                 '--edible-fraction', '.7', '--yield-note', '测试规划假设', '--out-catalog', out)
    assert result['source']['evidence_sha256'] == hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
    assert result['catalog_sha256'] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert result['audit']['inputs']['evidence']['sha256'] == result['source']['evidence_sha256']
    p = run('--catalog', out, 'profile', 'Tommy Atkins芒果')
    assert p['nutrition']['potassium_mg'] == 165 and 'pricing' not in p
    c = run('--catalog', out, 'compare', 'Tommy Atkins芒果', '香蕉', '--nutrients', '钾')
    assert c['audit']['inputs']['catalog']['sha256'] == result['catalog_sha256']


def test_import_web_does_not_call_network(evidence, tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError('web evidence import must not call API or network')
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)
    monkeypatch.setattr(cli, 'fetch_fdc', forbidden)
    monkeypatch.delenv('FDC_API_KEY', raising=False)
    assert cli.main(['import-web', str(EVIDENCE), '--id', 'mango', '--name', 'Mango',
                     '--edible-fraction', '.7', '--yield-note', 'test assumption',
                     '--out-catalog', str(tmp_path / 'new.json')]) == 0


def test_report_output_cannot_destroy_imported_catalog(tmp_path, capsys):
    out = tmp_path / 'catalog.json'
    rc = cli.main(['--output', str(out), 'import-web', str(EVIDENCE), '--id', 'mango',
                   '--name', 'Mango', '--edible-fraction', '.7', '--yield-note', 'test',
                   '--out-catalog', str(out)])
    assert rc == 2 and not out.exists()
    assert '不可覆盖' in capsys.readouterr().err


def test_developer_fdc_environment_key_still_used(monkeypatch):
    monkeypatch.setenv('FDC_API_KEY', 'TEST_DEVELOPER_KEY')
    class Session:
        def get(self, url, **kwargs):
            assert url == 'https://api.nal.usda.gov/fdc/v1/food/123'
            assert kwargs['params'] == {'api_key': 'TEST_DEVELOPER_KEY'}
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'fdcId': 123, 'dataType': 'Foundation'})
    assert fetch_fdc(123, session=Session())['fdcId'] == 123


def test_developer_fdc_cli_still_imports_and_rejects_collision(tmp_path, monkeypatch, capsys):
    detail = {'fdcId': 123, 'dataType': 'SR Legacy', 'description': 'Test fruit, raw',
              'foodNutrients': [{'nutrient': {'id': 1092, 'unitName': 'mg'}, 'amount': 100}]}
    monkeypatch.setattr(cli, 'fetch_fdc', lambda fid, key: detail)
    out = tmp_path / 'fdc.json'
    args = ['import-fdc', '123', '--id', 'developer_fruit', '--name', 'Developer fruit',
            '--edible-fraction', '.8', '--out-catalog', str(out)]
    assert cli.main(args) == 0
    assert load_catalog(out)['developer_fruit'].nutrition['potassium_mg'] == 100
    capsys.readouterr()
    before = out.read_bytes()
    args[args.index('developer_fruit')] = 'banana'
    assert cli.main(args) == 2
    assert out.read_bytes() == before


def test_developer_network_error_is_readable(tmp_path, monkeypatch, capsys):
    def fail(*args):
        raise requests.ConnectionError('network unavailable: https://example.org/?api_key=PRIVATE_KEY')
    monkeypatch.setattr(cli, 'fetch_fdc', fail)
    rc = cli.main(['import-fdc', '123', '--id', 'x', '--name', 'X',
                   '--edible-fraction', '.7', '--out-catalog', str(tmp_path / 'fdc.json')])
    error = capsys.readouterr().err
    assert rc == 2 and 'FDC API 请求失败' in error
    assert 'PRIVATE_KEY' not in error and 'api_key=' not in error


def test_non_usda_source_keeps_its_identity_in_optimization_report(evidence, tmp_path):
    evidence['source']['dataset'] = 'Official test food composition table'
    evidence['source']['publisher'] = 'Test research institute'
    row = imported(evidence)
    out = tmp_path / 'catalog.json'
    append_catalog(CATALOG, out, row)
    fruits = load_catalog(out)
    prices_path = tmp_path / 'prices.json'
    prices_path.write_text(json.dumps({'offers': [{'fruit_id': 'mango_tommy',
        'amount_cny': 10, 'measure': 'kg', 'kind': 'simulation', 'location': '测试模拟'}]}))
    prices = load_prices(prices_path, fruits, allow_simulation=True)
    result = plan(fruits, prices, days=1)
    assert result['sources'][0]['fdc_id'] is None
    text = cli.render_md(result)
    assert 'Official test food composition table 条目 2710833' in text
    assert 'USDA 条目' not in text
