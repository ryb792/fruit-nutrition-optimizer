"""Synthetic quotes test reference labels and arithmetic, not current market facts."""
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fruit_optimizer import cli
from fruit_optimizer.core import (load_catalog, load_prices, profile, ranking,
                                 compare, substitutes)
from fruit_optimizer.optimization import (plan, pareto_fruits, break_even_price,
                                         execute_v11)

ROOT = Path(__file__).resolve().parents[1]
AS_OF = dt.date(2026, 10, 17)


@pytest.fixture
def fruits():
    return load_catalog(ROOT / 'data/fruits.usda-sr-legacy.snapshot.json')


@pytest.fixture
def offer():
    return {'fruit_id': 'banana', 'amount_cny': 3, 'measure': 'jin',
            'location': '测试城市', 'kind': 'reference_retail',
            'observed_on': '2026-10-16',
            'source_url': 'https://prices.example.test/retail/2026-10-16',
            'source_note': '合成测试数据：零售香蕉3元/市斤；不是真实市场报价'}


def prices_from(tmp_path, fruits, offers, **kwargs):
    p = tmp_path / 'prices.json'
    p.write_text(json.dumps({'offers': offers}, ensure_ascii=False), encoding='utf-8')
    return load_prices(p, fruits, as_of=AS_OF, **kwargs)


def test_reference_is_not_simulation_and_retains_quote_evidence(tmp_path, fruits, offer):
    prices = prices_from(tmp_path, fruits, [offer])
    price = prices['banana']
    assert price.is_reference and not price.is_simulated
    result = profile(fruits['banana'], price)['pricing']
    assert result['price_cny_per_kg'] == 6  # Chinese jin -> kg.
    assert result['nutrient_per_cny']['potassium_mg'] == pytest.approx(387.833333333)
    assert result['kind'] == 'reference_retail'
    assert result['observed_on'] == '2026-10-16'
    assert result['location'] == offer['location']
    assert result['source_url'] == offer['source_url']
    assert result['price_context']['reference_used']
    assert not result['price_context']['simulation_used']
    assert '非用户实际成交价' in result['price_context']['notice']


@pytest.mark.parametrize('key,value', [
    ('source_url', None), ('source_url', ''), ('source_url', 'not-a-url'),
    ('source_url', 'https://user:password@example.test/retail'),
    ('source_note', ''), ('source_note', None), ('location', ''), ('location', None),
    ('observed_on', None), ('observed_on', '2026-10-18'),
    ('kind', 'wholesale'), ('kind', 'reference_wholesale'),
])
def test_unusable_or_wholesale_reference_rejected(tmp_path, fruits, offer, key, value):
    offer[key] = value
    with pytest.raises(ValueError):
        prices_from(tmp_path, fruits, [offer])


def test_old_reference_requires_explicit_flag_keeps_original_date(tmp_path, fruits, offer):
    offer['observed_on'] = '2026-10-01'
    with pytest.raises(ValueError, match='过期'):
        prices_from(tmp_path, fruits, [offer])
    prices = prices_from(tmp_path, fruits, [offer], allow_stale=True)
    assert profile(fruits['banana'], prices['banana'])['pricing']['observed_on'] == '2026-10-01'


def test_reference_and_actual_quotes_keep_separate_identity(tmp_path, fruits, offer):
    actual = {**offer, 'fruit_id': 'apple', 'kind': 'user_receipt',
              'amount_cny': 4, 'source_note': '合成收据测试；不是实际交易'}
    prices = prices_from(tmp_path, fruits, [offer, actual])
    compared = compare(fruits, prices, '香蕉', '苹果', ['钾'])
    assert compared['a']['pricing']['kind'] == 'reference_retail'
    assert compared['b']['pricing']['kind'] == 'user_receipt'
    rank = ranking(fruits, prices, 'potassium_mg')
    assert rank['ranked_count'] == 2 and rank['price_context']['reference_used']
    assert rank['ranked'][0]['price_source']['location'] == offer['location']
    assert substitutes(fruits, prices, '香蕉', ['钾'])['price_context']['reference_used']


def test_different_locations_cannot_be_silently_combined(tmp_path, fruits, offer):
    second = {**offer, 'fruit_id': 'apple', 'location': '另一测试城市'}
    with pytest.raises(ValueError, match='不同地区'):
        prices_from(tmp_path, fruits, [offer, second])


def test_price_qualifications_survive_pareto_threshold_and_optimization(tmp_path, fruits, offer):
    prices = prices_from(tmp_path, fruits, [offer])
    pareto = pareto_fruits(fruits, prices, ['钾', '维生素C'])
    assert pareto['price_context']['reference_used']
    assert pareto['frontier'][0]['pricing']['observed_on'] == offer['observed_on']
    threshold = break_even_price(fruits, prices, '香蕉', '苹果', '钾')
    assert threshold['price_context']['reference_used']
    assert threshold['baseline_pricing']['source_url'] == offer['source_url']
    assert threshold['challenger_pricing'] is None
    result = plan(fruits, prices, days=1)
    assert result['total_cost_cny'] == pytest.approx(200 / .65 / 1000 * 6)
    assert result['price_context']['reference_used']
    assert not result['price_context']['simulation_used']
    assert result['sources'][0]['price_location'] == offer['location']
    assert result['sources'][0]['price_date'] == offer['observed_on']


def test_budget_frontier_keeps_reference_label_and_sources(tmp_path, fruits, offer):
    prices = prices_from(tmp_path, fruits, [offer])
    args = SimpleNamespace(command='frontier', budgets=[5], days=1, min_types=1,
                           targets=str(ROOT / 'data/targets.EXAMPLE.json'))
    result = execute_v11(args, fruits, prices)
    assert result['price_context']['reference_used']
    assert result['samples'][0]['price_context']['reference_used']
    assert result['samples'][0]['sources'][0]['price_source_url'] == offer['source_url']


def test_markdown_never_drops_reference_qualification(tmp_path, fruits, offer):
    prices = prices_from(tmp_path, fruits, [offer])
    reports = [profile(fruits['banana'], prices['banana']),
               ranking(fruits, prices, 'potassium_mg'), plan(fruits, prices, days=1)]
    for data in reports:
        text = cli.render_md(data)
        assert '参考价' in text and '非用户实际成交价' in text
        assert offer['location'] in text and offer['observed_on'] in text
        assert offer['source_url'] in text


def test_cli_reference_validate_and_rank_without_simulation_flag(tmp_path, fruits, offer, capsys):
    prices_from(tmp_path, fruits, [offer])
    args = ['--prices', str(tmp_path / 'prices.json'), '--as-of', AS_OF.isoformat()]
    assert cli.main([*args, 'validate']) == 0
    check = json.loads(capsys.readouterr().out)
    assert check['price_context']['reference_used'] and not check['simulation_used']
    assert cli.main([*args, 'rank', '钾']) == 0
    rank = json.loads(capsys.readouterr().out)
    assert rank['ranked'][0]['price_kind'] == 'reference_retail'
    assert '模拟' not in rank['price_context']['notice']


def test_reference_template_has_no_accidentally_usable_quote(fruits):
    with pytest.raises(ValueError):
        load_prices(ROOT / 'data/prices.reference.template.json', fruits, as_of=AS_OF)
