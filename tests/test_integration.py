import dataclasses
import json
import math
import random
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
import pytest
from fruit_optimizer.core import load_catalog,load_prices,read_json
from fruit_optimizer.optimization import plan
ROOT=Path(__file__).resolve().parents[1]

def command(*args):
    return subprocess.run([sys.executable,'-m','fruit_optimizer',*args],cwd=ROOT,
                          capture_output=True,text=True,timeout=30)

def test_cli_no_prices_is_honest():
    x=command('profile','香蕉')
    assert x.returncode==0
    j=json.loads(x.stdout)
    assert 'pricing' not in j
    assert j['source']['record_id']=='173944'
    assert j['audit']['inputs']['catalog']['sha256']

def test_cli_simulation_explicit():
    x=command('--prices','data/prices.SIMULATION.json','rank','钾')
    assert x.returncode==2 and '模拟' in x.stderr
    y=command('--prices','data/prices.SIMULATION.json','--allow-simulation','rank','钾')
    assert y.returncode==0
    j=json.loads(y.stdout)
    assert all(row['price_kind']=='simulation' for row in j['ranked'])

def test_cli_md_report_has_sources():
    x=command('--prices','data/prices.SIMULATION.json','--allow-simulation','--format','md',
         'optimize','--days','2','--targets','data/targets.EXAMPLE.json')
    assert x.returncode==0
    assert '模拟价格' in x.stdout and 'fdc.nal.usda.gov' in x.stdout

def test_cli_pareto():
    x=command('--prices','data/prices.SIMULATION.json','--allow-simulation','pareto','钾','维生素C')
    assert x.returncode==0
    r=json.loads(x.stdout)
    assert r['frontier']

def test_cli_threshold():
    x=command('--prices','data/prices.SIMULATION.json','--allow-simulation','threshold','香蕉','樱桃','钾')
    assert x.returncode==0
    r=json.loads(x.stdout)
    assert 0<r['break_even_challenger_price_cny_per_kg']<10

def test_cli_invalid_photo_classification_label():
    # CLI intentionally does not hallucinate from arbitrary image path.
    x=command('profile','photo_unknown.jpg')
    assert x.returncode==2 and '未在数据集中找到' in x.stderr

def test_cli_export_file(tmp_path):
    f=tmp_path/'out.json'
    x=command('--output',str(f),'profile','香蕉')
    assert x.returncode==0 and f.exists()
    assert json.loads(f.read_text(encoding='utf-8'))['id']=='banana'

def test_cli_audit_hashes():
    x=command('--prices','data/prices.SIMULATION.json','--allow-simulation','--as-of','2026-10-16','optimize','--days','1')
    assert x.returncode==0
    audit=json.loads(x.stdout)['audit']
    assert set(audit['inputs'])=={'catalog','prices'}
    assert audit['analysis_date']=='2026-10-16'

def test_deterministic_repeated_same_scenario():
    fr=load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
    pr=load_prices(ROOT/'data/prices.SIMULATION.json',fr,allow_simulation=True)
    a=plan(fr,pr,days=3,min_fruit_types=3,nutrient_targets={'vitamin_c_mg':30,'potassium_mg':450})
    b=plan(fr,pr,days=3,min_fruit_types=3,nutrient_targets={'vitamin_c_mg':30,'potassium_mg':450})
    assert a['total_cost_cny']==pytest.approx(b['total_cost_cny'])
    for k in a['nutrient_coverage']:
        for metric in a['nutrient_coverage'][k]:
            assert a['nutrient_coverage'][k][metric]==pytest.approx(b['nutrient_coverage'][k][metric])

def test_expected_daily_weights_are_finite():
    fr=load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
    pr=load_prices(ROOT/'data/prices.SIMULATION.json',fr,allow_simulation=True)
    for days in (1,3,7):
        for count in (1,2,3):
            x=plan(fr,pr,days=days,min_fruit_types=count)
            assert x['status']=='optimal'
            assert len(x['daily_plan'])==days
            assert math.isfinite(x['total_cost_cny'])
            assert sum(p['cost_cny'] for p in x['purchases'])==pytest.approx(x['total_cost_cny'])
            assert all(200-1e-4<=d['edible_g']<=350+1e-4 for d in x['daily_plan'])

def test_increasing_min_types_does_not_lower_cost():
    fr=load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
    pr=load_prices(ROOT/'data/prices.SIMULATION.json',fr,allow_simulation=True)
    costs=[plan(fr,pr,days=3,min_fruit_types=k)['total_cost_cny'] for k in (1,2,3,4)]
    assert all(costs[i+1]>=costs[i]-1e-5 for i in range(len(costs)-1))

def test_more_expensive_same_nutrition_does_not_decrease_min_cost():
    fr=load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
    pr=load_prices(ROOT/'data/prices.SIMULATION.json',fr,allow_simulation=True)
    start=plan(fr,pr,days=2)['total_cost_cny']
    from dataclasses import replace
    pr2={k:replace(v,price_per_kg=2*v.price_per_kg) for k,v in pr.items()}
    end=plan(fr,pr2,days=2)['total_cost_cny']
    assert end==pytest.approx(2*start,abs=1e-5)

def test_all_zero_energy_is_not_faked():
    fr=load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
    pr=load_prices(ROOT/'data/prices.SIMULATION.json',fr,allow_simulation=True)
    fr2={'banana':dataclasses.replace(fr['banana'],nutrition={**fr['banana'].nutrition,'energy_kcal':None})}
    with pytest.raises(ValueError,match='数量不足'):
        plan(fr2,pr,days=1,max_daily_energy_kcal=40)
