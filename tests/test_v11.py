import dataclasses
import json
import itertools
from pathlib import Path
from collections import defaultdict
from types import SimpleNamespace
import pytest
from fruit_optimizer.core import load_catalog,load_prices,read_json,apply_yield_overrides,nutrient_per_cny
from fruit_optimizer.optimization import pareto_fruits,break_even_price,plan,parse_targets,execute_v11
from fruit_optimizer.cli import build_parser, execute

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def fruits():return load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
@pytest.fixture
def prices(fruits):return load_prices(ROOT/'data/prices.SIMULATION.json',fruits,allow_simulation=True)

@pytest.mark.parametrize('keys',[['钾'],['维生素C','钾'],['fiber_g','vitamin_c_mg','vitamin_b6_mg']])
def test_pareto_nutrition_scope(fruits,prices,keys):
    r=pareto_fruits(fruits,prices,keys)
    assert len(r['frontier'])>=1
    assert len(r['frontier'])+len(r['dominated'])==8
    for d in r['dominated']:assert d['dominated_by']

def test_pareto_single_metric_equals_winner(fruits,prices):
    r=pareto_fruits(fruits,prices,['钾'])
    from fruit_optimizer.core import ranking
    top=ranking(fruits,prices,'钾')['ranked'][0]['fruit_id']
    assert top in [x['fruit_id'] for x in r['frontier']]

def test_pareto_unknown_excluded(fruits,prices):
    fr=dict(fruits)
    fr['banana']=dataclasses.replace(fr['banana'],nutrition={**fr['banana'].nutrition,'vitamin_c_mg':None})
    r=pareto_fruits(fr,prices,['vitamin_c_mg'])
    assert '缺失' in [x['reason'] for x in r['excluded'] if x['fruit']=='香蕉'][0]

def test_break_even_is_precise(fruits,prices):
    r=break_even_price(fruits,prices,'香蕉','樱桃','钾')
    from dataclasses import replace
    p=replace(prices['cherry'],price_per_kg=r['break_even_challenger_price_cny_per_kg'])
    assert nutrient_per_cny(fruits['banana'],prices['banana'],'钾')==pytest.approx(nutrient_per_cny(fruits['cherry'],p,'钾'))

def test_targets_require_scoped_explanation(tmp_path):
    x=tmp_path/'targets.json'
    x.write_text(json.dumps({'target_scope':'whole_diet','targets_per_day':{'potassium_mg':3000},'source':'example'}),encoding='utf8')
    with pytest.raises(ValueError,match='fruit_contribution_only'):parse_targets(x)

def test_targets_example():
    targets,metadata=parse_targets(ROOT/'data/targets.EXAMPLE.json')
    assert targets['potassium_mg']==450
    assert metadata['source'].startswith('User-selected')

def test_min_cost_solution_satisfies_all(fruits,prices):
    s=plan(fruits,prices,days=7,min_fruit_types=3,nutrient_targets={'potassium_mg':450,'vitamin_c_mg':30,'fiber_g':5})
    assert s['status']=='optimal'
    assert len(s['daily_plan'])==7
    assert s['fruit_type_count']>=3
    assert len(s['sources'])==8
    assert all(200-1e-4<=x['edible_g']<=350+1e-4 for x in s['daily_plan'])
    assert all(c['completion_fraction']>=1-1e-5 for c in s['nutrient_coverage'].values())

def test_budget_maximin_valid(fruits,prices):
    r=plan(fruits,prices,days=3,budget_cny=9,objective='maximin',
        nutrient_targets={'potassium_mg':450,'vitamin_c_mg':30,'fiber_g':5},min_fruit_types=2)
    assert r['status']=='optimal'
    assert 0<=r['maximin_fraction']<=1
    assert r['total_cost_cny']<=9+1e-4
    assert all(x['completion_fraction']>=r['maximin_fraction']-1e-5 for x in r['nutrient_coverage'].values())

def test_budget_too_low_infeasible(fruits,prices):
    with pytest.raises(ValueError,match='无可行解'):
        plan(fruits,prices,days=2,budget_cny=0.01,objective='maximin',nutrient_targets={'potassium_mg':400})

