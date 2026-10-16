import datetime as dt
import json
import math
from pathlib import Path
from types import SimpleNamespace
import pytest
from fruit_optimizer.core import (load_catalog,load_prices,profile,resolve,compare,substitutes,nutrient_per_cny,read_json)
from fruit_optimizer.fdc import nutrition_from_detail,fetch_fdc,import_fdc_record

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def fruits():return load_catalog(ROOT/'data/fruits.usda-sr-legacy.snapshot.json')
@pytest.fixture
def prices(fruits):return load_prices(ROOT/'data/prices.SIMULATION.json',fruits,allow_simulation=True)

def test_v10_catalog(fruits):assert len(fruits)==8
@pytest.mark.parametrize('alias,fid',[('香蕉','banana'),('banana','banana'),('樱桃','cherry'),('车厘子','cherry'),('KiWi','kiwi_green')])
def test_alias(fruits,alias,fid):assert resolve(fruits,alias).id==fid

def test_mandatory_source(fruits):
    for f in fruits.values():
        assert f.source['url'].startswith('https://fdc.nal.usda.gov/food-details/')
        assert f.source['record_id'] and f.yield_source['type']

def test_per_100g_raw(fruits):
    b=resolve(fruits,'香蕉');c=resolve(fruits,'樱桃')
    assert b.nutrition['potassium_mg']==358
    assert c.nutrition['potassium_mg']==222
    assert b.nutrition['potassium_mg']/c.nutrition['potassium_mg']==pytest.approx(1.6126126)

def test_unit_normalization(prices,fruits):
    b=fruits['banana'];p=prices['banana']
    assert nutrient_per_cny(b,p,'钾')==pytest.approx(387.8333333333333)
    assert nutrient_per_cny(fruits['cherry'],prices['cherry'],'钾')==pytest.approx(33.3)

def test_price_double_halves(fruits,prices):
    from dataclasses import replace
    f=fruits['banana'];p=prices['banana']
    assert nutrient_per_cny(f,replace(p,price_per_kg=2*p.price_per_kg),'potassium_mg')==pytest.approx(nutrient_per_cny(f,p,'potassium_mg')/2)

def test_price_jin_conversion(tmp_path,fruits):
    src=read_json(ROOT/'data/prices.SIMULATION.json');src['offers']=[{'fruit_id':'banana','amount_cny':3,'measure':'jin','kind':'simulation','location':'模拟'}]
    f=tmp_path/'p.json';f.write_text(json.dumps(src),encoding='utf8')
    assert load_prices(f,fruits,allow_simulation=True)['banana'].price_per_kg==6

def test_pack_conversion(tmp_path,fruits):
    src={'offers':[{'fruit_id':'banana','amount_cny':5,'measure':'pack','package_kg':0.5,'kind':'simulation','location':'模拟'}]}
    f=tmp_path/'p.json';f.write_text(json.dumps(src),encoding='utf8')
    assert load_prices(f,fruits,allow_simulation=True)['banana'].price_per_kg==10

def test_simulated_denied_by_default(fruits):
    with pytest.raises(ValueError,match='模拟'):
        load_prices(ROOT/'data/prices.SIMULATION.json',fruits)

def test_stale_prices_denied(tmp_path,fruits):
    r={'offers':[{'fruit_id':'banana','amount_cny':6,'measure':'kg','location':'北京','kind':'retail','observed_on':'2024-01-01','source_url':'https://example.com/abc'}]}
    x=tmp_path/'p.json';x.write_text(json.dumps(r),encoding='utf8')
    with pytest.raises(ValueError,match='过期'):load_prices(x,fruits,as_of=dt.date(2026,10,16))
    assert load_prices(x,fruits,as_of=dt.date(2026,10,16),allow_stale=True)['banana'].price_per_kg==6

def test_region_incomparability(tmp_path,fruits):
    r={'offers':[{'fruit_id':i,'amount_cny':6,'measure':'kg','location':loc,'kind':'simulation'} for i,loc in [('banana','深圳'),('apple','广州')]]}
    x=tmp_path/'p.json';x.write_text(json.dumps(r),encoding='utf8')
    with pytest.raises(ValueError,match='地区'):load_prices(x,fruits,allow_simulation=True)

