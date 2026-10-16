"""Validated nutrition data and price normalization, V1.0 core."""
from __future__ import annotations
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UNITS = {'potassium_mg':'mg','vitamin_c_mg':'mg','vitamin_b6_mg':'mg',
         'fiber_g':'g','magnesium_mg':'mg','energy_kcal':'kcal',
         'sugar_g':'g','folate_ug':'µg','calcium_mg':'mg'}
ALIASES = {'钾':'potassium_mg','维生素c':'vitamin_c_mg','vc':'vitamin_c_mg',
           '维生素b6':'vitamin_b6_mg','b6':'vitamin_b6_mg','膳食纤维':'fiber_g',
           '纤维':'fiber_g','镁':'magnesium_mg','能量':'energy_kcal',
           '热量':'energy_kcal','糖':'sugar_g','叶酸':'folate_ug','钙':'calcium_mg'}

def nutrient_key(key:str)->str:
    k=ALIASES.get(key.casefold().strip(),key.strip())
    if k not in UNITS: raise ValueError(f'不支持的营养素: {key}；支持 {list(UNITS)}')
    return k

def finite_nonnegative(value:Any, name:str, *, allow_zero=True)->float:
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(f'{name} 必须是数字')
    n=float(value)
    if not math.isfinite(n) or n<0 or (not allow_zero and n==0):
        raise ValueError(f'{name} 不可为负数、无穷、NaN 或不允许的零')
    return n

def fraction(value:Any,name:str,positive=False)->float:
    x=finite_nonnegative(value,name,allow_zero=not positive)
    if x>1: raise ValueError(f'{name} 必须在0到1之间')
    return x

def read_json(path:str|Path)->Any:
    with open(path,encoding='utf-8') as f: return json.load(f)

def write_json(path:str|Path, data:Any)->None:
    with open(path,'w',encoding='utf-8') as f: json.dump(data,f,indent=2,ensure_ascii=False,allow_nan=False)

@dataclass(frozen=True)
class Fruit:
    id:str
    name:str
    aliases:tuple[str,...]
    nutrition:dict[str,float|None]
    edible_fraction:float
    waste_fraction:float
    shelf_days:int
    source:dict
    yield_source:dict

    @property
    def yield_fraction(self)->float:
        return self.edible_fraction*(1-self.waste_fraction)

    def amount(self,key:str,edible_g:float)->float|None:
        key=nutrient_key(key)
        n=self.nutrition.get(key)
        return None if n is None else n*edible_g/100.0


def load_catalog(path:str|Path)->dict[str,Fruit]:
    rows=read_json(path)
    if not isinstance(rows,list) or not rows: raise ValueError('水果目录须为非空数组')
    fruits={}; names={}
    for r in rows:
        fid=str(r['id']).strip()
        if not fid or fid in fruits: raise ValueError('水果ID重复或为空')
        src=r.get('source',{})
        if not src.get('url') or not src.get('record_id') or not src.get('dataset'):
            raise ValueError(f'{fid}: 缺少具体来源URL/条目ID/数据集')
        ysrc=r.get('yield_source',{})
        if not ysrc.get('type') or not ysrc.get('note'):
            raise ValueError(f'{fid}: 可食率需要标明依据或假设')
        nutrients=r.get('nutrition_per_100g_edible')
        if not isinstance(nutrients,dict):raise ValueError(f'{fid} 缺少营养数据')
        cleaned={}
        for key,val in nutrients.items():
            nk=nutrient_key(key)
            cleaned[nk]=None if val is None else finite_nonnegative(val,f'{fid}.{nk}')
        e=fraction(r['edible_fraction'],f'{fid}.可食率',positive=True)
        w=fraction(r.get('extra_waste_fraction',0),f'{fid}.额外损耗')
        if w>=1:raise ValueError(f'{fid}: 损耗率达到100%，无有效可食部，不可计算营养性价比')
        days=r.get('shelf_days',1)
        if not isinstance(days,int) or days<1: raise ValueError('shelf_days 必须为正整数')
        f=Fruit(fid,str(r['name']),tuple(r.get('aliases',[])),cleaned,e,w,days,src,ysrc)
        for a in (f.id,f.name,*f.aliases):
            a=a.casefold().strip()
            if a in names and names[a]!=fid:raise ValueError(f'水果名称或别名冲突: {a}')
            names[a]=fid
        fruits[fid]=f
    return fruits

def resolve(fruits:dict[str,Fruit],name:str)->Fruit:
    q=name.strip().casefold()
    for f in fruits.values():
        if q in [x.casefold() for x in (f.id,f.name,*f.aliases)]:return f
    raise ValueError(f'未在数据集中找到水果「{name}」。需确认品种或通过官方数据导入新条目。')