def test_targets_impossible_infeasible(fruits,prices):
    with pytest.raises(ValueError,match='无可行解'):
        plan(fruits,prices,days=1,nutrient_targets={'potassium_mg':9000})

def test_min_cost_independent_analytical(fruits,prices):
    # Single-day, exactly 200g, with no nutrients and one type allowed:
    # cheapest edible gram is analytically optimal, except packs may be dearer;
    # remove fixed packs for this specific proof.
    fr={k:v for k,v in fruits.items() if prices[k].package_kg is None}
    pr={k:v for k,v in prices.items() if k in fr}
    best=min(200*prices[f.id].price_per_kg/(1000*f.yield_fraction) for f in fr.values())
    s=plan(fr,pr,days=1,min_daily_g=200,max_daily_g=200,min_fruit_types=1)
    assert s['total_cost_cny']==pytest.approx(best,abs=1e-6)

def test_two_fruit_exact_bruteforce_pack(fruits,prices):
    # Independent enumeration of whole boxes: one packaged 250g strawberry or 500g kiwi.
    # Require exactly 200g edible consumption. Enumeration checks MILP integer correctness.
    fr={k:fruits[k] for k in ('strawberry','kiwi_green')}
    pr={k:prices[k] for k in fr}
    brute=min(pr['strawberry'].package_cost()*a+pr['kiwi_green'].package_cost()*b
      for a in range(10) for b in range(10)
      if 1000*fr['strawberry'].yield_fraction*pr['strawberry'].package_kg*a+
        1000*fr['kiwi_green'].yield_fraction*pr['kiwi_green'].package_kg*b>=200)
    sol=plan(fr,pr,days=1,min_daily_g=200,max_daily_g=200)
    assert sol['total_cost_cny']==pytest.approx(brute,abs=1e-6)
    assert all(p['packages'] is not None and p['packages']==int(p['packages']) for p in sol['purchases'])

def test_stock_respects_shelf_life(fruits,prices):
    # Packaged strawberry lasts 1 day; needs fresh purchase each day when it is the only candidate.
    fr={'strawberry':dataclasses.replace(fruits['strawberry'],shelf_days=1)}
    pr={'strawberry':prices['strawberry']}
    x=plan(fr,pr,days=3,min_daily_g=200,max_daily_g=200)
    assert set(p['day'] for p in x['purchases'])=={1,2,3}
    assert all(p['packages']==1 for p in x['purchases'])

def test_no_false_package_leftover_waste(fruits,prices):
    x=plan({'kiwi_green':fruits['kiwi_green']},{'kiwi_green':prices['kiwi_green']},days=1,min_daily_g=200,max_daily_g=200)
    p=x['purchases'][0]
    assert p['edible_capacity_g']==pytest.approx(380)
    assert p['unconsumed_edible_g']==pytest.approx(180)

def test_energy_constraint(fruits,prices):
    x=plan(fruits,prices,days=2,max_daily_energy_kcal=110)
    assert all(day['nutrition']['energy_kcal']<=110+1e-4 for day in x['daily_plan'])

def test_energy_impossible(fruits,prices):
    with pytest.raises(ValueError,match='无可行解'):
        plan(fruits,prices,days=1,max_daily_energy_kcal=2)

def test_variety_impossible(fruits,prices):
    with pytest.raises(ValueError,match='超过'):
        plan(fruits,prices,days=1,min_fruit_types=3,min_total_each_type_g=140)

def test_variety_constraint(fruits,prices):
    x=plan(fruits,prices,days=2,min_fruit_types=4,min_total_each_type_g=60)
    assert x['fruit_type_count']>=4
    totals=defaultdict(float)
    for d in x['daily_plan']:
        for z in d['fruits']:totals[z['fruit_id']]+=z['edible_g']
    assert sum(v>=59.999 for v in totals.values())>=4

def test_trip_fee_adds_only_per_shopping_day(fruits,prices):
    fr={'banana':fruits['banana']};pr={'banana':prices['banana']}
    x=plan(fr,pr,days=3,trip_fee_cny=2)
    assert x['shopping_days']==[1,2,3]
    assert x['total_trip_fees_cny']==6
    assert x['total_cost_cny']==pytest.approx(sum(p['cost_cny'] for p in x['purchases'])+6)

