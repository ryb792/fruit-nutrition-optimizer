"""Generate transparent, small reference snapshot. Nutrients from USDA SR Legacy records (2018).
Do not run this to infer current retail prices or lab-test individual produce.
"""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
# Fields: potassium mg, vitamin C mg, vitamin B6 mg, dietary fiber g, magnesium mg,
# energy kcal, sugar g, folate microgram, calcium mg per 100g edible raw fruit.
rows=[
('banana','香蕉',['bananas','banana'],173944,[358,8.7,.367,2.6,27,89,12.23,20,5],.65,4),
('cherry','甜樱桃',['樱桃','车厘子','sweet cherry','cherries'],171719,[222,7,.049,2.1,11,63,12.82,4,13],.90,5),
('apple','苹果',['apple','apples'],171688,[107,4.6,.041,2.4,5,52,10.39,3,6],.90,14),
('orange','橙子',['orange','oranges'],169097,[181,53.2,.06,2.4,10,47,9.35,30,40],.73,10),
('kiwi_green','绿心猕猴桃',['猕猴桃','kiwi','kiwifruit'],168153,[312,92.7,.063,3.0,17,61,8.99,25,34],.76,7),
('strawberry','草莓',['strawberry','strawberries'],167762,[153,58.8,.047,2.0,13,32,4.89,24,16],.94,3),
('pineapple','菠萝',['pineapple'],169124,[109,47.8,.112,1.4,12,50,9.85,18,13],.51,5),
('watermelon','西瓜',['watermelon'],167765,[112,8.1,.045,.4,10,30,6.2,3,7],.52,4),
]
keys=['potassium_mg','vitamin_c_mg','vitamin_b6_mg','fiber_g','magnesium_mg','energy_kcal','sugar_g','folate_ug','calcium_mg']
records=[]
for fid,name,aliases,fdc,values,y,shelf in rows:
    records.append({'id':fid,'name':name,'aliases':aliases,
      'nutrition_per_100g_edible':dict(zip(keys,values)),
      'edible_fraction':y,'extra_waste_fraction':0.0,'shelf_days':shelf,
      'source':{'dataset':'USDA FoodData Central - SR Legacy (April 2018)',
        'record_id':str(fdc),'url':f'https://fdc.nal.usda.gov/food-details/{fdc}/nutrients',
        'data_type':'SR Legacy','retrieval_note':'手工摘录的公开食物成分数据，非自动实时同步；请访问FDC原条目核对，品种或产地可能不同',
        'secondary_crosscheck':f'https://whatyoueat.io/foods/{fdc}'},
      'yield_source':{'type':'planning_assumption','note':'可食率为粗略情景假设，未独立查证；应以当地品种称重或可靠的食部数据覆盖'},
      'shelf_source':{'type':'planning_assumption','note':'存放天数假设，依储存条件和成熟度变化'}})
(root/'data/fruits.usda-sr-legacy.snapshot.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print('created',len(records),'records')
