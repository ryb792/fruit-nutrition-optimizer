"""Optional USDA FoodData Central live import. API access requires external network and key.
See https://fdc.nal.usda.gov/api-guide/ .
"""
from __future__ import annotations
import os
from typing import Any
import requests
from .core import UNITS, finite_nonnegative

# IDs used by FDC. Records without these fields are reported as unknown, never zero.
FDC_NUTRIENT_IDS = {
   1008:'energy_kcal',1079:'fiber_g',1092:'potassium_mg',1162:'vitamin_c_mg',
   1175:'vitamin_b6_mg',1090:'magnesium_mg',2000:'sugar_g',1177:'folate_ug',1087:'calcium_mg'
}
FDC_NUTRIENT_NUMBERS = {
 '208':'energy_kcal','291':'fiber_g','306':'potassium_mg','401':'vitamin_c_mg',
 '415':'vitamin_b6_mg','304':'magnesium_mg','269':'sugar_g','417':'folate_ug','301':'calcium_mg'
}

def nutrition_from_detail(detail:dict[str,Any])->dict[str,float|None]:
    out={k:None for k in UNITS}
    source_ids={}
    for entry in detail.get('foodNutrients',[]):
        n=entry.get('nutrient') or {}
        # Foundation vs SR Legacy may use id and number; do not confuse foodNutrient id
        key=FDC_NUTRIENT_IDS.get(n.get('id')) or FDC_NUTRIENT_NUMBERS.get(str(n.get('number')))
        if not key:continue
        x=entry.get('amount')
        if x is None:continue
        unit=str(n.get('unitName','')).lower().replace('μ','u').replace('µ','u')
        expect=UNITS[key].lower().replace('µ','u')
        if unit not in (expect,):
            continue  # mismatch cannot be assumed equal; leave unknown
        value=finite_nonnegative(x,key)
        prev=source_ids.get(key)
        if prev is not None:
            # Duplicate nutrient by id with conflicting value is ambiguous.
            if abs(out[key]-value)>1e-7:raise ValueError(f'FDC重复矛盾营养值：{key}')
            continue
        out[key]=value
        source_ids[key]=n.get('id')
    return out

def fetch_fdc(fdc_id:int,api_key:str|None=None,session=None)->dict:
    if not isinstance(fdc_id,int) or fdc_id<=0: raise ValueError('fdc_id必须为正整数')
    key=api_key or os.getenv('FDC_API_KEY')
    if not key:raise ValueError('请设置 FDC_API_KEY 或传入 --api-key；不能凭空获取 USDA 数据')
    sess=session or requests.Session()
    r=sess.get(f'https://api.nal.usda.gov/fdc/v1/food/{fdc_id}',
           params={'api_key':key},timeout=20)
    r.raise_for_status()
    data=r.json()
    if int(data.get('fdcId',-1))!=fdc_id:raise ValueError('API响应 FDC ID 不匹配')
    if data.get('dataType') not in ('Foundation','SR Legacy'):
        raise ValueError('只允许Foundation或SR Legacy食品，拒绝品牌标签和加工不明记录')
    return data

def import_fdc_record(detail:dict,id:str,name:str,aliases:list[str],edible_fraction:float,
                       shelf_days:int=5)->dict:
    from .core import fraction
    fraction(edible_fraction,'edible_fraction',positive=True)
    nutrients=nutrition_from_detail(detail)
    if all(v is None for v in nutrients.values()):raise ValueError('未识别任何可核对营养素，不导入')
    fid=detail['fdcId'];dtype=detail['dataType']
    return {'id':id,'name':name,'aliases':aliases,
        'nutrition_per_100g_edible':nutrients,'edible_fraction':edible_fraction,
        'extra_waste_fraction':0.0,'shelf_days':shelf_days,
        'source':{'dataset':f'USDA FoodData Central {dtype}','data_type':dtype,
         'record_id':str(fid),'url':f'https://fdc.nal.usda.gov/food-details/{fid}/nutrients',
         'description':detail.get('description'), 'publication_date':detail.get('publicationDate'),
         'retrieval_note':'API返回原始记录; 需人工核对品种/可食部分/生熟状态'},
        'yield_source':{'type':'user_assumption','note':'用户输入可食率，非USDA营养API确认'},
        'shelf_source':{'type':'planning_assumption','note':'默认保存期为情景参数'}}