@dataclass(frozen=True)
class Price:
    fruit_id:str
    amount_cny:float
    measure:str
    package_kg:float|None
    price_per_kg:float
    source_url:str|None
    location:str
    observed_on:dt.date|None
    kind:str
    source_note:str
    shipping_cny:float  # shipping of the whole basket must not be counted as per-fruit marginal cost
    @property
    def is_simulated(self)->bool:return self.kind=='simulation'
    def package_cost(self)->float:
        if self.package_kg is None:raise ValueError('散称水果无固定包装成本')
        return self.price_per_kg*self.package_kg


def load_prices(path:str|Path,fruits:dict[str,Fruit],*,as_of:dt.date|None=None,
                max_age_days:int=7,allow_stale:bool=False,allow_simulation:bool=False,
                allow_mixed_regions:bool=False)->dict[str,Price]:
    data=read_json(path)
    if not isinstance(data,dict) or not isinstance(data.get('offers'),list):
        raise ValueError('报价需为 {"offers":[...]}')
    as_of=as_of or dt.date.today()
    prices={}
    locations=set()
    for raw in data['offers']:
        fid=str(raw['fruit_id'])
        if fid not in fruits: raise ValueError(f'价格水果无对应营养记录: {fid}')
        if fid in prices:raise ValueError(f'{fid} 多条报价未指定选择策略，拒绝隐式选价')
        kind=str(raw.get('kind','')).strip()
        if kind not in ('retail','user_receipt','simulation'):
            raise ValueError(f'{fid} 价格类型须为 retail/user_receipt/simulation')
        if kind=='simulation' and not allow_simulation:
            raise ValueError('模拟价格不可作为实际价格排名；请加 --allow-simulation')
        url=raw.get('source_url'); note=str(raw.get('source_note','')).strip()
        if kind!='simulation' and not (url or note):
            raise ValueError(f'{fid}: 真实价格至少提供来源网址或收据说明')
        dateval=raw.get('observed_on')
        try: day=dt.date.fromisoformat(dateval) if dateval else None
        except (TypeError,ValueError):raise ValueError(f'{fid}: observed_on格式必须YYYY-MM-DD')
        if kind!='simulation' and day is None:raise ValueError(f'{fid}: 真实报价必须提供采集日期')
        if day and day>as_of:raise ValueError(f'{fid}: 报价日期晚于分析日期')
        if day and (as_of-day).days>max_age_days and not allow_stale:
            raise ValueError(f'{fid}: 报价过期，距分析日{(as_of-day).days}天；可显式 --allow-stale')
        location=str(raw.get('location','')).strip()
        if not location:raise ValueError(f'{fid}: 价格缺少地区')
        locations.add(location)
        amount=finite_nonnegative(raw['amount_cny'],f'{fid}.价格',allow_zero=False)
        measure=raw.get('measure')
        pack=raw.get('package_kg')
        if pack is not None:pack=finite_nonnegative(pack,f'{fid}.包装公斤',allow_zero=False)
        if measure=='kg':perkg=amount
        elif measure=='jin':perkg=amount*2
        elif measure=='pack':
            if pack is None:raise ValueError(f'{fid}: pack报价必须给package_kg')
            perkg=amount/pack
        else:raise ValueError('measure仅支持kg、jin、pack')
        ship=finite_nonnegative(raw.get('shipping_cny',0),f'{fid}.运费')
        if ship:raise ValueError('暂不支持含运费的组合报价：运费不能重复计入每水果；请使用到手单价')
        prices[fid]=Price(fid,amount,measure,pack,perkg,url,location,day,kind,note,ship)
    if len(locations)>1 and not allow_mixed_regions:
        raise ValueError('不同地区报价不能直接比较：请统一地区或显式允许混合地区（仅模拟）')
    return prices

def unit_cost_per_edible_g(fruit:Fruit,price:Price)->float:
    return price.price_per_kg/(1000*fruit.yield_fraction)

def nutrient_per_cny(fruit:Fruit,price:Price,nutrient:str)->float|None:
    n=fruit.nutrition.get(nutrient_key(nutrient))
    return None if n is None else n*10*fruit.yield_fraction/price.price_per_kg