def test_trip_fee_pack_single_trip(fruits,prices):
    fr={'kiwi_green':fruits['kiwi_green']};pr={'kiwi_green':prices['kiwi_green']}
    x=plan(fr,pr,days=2,trip_fee_cny=10)
    assert x['shopping_days'] and len(x['shopping_days'])==1
    assert x['total_trip_fees_cny']==10

def test_yield_override(tmp_path,fruits):
    x=tmp_path/'overrides.json'
    x.write_text(json.dumps({'overrides':{'banana':{'edible_fraction':.5,'extra_waste_fraction':.1,'shelf_days':2,
        'source_note':'test weighed 2 kg'}}}),encoding='utf8')
    f=apply_yield_overrides(fruits,x)
    assert f['banana'].yield_fraction==pytest.approx(.45)
    assert f['banana'].shelf_days==2
    assert fruits['banana'].yield_fraction==.65

def test_yield_override_requires_evidence(tmp_path,fruits):
    x=tmp_path/'overrides.json';x.write_text(json.dumps({'overrides':{'banana':{'edible_fraction':.8}}}),encoding='utf8')
    with pytest.raises(ValueError,match='来源'):apply_yield_overrides(fruits,x)

@pytest.mark.parametrize('kwargs',[{'days':0},{'days':32},{'min_daily_g':-1},
    {'max_daily_g':1001},{'objective':'random'},{'budget_cny':-1},
    {'min_fruit_types':0},{'trip_fee_cny':float('nan')},{'min_daily_g':400,'max_daily_g':200}])
def test_invalid_params_are_rejected(fruits,prices,kwargs):
    with pytest.raises(ValueError):plan(fruits,prices,**kwargs)

def test_maximin_needs_budget_and_targets(fruits,prices):
    with pytest.raises(ValueError):plan(fruits,prices,objective='maximin')
    with pytest.raises(ValueError):plan(fruits,prices,objective='maximin',budget_cny=20)

def test_unknown_nutrients_exclude_no_zero(fruits,prices):
    f=dataclasses.replace(fruits['banana'],nutrition={**fruits['banana'].nutrition,'potassium_mg':None})
    x=plan({'banana':f,'cherry':fruits['cherry']},prices,days=1,nutrient_targets={'potassium_mg':200})
    assert any(r['fruit']=='香蕉' for r in x['excluded_candidates'])
    assert all(p['fruit_id']=='cherry' for p in x['purchases'])

def test_no_price_not_optimizable(fruits):
    with pytest.raises(ValueError,match='数量不足'):
        plan(fruits,{})

def test_budget_frontier_samples(fruits,prices):
    args=SimpleNamespace(command='frontier',budgets=[.01,10,20],targets=str(ROOT/'data/targets.EXAMPLE.json'),days=1,min_types=2)
    r=execute_v11(args,fruits,prices)
    assert any(s.get('status')=='infeasible' for s in r['samples'])
    assert len(r['sampled_nondominated'])>=1

def test_cli_smoke_v11(fruits,prices):
    parser=build_parser()
    args=parser.parse_args(['--prices',str(ROOT/'data/prices.SIMULATION.json'),'--allow-simulation',
        'optimize','--days','2','--targets',str(ROOT/'data/targets.EXAMPLE.json')])
    x=execute(args)
    assert x['status']=='optimal'

def test_safe_price_threshold_zero_nutrient(fruits,prices):
    fr=dict(fruits);f=fr['banana']
    fr['banana']=dataclasses.replace(f,nutrition={**f.nutrition,'potassium_mg':0})
    with pytest.raises(ValueError):break_even_price(fr,prices,'banana','樱桃','钾')


def test_full_waste_rejected_instead_of_division_by_zero(tmp_path,fruits):
    data=read_json(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
    data[0]['extra_waste_fraction']=1
    path=tmp_path/'bad.json'
    path.write_text(json.dumps(data),encoding='utf8')
    with pytest.raises(ValueError,match='100%'):load_catalog(path)

