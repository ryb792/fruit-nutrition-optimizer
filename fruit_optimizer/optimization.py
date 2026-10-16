"""V1.1: Pareto, price break-even, and mathematically verified fruit purchase plans.

All nutrition constraints apply only to the fruit portion of a diet. In packaged
mode, integer purchases are allocated into consumption days within a shelf-life
window. No invented 'average vitamin score'.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from .core import (Fruit,Price,UNITS,nutrient_key,finite_nonnegative,read_json,
                   nutrient_per_cny,resolve)


def pareto_fruits(fruits:dict[str,Fruit],prices:dict[str,Price], nutrients:list[str])->dict:
    keys=list(dict.fromkeys(nutrient_key(k) for k in nutrients))
    if not keys:raise ValueError('至少指定一项营养素')
    entries=[]; excluded=[]
    for fid,f in fruits.items():
        if fid not in prices:
            excluded.append({'fruit':f.name,'reason':'没有可核验的报价'});continue
        vals=[nutrient_per_cny(f,prices[fid],k) for k in keys]
        if any(v is None for v in vals):
            excluded.append({'fruit':f.name,'reason':'至少一项指定营养数据缺失（没有视为零）'});continue
        entries.append({'fruit_id':fid,'fruit':f.name,'nutrition_per_cny':dict(zip(keys,vals))})
    frontier=[]; dominated=[]
    for a in entries:
        dominators=[]
        for b in entries:
            if b['fruit_id']==a['fruit_id']:continue
            av=np.asarray(list(a['nutrition_per_cny'].values()))
            bv=np.asarray(list(b['nutrition_per_cny'].values()))
            tol=1e-9*np.maximum(1,np.maximum(np.abs(av),np.abs(bv)))
            if np.all(bv>=av-tol) and np.any(bv>av+tol):
                dominators.append(b['fruit_id'])
        (dominated if dominators else frontier).append({**a,'dominated_by':dominators})
    return {'nutrients':keys,'frontier':frontier,'dominated':dominated,'excluded':excluded,
            'candidate_count':len(fruits),
            'description':'只比较指定营养素每元提供量的帕累托支配；不等于全面健康收益排序'}


def break_even_price(fruits,prices,baseline:str,challenger:str,nutrient:str)->dict:
    a=resolve(fruits,baseline);b=resolve(fruits,challenger)
    key=nutrient_key(nutrient)
    if a.id not in prices:raise ValueError('基准水果缺少价格')
    na=a.nutrition.get(key);nb=b.nutrition.get(key)
    if na is None or nb is None or na<=0:raise ValueError('缺少用于价格阈值分析的有效营养素')
    max_price=prices[a.id].price_per_kg*nb*b.yield_fraction/(na*a.yield_fraction)
    actual=prices.get(b.id)
    return {'baseline':a.name,'challenger':b.name,'nutrient':key,
       'break_even_challenger_price_cny_per_kg':max_price,
       'challenger_is_more_cost_effective_if':'挑战者价格低于阈值（相等时营养/元相同）',
       'challenger_current_price_cny_per_kg':actual.price_per_kg if actual else None,
       'baseline_price_source':prices[a.id].source_url or prices[a.id].source_note,
       'formula':'P_b_threshold=P_a*(N_b*effective_yield_b)/(N_a*effective_yield_a)'}


def parse_targets(path:str|None)->tuple[dict[str,float],dict]:
    if not path:return {},{'target_scope':'none','source':'没有指定水果营养目标'}
    j=read_json(path)
    if j.get('target_scope')!='fruit_contribution_only':
        raise ValueError('营养约束只接受 fruit_contribution_only；不可误用人体整日参考摄入量')
    if not j.get('source'):raise ValueError('目标值必须提供来源或明确标注为用户假设')
    if not isinstance(j.get('targets_per_day'),dict):raise ValueError('缺少targets_per_day')
    out={}
    for k,v in j['targets_per_day'].items():
        key=nutrient_key(k);out[key]=finite_nonnegative(v,k,allow_zero=False)
    if not out:raise ValueError('营养目标不可为空')
    return out,{'target_scope':j['target_scope'],'source':j['source'],
                'disclaimer':j.get('disclaimer','')}


def plan(fruits:dict[str,Fruit],prices:dict[str,Price],*,days:int=7,
         min_daily_g:float=200,max_daily_g:float=350,
         nutrient_targets:dict[str,float]|None=None,target_meta:dict|None=None,
         budget_cny:float|None=None,objective:str='mincost',
         min_fruit_types:int=1,min_total_each_type_g:float=50,
         max_daily_energy_kcal:float|None=None, trip_fee_cny:float=0.0)->dict:
    if not isinstance(days,int) or days<1 or days>31:raise ValueError('days须在1-31之间')
    if objective not in ('mincost','maximin'):raise ValueError('objective须为mincost/maximin')
    low=finite_nonnegative(min_daily_g,'每日下限',allow_zero=False)
    high=finite_nonnegative(max_daily_g,'每日上限',allow_zero=False)
    if low>high:raise ValueError('每日最小食用量不能大于最大值')
    if high>1000:raise ValueError('每日水果上限大于1000g，请重新核实输入')
    if not isinstance(min_fruit_types,int) or min_fruit_types<1:
        raise ValueError('min_fruit_types须为正整数')
    min_each=finite_nonnegative(min_total_each_type_g,'每个品种最少总食用量',allow_zero=False)
    if max_daily_energy_kcal is not None:
        max_daily_energy_kcal=finite_nonnegative(max_daily_energy_kcal,'能量上限',allow_zero=False)
    if budget_cny is not None:budget_cny=finite_nonnegative(budget_cny,'预算',allow_zero=False)
    trip_fee_cny=finite_nonnegative(trip_fee_cny,'每次采购固定成本')
    targets={nutrient_key(k):finite_nonnegative(v,k,allow_zero=False) for k,v in (nutrient_targets or {}).items()}
    if objective=='maximin' and (budget_cny is None or not targets):
        raise ValueError('maximin模式必须有预算和明确的水果部分营养目标')
    required=list(targets)
    if max_daily_energy_kcal is not None:required.append('energy_kcal')
    selected=[];excluded=[]
    for f in fruits.values():
        if f.id not in prices:
            excluded.append({'fruit':f.name,'reason':'缺少报价'});continue
        missing=[k for k in required if f.nutrition.get(k) is None]
        if missing:
            excluded.append({'fruit':f.name,'reason':'缺少所需营养数据 '+','.join(missing)});continue
        selected.append(f)
    if len(selected)<min_fruit_types:raise ValueError('满足数据完整性与有报价条件的候选水果数量不足')
    if min_each*min_fruit_types>high*days+1e-9:raise ValueError('最低品种量超过全部可食用总量上限')
    # Variables indexed by tuple:
    # q[fruit, purchase_day, consumption_day] = grams actually eaten;
    # for loose fruit purchase_day == consumption_day, enabling just-in-time purchase;
    # z[fruit,purchase_day] = number of whole packs (integer) for packaged fruit;
    # b[fruit] = binary fruit type used, with a nontrivial minimum quantity.
    index={}; costs=[]; integ=[]; ubs=[]
    def var(k,cost=0.0,integer=False,upper=np.inf):
        index[k]=len(costs);costs.append(float(cost));integ.append(1 if integer else 0);ubs.append(float(upper))
    for f in selected:
        price=prices[f.id]
        for pd in range(days):
            if price.package_kg is not None:
                # ceil worst-case required pack counts, no enormous integer domain
                maxpacks=int(np.ceil(high*days/(1000*price.package_kg*f.yield_fraction)))+1
                var(('z',f.id,pd),price.package_cost(),integer=True,upper=maxpacks)
                for cd in range(pd,min(days,pd+f.shelf_days)):
                    var(('q',f.id,pd,cd),upper=high)
            else:
                var(('q',f.id,pd,pd),cost=price.price_per_kg/(1000*f.yield_fraction),upper=high)
        var(('b',f.id),integer=True,upper=1)
    if trip_fee_cny>0:
        for day in range(days):var(('visit',day),cost=trip_fee_cny,integer=True,upper=1)
    if objective=='maximin':var(('t',),upper=1)
    n=len(costs);rows=[];los=[];his=[]
    def constraint(terms:dict[tuple,float],lo=-np.inf,hi=np.inf):
        row=np.zeros(n)
        for key,val in terms.items(): row[index[key]]+=val
        rows.append(row);los.append(lo);his.append(hi)
    if trip_fee_cny>0:
        for k in tuple(index):
            if k[0]=='z':
                f=fruits[k[1]];p=prices[f.id]
                maxpacks=int(np.ceil(high*days/(1000*p.package_kg*f.yield_fraction)))+1
                constraint({k:1,('visit',k[2]):-maxpacks},hi=0)
            elif k[0]=='q' and prices[k[1]].package_kg is None:
                constraint({k:1,('visit',k[2]):-high},hi=0)
    # Day bounds on actual edible portion. No double deduction of peel.
    for d in range(days):
        constraint({k:1 for k in index if k[0]=='q' and k[3]==d},low,high)
        if max_daily_energy_kcal is not None:
            constraint({k:fruits[k[1]].nutrition['energy_kcal']/100 for k in index if k[0]=='q' and k[3]==d},
                       hi=max_daily_energy_kcal)
    # Each purchased package can yield at most the available edible amount;
    # stock from purchase on day pd cannot be eaten after a fruit's shelf life.
    for f in selected:
        p=prices[f.id]
        if p.package_kg is not None:
            for pd in range(days):
                cap=1000*p.package_kg*f.yield_fraction
                terms={k:1 for k in index if k[0]=='q' and k[1]==f.id and k[2]==pd}
                terms[('z',f.id,pd)]=-cap
                constraint(terms,hi=0)
        qterms={k:1 for k in index if k[0]=='q' and k[1]==f.id}
        # Binary activation with a minimum effective variety contribution.
        constraint({**qterms,('b',f.id):-min_each},lo=0)
        constraint({**qterms,('b',f.id):-high*days},hi=0)
    constraint({('b',f.id):1 for f in selected},lo=min_fruit_types)
    # Nutrient targets are for FRUIT contribution only; maximin varies common completion fraction.
    for key, target in targets.items():
        terms={k:fruits[k[1]].nutrition[key]/100 for k in index if k[0]=='q'}
        if objective=='maximin':terms[('t',)]=-target*days
        constraint(terms,lo=0 if objective=='maximin' else target*days)
    if budget_cny is not None:
        constraint({k:v for k,v in zip(index,costs) if v>0},hi=budget_cny)
    def solve(objective_vector,extra_constraint=None):
        allrows=rows if extra_constraint is None else rows+[extra_constraint[0]]
        all_los=los if extra_constraint is None else los+[extra_constraint[1]]
        all_his=his if extra_constraint is None else his+[extra_constraint[2]]
        res=milp(np.asarray(objective_vector,dtype=float),integrality=np.asarray(integ),
                 bounds=Bounds(np.zeros(n),np.asarray(ubs)),
                 constraints=LinearConstraint(np.asarray(allrows),np.asarray(all_los),np.asarray(all_his)),
                 options={'time_limit':35,'mip_rel_gap':1e-8})
        if res.status==2:raise ValueError('无可行解：预算、每日食用量、营养目标、采购规格或品种约束相互冲突')
        if res.status!=0 or res.x is None:raise RuntimeError('优化求解器未证明最优：status='+str(res.status)+'; '+str(res.message))
        return res
    obj=np.asarray(costs)
    if objective=='maximin':
        v=np.zeros(n);v[index[('t',)]]=-1
        first=solve(v)
        t_opt=float(first.x[index[('t',)]])
        row=np.zeros(n);row[index[('t',)]]=1
        # Avoid microscopic solver rounding causing artificial infeasibility.
        second=solve(obj,(row,max(0,t_opt-1e-7),np.inf))
        result=second
    else:
        result=solve(obj)
        t_opt=None
    xx=result.x
    allocations=defaultdict(float);purchases=[];consumption=defaultdict(lambda:defaultdict(float))
    for k,j in index.items():
        val=float(xx[j])
        if k[0]=='q' and val>1e-6:
            _,fid,pd,cd=k
            allocations[(fid,pd)]+=val
            consumption[cd][fid]+=val
        elif k[0]=='z' and val>1e-5:
            _,fid,pd=k
            count=int(round(val))
            p=prices[fid];f=fruits[fid]
            used=allocations[(fid,pd)] # populated after complete traversal below; overwritten later
            purchases.append({'day':pd+1,'fruit_id':fid,'fruit':f.name,
                  'packages':count,'package_kg':p.package_kg,
                  'purchased_kg':p.package_kg*count,
                  'cost_cny':p.package_cost()*count,
                  'edible_capacity_g':p.package_kg*count*1000*f.yield_fraction})
    for d in range(days):
        for fid,val in consumption[d].items():
            if prices[fid].package_kg is None:
                f=fruits[fid];p=prices[fid]
                purchases.append({'day':d+1,'fruit_id':fid,'fruit':f.name,
                 'packages':None,'purchased_kg':val/(1000*f.yield_fraction),
                 'cost_cny':val*p.price_per_kg/(1000*f.yield_fraction),
                 'edible_capacity_g':val,'model':'按需零售称重，同日食用'})
    purchases.sort(key=lambda x:(x['day'],x['fruit_id']))
    used_packed=defaultdict(float)
    for k,j in index.items():
        if k[0]=='q' and prices[k[1]].package_kg is not None:
            used_packed[(k[1],k[2])]+=max(0,float(xx[j]))
    for p in purchases:
        if p['packages'] is not None:
            used=used_packed[(p['fruit_id'],p['day']-1)]
            p['consumed_edible_g']=used
            p['unconsumed_edible_g']=max(0,p['edible_capacity_g']-used)
    day_schedules=[];total_nutrients=defaultdict(float)
    for d in range(days):
        eaten=consumption[d]
        tot=sum(eaten.values())
        daily_nutrient={}
        for key in UNITS:
            if all(fruits[fid].nutrition.get(key) is not None for fid in eaten):
                val=sum(fruits[fid].nutrition[key]*g/100 for fid,g in eaten.items())
                daily_nutrient[key]=val;total_nutrients[key]+=val
            else:
                daily_nutrient[key]=None
        day_schedules.append({'day':d+1,
            'edible_g':tot,'fruits':[{'fruit_id':fid,'fruit':fruits[fid].name,'edible_g':g} for fid,g in sorted(eaten.items())],
            'nutrition':daily_nutrient})
    shopping_days=[k[1]+1 for k,j in index.items() if k[0]=='visit' and xx[j]>0.5]
    extra_trip_cost=trip_fee_cny*len(shopping_days)
    actual_cost=sum(p['cost_cny'] for p in purchases)+extra_trip_cost
    # Defensively verify against numerical drift; a solver's flag isn't enough.
    if any(d['edible_g']<low-1e-4 or d['edible_g']>high+1e-4 for d in day_schedules):
        raise RuntimeError('验收失败：每日食用量超界')
    if budget_cny is not None and actual_cost>budget_cny+1e-4:
        raise RuntimeError('验收失败：预算超界')
    if abs(actual_cost-float(np.dot(obj,xx)))>1e-3:
        raise RuntimeError('验收失败：采购成本与求解器不一致')
    for k,v in targets.items():
        val=total_nutrients[k]
        expected=v*days*(t_opt-1e-6 if objective=='maximin' else 1)
        if val+1e-3<expected:raise RuntimeError('验收失败：营养目标不满足')
    usedtotals=defaultdict(float)
    for daily in consumption.values():
        for fid,g in daily.items():usedtotals[fid]+=g
    usedtypes={fid for fid,g in usedtotals.items() if g>=min_each-1e-4}
    if len(usedtypes)<min_fruit_types:raise RuntimeError('验收失败：水果种类不足')
    sources=[{'fruit_id':f.id,'fdc_id':f.source['record_id'],'nutrition_url':f.source['url'],
              'edible_yield_basis':f.yield_source,'price_kind':prices[f.id].kind,
              'price_date':prices[f.id].observed_on.isoformat() if prices[f.id].observed_on else None,
              'price_source_url':prices[f.id].source_url,'price_source_note':prices[f.id].source_note} for f in selected]
    coverage={k:{'total':total_nutrients[k], 'goal_total':v*days,
               'completion_fraction':total_nutrients[k]/(v*days)} for k,v in targets.items()}
    return {'status':'optimal','objective':objective,'period_days':days,
        'total_cost_cny':actual_cost,'shopping_days':shopping_days,'trip_fee_cny':trip_fee_cny,'total_trip_fees_cny':extra_trip_cost,'budget_cny':budget_cny,'available_budget_cny':None if budget_cny is None else budget_cny-actual_cost,
        'maximin_fraction':t_opt,'fruit_type_count':len(usedtypes),
        'total_edible_g':sum(x['edible_g'] for x in day_schedules),
        'purchases':purchases,'daily_plan':day_schedules,'nutrient_coverage':coverage,
        'target_meta':target_meta or {'target_scope':'none'},
        'excluded_candidates':excluded,'compared_candidates_count':len(selected),'sources':sources,
        'warnings':['营养优化仅针对水果，不保证全天饮食营养充足',
          '可食率及货架期为估算假设，实际可能不同',
          '包装未用尽部分标为unconsumed，不一律视为腐坏',
          '如设定trip_fee则按实际采购日计固定费用；其他隐性成本仍可能遗漏',
          '仅在已录入且完整的候选水果、价格与约束下证明最优',
          '这是多日采购/消费数学方案；实际储存条件可能改变货架期']}


def add_cli(sub):
    p=sub.add_parser('pareto',help='多营养素每元供给帕累托前沿')
    p.add_argument('nutrients',nargs='+')
    p=sub.add_parser('threshold',help='挑战者水果价格降到多少才与基准一样划算')
    p.add_argument('baseline');p.add_argument('challenger');p.add_argument('nutrient')
    p=sub.add_parser('optimize',help='七天/指定天数预算、营养、整数包装及储存约束优化')
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--daily-min',type=float,default=200)
    p.add_argument('--daily-max',type=float,default=350)
    p.add_argument('--budget',type=float)
    p.add_argument('--targets',help='只允许标记为 fruit_contribution_only 的营养目标 JSON')
    p.add_argument('--objective',choices=['mincost','maximin'],default='mincost')
    p.add_argument('--min-types',type=int,default=1)
    p.add_argument('--min-each-g',type=float,default=50)
    p.add_argument('--max-energy-kcal',type=float)
    p.add_argument('--trip-fee',type=float,default=0,help='每发生一天采购的固定费用，默认0')
    p=sub.add_parser('frontier',help='不同预算下 maximin 营养目标达成率的样本帕累托集')
    p.add_argument('--budgets',type=float,nargs='+',required=True)
    p.add_argument('--targets',required=True)
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--min-types',type=int,default=1)


def execute_v11(args,fruits,prices):
    if args.command=='pareto':return pareto_fruits(fruits,prices,args.nutrients)
    if args.command=='threshold':return break_even_price(fruits,prices,args.baseline,args.challenger,args.nutrient)
    if args.command=='optimize':
        targets,meta=parse_targets(args.targets)
        return plan(fruits,prices,days=args.days,min_daily_g=args.daily_min,max_daily_g=args.daily_max,
          nutrient_targets=targets,target_meta=meta,budget_cny=args.budget,objective=args.objective,
          min_fruit_types=args.min_types,min_total_each_type_g=args.min_each_g,
          max_daily_energy_kcal=args.max_energy_kcal,trip_fee_cny=args.trip_fee)
    if args.command=='frontier':
        targets,meta=parse_targets(args.targets)
        options=[]
        for budget in args.budgets:
            try:
                sol=plan(fruits,prices,days=args.days,nutrient_targets=targets,target_meta=meta,
                         budget_cny=budget,objective='maximin',min_fruit_types=args.min_types)
                options.append({'budget_cny':budget,'actual_cost_cny':sol['total_cost_cny'],
                 'maximin_fraction':sol['maximin_fraction'],'fruit_type_count':sol['fruit_type_count'],
                 'purchases':sol['purchases']})
            except ValueError as e:options.append({'budget_cny':budget,'status':'infeasible','reason':str(e)})
        nondominated=[]
        feasible=[x for x in options if x.get('status')!='infeasible']
        for x in feasible:
            dom=any(y is not x and
               y['actual_cost_cny']<=x['actual_cost_cny']+1e-7 and
               y['maximin_fraction']>=x['maximin_fraction']-1e-7 and
               (y['actual_cost_cny']<x['actual_cost_cny']-1e-7 or y['maximin_fraction']>x['maximin_fraction']+1e-7)
               for y in feasible)
            if not dom:nondominated.append(x)
        return {'samples':options,'sampled_nondominated':nondominated,
          'limitations':'仅是给定预算样本点中的非劣集，不是完整连续帕累托前沿；达成率上限为100%'}
    raise ValueError('未知子命令')