def profile(fruit:Fruit,price:Price|None=None)->dict:
    result={'fruit':fruit.name,'id':fruit.id,'basis':'每100g可食部分','source':fruit.source,
      'edible_fraction':fruit.edible_fraction,'extra_waste_fraction':fruit.waste_fraction,
      'yield_source':fruit.yield_source,'nutrition':fruit.nutrition,
      'units':{k:UNITS[k] for k in fruit.nutrition}}
    if price:
        result['pricing']={'price_cny_per_kg':price.price_per_kg,'kind':price.kind,
          'observed_on':price.observed_on.isoformat() if price.observed_on else None,
          'location':price.location,'source_url':price.source_url,'source_note':price.source_note,
          'nutrient_per_cny':{k:nutrient_per_cny(fruit,price,k) for k in fruit.nutrition}}
    return result

def ranking(fruits:dict[str,Fruit],prices:dict[str,Price],nutrient:str)->dict:
    key=nutrient_key(nutrient)
    entries=[]; excluded=[]
    for f in fruits.values():
        if f.id not in prices:
            excluded.append({'fruit_id':f.id,'reason':'缺少有效价格'});continue
        value=nutrient_per_cny(f,prices[f.id],key)
        if value is None:
            excluded.append({'fruit_id':f.id,'reason':'营养成分缺失（不是0）'});continue
        entries.append({'fruit_id':f.id,'fruit':f.name,'amount_per_cny':value,
           'unit':UNITS[key]+'/元','price_cny_per_kg':prices[f.id].price_per_kg,
           'price_kind':prices[f.id].kind,'nutrition_source':f.source,
           'price_source':{'url':prices[f.id].source_url,'note':prices[f.id].source_note,
               'date':prices[f.id].observed_on.isoformat() if prices[f.id].observed_on else None}})
    entries.sort(key=lambda x:(-x['amount_per_cny'],x['fruit_id']))
    return {'nutrient':key,'ranked':entries,'excluded':excluded,'candidate_count':len(fruits),
       'ranked_count':len(entries),'scope':'仅在已覆盖且有有效价格、营养数据的候选中排名',
       'assumptions':'可食率及额外损耗可能是模型假设；逐项查看水果档案'}

def compare(fruits,prices,a,b,nutrients):
    fa,fb=resolve(fruits,a),resolve(fruits,b)
    keys=[nutrient_key(s) for s in nutrients]
    return {'a':profile(fa,prices.get(fa.id)),'b':profile(fb,prices.get(fb.id)),
            'nutrient_ranks':{k:[x for x in ranking({fa.id:fa,fb.id:fb},prices,k)['ranked']] for k in keys}}

def substitutes(fruits,prices,fruit_name:str,nutrients:list[str])->dict:
    selected=resolve(fruits,fruit_name)
    results={}
    for key0 in nutrients:
        key=nutrient_key(key0)
        rank=ranking(fruits,prices,key)
        mine=next((row for row in rank['ranked'] if row['fruit_id']==selected.id),None)
        results[key]={'baseline':mine,'better':[x for x in rank['ranked'] if mine and x['amount_per_cny']>mine['amount_per_cny']*(1+1e-9)],'top':rank['ranked'][:5],
             'baseline_missing_price_or_nutrient':mine is None}
    return {'selected_fruit':selected.name,'results':results}

def apply_yield_overrides(fruits:dict[str,Fruit],path:str|Path)->dict[str,Fruit]:
    """Override yield, non-peel losses, shelf assumption with explicit user evidence."""
    from dataclasses import replace
    data=read_json(path)
    if not isinstance(data,dict) or not isinstance(data.get('overrides'),dict):
        raise ValueError('可食率覆盖文件应包含overrides对象')
    result=dict(fruits)
    for fid,r in data['overrides'].items():
        if fid not in result:raise ValueError(f'未知水果ID: {fid}')
        if not isinstance(r,dict) or not str(r.get('source_note','')).strip():
            raise ValueError(f'{fid} 修改可食率或保质期必须有来源说明')
        f=fruits[fid]
        allowed={'edible_fraction','extra_waste_fraction','shelf_days','source_note'}
        if set(r)-allowed:raise ValueError(f'{fid}: 覆盖文件包含未知字段')
        yf=fraction(r.get('edible_fraction',f.edible_fraction),fid+'.edible_fraction',positive=True)
        wf=fraction(r.get('extra_waste_fraction',f.waste_fraction),fid+'.extra_waste_fraction')
        if wf>=1:raise ValueError(f'{fid}: 额外损耗100%导致无法取得营养')
        shelf=r.get('shelf_days',f.shelf_days)
        if not isinstance(shelf,int) or shelf<1:raise ValueError(f'{fid} shelf_days必须为正整数')
        result[fid]=replace(f,edible_fraction=yf,waste_fraction=wf,shelf_days=shelf,
           yield_source={'type':'user_override','note':str(r['source_note'])})
    return result
