"""Fruit nutrition optimizer command-line interface (Chinese-first)."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import hashlib
import sys
from pathlib import Path
from requests.exceptions import RequestException
from . import __version__
from .core import (load_catalog,load_prices,profile,resolve,compare,ranking,substitutes,
                   nutrient_key,read_json,apply_yield_overrides,price_context)
from .fdc import fetch_fdc,import_fdc_record
from .evidence import import_web_record,append_catalog,read_web_evidence

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CATALOG=ROOT/'data/fruits.usda-sr-legacy.snapshot.json'

def build_parser():
    p=argparse.ArgumentParser(prog='fruitopt',description=f'水果营养性价比 V{__version__}。只以可核验来源及约束计算。')
    p.add_argument('--catalog',default=str(DEFAULT_CATALOG),help='水果营养数据库 JSON')
    p.add_argument('--prices',help='报价 JSON; 不提供时只能返回营养资料')
    p.add_argument('--yields',help='用户自测可食率、损耗、保质期覆盖JSON')
    p.add_argument('--allow-simulation',action='store_true',help='允许明确标注的情景价格')
    p.add_argument('--allow-stale',action='store_true',help='显式允许过期参考价')
    p.add_argument('--allow-mixed-regions',action='store_true',help='仅模拟用：允许跨地区报价')
    p.add_argument('--as-of',help='分析日期YYYY-MM-DD; 默认今天')
    p.add_argument('--format',choices=['json','md'],default='json')
    p.add_argument('--output',help='写入文件，不指定则输出到标准输出')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('profile',help='查询水果成分及出处')
    a.add_argument('fruit')
    b=sub.add_parser('rank',help='指定营养素的每元排名')
    b.add_argument('nutrient')
    c=sub.add_parser('compare',help='两种水果对比')
    c.add_argument('fruit_a');c.add_argument('fruit_b')
    c.add_argument('--nutrients',nargs='+',default=['potassium_mg','vitamin_c_mg','vitamin_b6_mg','fiber_g'])
    d=sub.add_parser('substitutes',help='寻找某水果在营养素方面更经济的替代')
    d.add_argument('fruit');d.add_argument('--nutrients',nargs='+',default=['potassium_mg','vitamin_c_mg','vitamin_b6_mg','fiber_g'])
    v=sub.add_parser('validate',help='核验目录与价格数据')
    web=sub.add_parser('import-web',help='免密钥导入 Agent 已查证的官方网页/下载数据证据；CLI自身不搜索')
    web.add_argument('evidence',help='带来源、原始单位及食部口径的 JSON 证据文件')
    web.add_argument('--id',required=True);web.add_argument('--name',required=True)
    web.add_argument('--alias',action='append',default=[])
    web.add_argument('--edible-fraction',type=float,required=True)
    web.add_argument('--yield-note',required=True,help='可食率依据或明确的规划假设')
    web.add_argument('--shelf-days',type=int,default=5)
    web.add_argument('--out-catalog',required=True)
    fdc=sub.add_parser('import-fdc',help='开发者可选：使用密钥从USDA FDC API导入一个条目到新文件')
    fdc.add_argument('fdc_id',type=int);fdc.add_argument('--id',required=True)
    fdc.add_argument('--name',required=True);fdc.add_argument('--alias',action='append',default=[])
    fdc.add_argument('--edible-fraction',type=float,required=True)
    fdc.add_argument('--shelf-days',type=int,default=5)
    fdc.add_argument('--api-key',help='优先使用环境变量 FDC_API_KEY')
    fdc.add_argument('--out-catalog',required=True)
    # V1.1 extensions added separately
    try:
        from .optimization import add_cli
        add_cli(sub)
    except ImportError:
        pass
    return p

def render_md(data):
    # Human-readable output is supplementary to exact JSON, never alter precision in calculations.
    if isinstance(data,dict) and data.get('status')=='optimal' and 'daily_plan' in data:
        lines=['# 水果营养经济采购优化结果','',
          f"- 优化目标：{data['objective']}；状态：已证明最优（仅限当前候选与约束）",
          f"- 规划周期：{data['period_days']} 天；总成本：¥{data['total_cost_cny']:.2f}",
          f"- 涉及水果：{data['fruit_type_count']}种；总可食重量：{data['total_edible_g']:.1f}g",
          f"- 价格类型：{data['price_context']['notice']}",'']
        if data['budget_cny'] is not None:lines.append(f"- 预算：¥{data['budget_cny']:.2f}；余量：¥{data['available_budget_cny']:.2f}")
        if data['maximin_fraction'] is not None:lines.append(f"- 最差营养目标覆盖率：{data['maximin_fraction']:.2%}")
        lines+=['','## 每日食用方案','','| 第几天 | 实际可食重量 | 水果组合 |','|---:|---:|---|']
        for d in data['daily_plan']:
            names='、'.join(f"{x['fruit']} {x['edible_g']:.0f}g" for x in d['fruits'])
            lines.append(f"| {d['day']} | {d['edible_g']:.1f} g | {names} |")
        lines+=['','## 采购清单','','| 采购日 | 水果 | 买入重量 | 整包数 | 成本 |','|---:|---|---:|---:|---:|']
        for p in data['purchases']:
            package='散称' if p['packages'] is None else str(p['packages'])
            lines.append(f"| {p['day']} | {p['fruit']} | {p['purchased_kg']:.3f} kg | {package} | ¥{p['cost_cny']:.2f} |")
        if data['total_trip_fees_cny']>0:lines.append(f"\n采购固定费用：¥{data['total_trip_fees_cny']:.2f}（{len(data['shopping_days'])}个采购日）")
        lines+=['','## 水果部分营养目标覆盖','','| 营养 | 总摄入 | 预设目标 | 比例 |','|---|---:|---:|---:|']
        for k,v in data['nutrient_coverage'].items():
            lines.append(f"| {k} | {v['total']:.2f} | {v['goal_total']:.2f} | {v['completion_fraction']:.1%} |")
        lines+=['','## 证据与假设','']
        for src in data['sources']:
            lines.append(f"- {src['fruit_id']}：{src['dataset']} 条目 {src['record_id']} {src['nutrition_url']}；价格类别 {src['price_kind']}；可食率：{src['edible_yield_basis']['type']}")
            lines.append(f"  价格：{src['price_location']}，{src['price_date']}；{src['price_source_url'] or src['price_source_note']}")
        lines+=['','## 限制条件','']+[f'- {v}' for v in data['warnings']]
        return '\n'.join(lines)+'\n'
    if isinstance(data,dict) and 'nutrition' in data and 'fruit' in data:
        lines=[f"# {data['fruit']}：水果营养档案",'',f"来源：{data['source']['url']}",f"来源条目：{data['source']['record_id']}",
          '',f"可食率：{data['edible_fraction']:.0%}（{data['yield_source']['type']}）",'','| 营养素 | 每100g可食部 |','|---|---:|']
        for k,v in data['nutrition'].items():
            lines.append(f'| {k} | {"未知" if v is None else str(v)+" "+data["units"][k]} |')
        if 'pricing' in data:
            p=data['pricing'];lines+=['',f"价格：¥{p['price_cny_per_kg']}/kg，类型：{p['kind']}，地区：{p['location']}，日期：{p['observed_on']}"]
            lines += [p['price_context']['notice'],f"价格来源：{p['source_url'] or p['source_note']}"]
        return '\n'.join(lines)+'\n'
    if isinstance(data,dict) and 'ranked' in data:
        lines=[f"# {data['nutrient']} 性价比排行",'',f"范围：{data['scope']}",data['price_context']['notice'],'','| 名次 | 水果 | 营养/元 | 每kg价 |','|---:|---|---:|---:|']
        for i,r in enumerate(data['ranked'],1):
            lines.append(f"| {i} | {r['fruit']} | {r['amount_per_cny']:.4g} {r['unit']} | ¥{r['price_cny_per_kg']:.2f} |")
        for r in data['ranked']:
            p=r['price_source']
            lines+=['',f"- {r['fruit']}：{r['price_kind']}，{p['location']}，{p['date']}；{p['url'] or p['note']}"]
        return '\n'.join(lines)+'\n'
    return '```json\n'+json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n```\n'

def execute(args):
    fruits=load_catalog(args.catalog)
    if args.yields:fruits=apply_yield_overrides(fruits,args.yields)
    if args.command in ('import-web','import-fdc'):
        if args.command=='import-web':
            import_row=import_web_record(read_web_evidence(args.evidence),args.id,args.name,args.alias,
                args.edible_fraction,args.shelf_days,yield_note=args.yield_note)
            import_row['source']['evidence_sha256']=hashlib.sha256(Path(args.evidence).read_bytes()).hexdigest()
        else:
            detail=fetch_fdc(args.fdc_id,args.api_key)
            import_row=import_fdc_record(detail,args.id,args.name,args.alias,args.edible_fraction,args.shelf_days)
        digest=append_catalog(args.catalog,args.out_catalog,import_row,
            protected_paths=[args.evidence] if args.command=='import-web' else [])
        return {'imported':import_row['id'],'source':import_row['source'],'catalog':args.out_catalog,
                'catalog_sha256':digest}
    asof=dt.date.fromisoformat(args.as_of) if args.as_of else None
    prices=load_prices(args.prices,fruits,as_of=asof,allow_simulation=args.allow_simulation,
          allow_stale=args.allow_stale,allow_mixed_regions=args.allow_mixed_regions) if args.prices else {}
    if args.command=='validate':
        return {'status':'ok','fruits_count':len(fruits),'prices_count':len(prices),
            'price_context':price_context(prices.values()),
            'nutrient_sources':[x.source['url'] for x in fruits.values()],
            'simulation_used':any(p.is_simulated for p in prices.values())}
    if args.command=='profile': return profile(resolve(fruits,args.fruit),prices.get(resolve(fruits,args.fruit).id))
    if args.command=='rank': return ranking(fruits,prices,args.nutrient)
    if args.command=='compare': return compare(fruits,prices,args.fruit_a,args.fruit_b,args.nutrients)
    if args.command=='substitutes':return substitutes(fruits,prices,args.fruit,args.nutrients)
    from .optimization import execute_v11
    return execute_v11(args,fruits,prices)

def main(argv=None):
    parser=build_parser();args=parser.parse_args(argv)
    try:
        if args.command in ('import-web','import-fdc') and args.output:
            protected=[args.catalog,args.out_catalog,getattr(args,'evidence',None)]
            if Path(args.output).resolve() in {Path(p).resolve() for p in protected if p}:
                raise ValueError('--output 报告不可覆盖输入目录、证据或 --out-catalog 数据文件')
        out=execute(args)
        if isinstance(out,dict):
            hashes={}
            for label,path in [('catalog',args.catalog),('prices',args.prices),('yields',args.yields),
                               ('targets',getattr(args,'targets',None)),('evidence',getattr(args,'evidence',None))]:
                if path:hashes[label]={'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'path':str(path)}
            out['audit']={'inputs':hashes,'analysis_date':args.as_of or dt.date.today().isoformat(),
                          'solver':'SciPy HiGHS' if args.command in ('optimize','frontier') else 'deterministic arithmetic',
                          'version':__version__}
        serialized=json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False) if args.format=='json' else render_md(out)
        if args.output:Path(args.output).write_text(serialized+'\n',encoding='utf-8')
        else:print(serialized)
        return 0
    except RequestException as exc:
        # requests exception URLs can contain api_key; never echo them.
        status=getattr(getattr(exc,'response',None),'status_code',None)
        detail=f'（HTTP {status}）' if status is not None else ''
        print(f'错误: FDC API 请求失败{detail}；请检查网络、配额或密钥配置',file=sys.stderr)
        return 2
    except (ValueError,KeyError,OSError,RuntimeError) as exc:
        print(f'错误: {exc}',file=sys.stderr)
        return 2
if __name__=='__main__':sys.exit(main())