def test_unknown_not_zero(fruits,prices):
    from dataclasses import replace
    b=fruits['banana'];bb=replace(b,nutrition={**b.nutrition,'vitamin_c_mg':None})
    assert nutrient_per_cny(bb,prices['banana'],'vitamin_c_mg') is None
    from fruit_optimizer.core import ranking
    rank_result=ranking({'banana':bb},prices,'vitamin_c_mg')
    assert not rank_result['ranked']
    assert '缺失' in rank_result['excluded'][0]['reason']

def test_rank_complete(fruits,prices):
    from fruit_optimizer.core import ranking
    r=ranking(fruits,prices,'potassium_mg')
    assert len(r['ranked'])==8 and r['candidate_count']==8
    assert r['ranked'][0]['amount_per_cny']>=r['ranked'][-1]['amount_per_cny']

def test_compare(fruits,prices):
    r=compare(fruits,prices,'香蕉','樱桃',['钾'])
    assert len(r['nutrient_ranks']['potassium_mg'])==2

def test_substitutes(fruits,prices):
    r=substitutes(fruits,prices,'樱桃',['钾'])
    assert any(x['fruit_id']=='banana' for x in r['results']['potassium_mg']['better'])

def test_invalid_edible_fraction(tmp_path,fruits):
    r=read_json(ROOT/'data/fruits.usda-sr-legacy.snapshot.json');r[0]['edible_fraction']=1.2
    f=tmp_path/'f.json';f.write_text(json.dumps(r),encoding='utf8')
    with pytest.raises(ValueError,match='0到1'):load_catalog(f)

def test_negative_nutrition_rejected(tmp_path):
    r=read_json(ROOT/'data/fruits.usda-sr-legacy.snapshot.json');r[0]['nutrition_per_100g_edible']['potassium_mg']=-1
    f=tmp_path/'f.json';f.write_text(json.dumps(r),encoding='utf8')
    with pytest.raises(ValueError):load_catalog(f)

def test_duplicate_id_rejected(tmp_path):
    r=read_json(ROOT/'data/fruits.usda-sr-legacy.snapshot.json');r.append(r[0])
    f=tmp_path/'f.json';f.write_text(json.dumps(r),encoding='utf8')
    with pytest.raises(ValueError):load_catalog(f)

def test_fdc_parser_preserve_null():
    d={'fdcId':12,'foodNutrients':[{'nutrient':{'id':1092,'unitName':'mg'},'amount':300},{'nutrient':{'id':1162,'unitName':'mg'},'amount':15.5}]}
    x=nutrition_from_detail(d)
    assert x['potassium_mg']==300 and x['vitamin_c_mg']==15.5 and x['fiber_g'] is None

def test_fdc_duplicate_conflict():
    d={'foodNutrients':[{'nutrient':{'id':1092,'unitName':'mg'},'amount':300},{'nutrient':{'id':1092,'unitName':'mg'},'amount':400}]}
    with pytest.raises(ValueError,match='矛盾'):nutrition_from_detail(d)

def test_fdc_import_trace():
    d={'fdcId':123,'dataType':'SR Legacy','description':'Test fruit, raw','foodNutrients':[{'nutrient':{'id':1092,'unitName':'mg'},'amount':100}]}
    r=import_fdc_record(d,'new','新水果',[],.7)
    assert r['source']['record_id']=='123' and r['nutrition_per_100g_edible']['vitamin_c_mg'] is None

class FakeSession:
    def __init__(self,data):self.data=data
    def get(self,*args,**kwargs):return SimpleNamespace(raise_for_status=lambda:None,json=lambda:self.data)

def test_fdc_fetch_mock():
    d={'fdcId':123,'dataType':'Foundation'}
    assert fetch_fdc(123,'TEST_KEY',FakeSession(d))==d
    with pytest.raises(ValueError):fetch_fdc(123,'TEST_KEY',FakeSession({'fdcId':456,'dataType':'Foundation'}))
    with pytest.raises(ValueError):fetch_fdc(123,'TEST_KEY',FakeSession({'fdcId':123,'dataType':'Branded'}))
