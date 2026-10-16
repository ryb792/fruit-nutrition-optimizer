# 数学方法与约束

## 购买重量与可食部
`edible_g = purchased_kg * 1000 * edible_fraction * (1-extra_waste_fraction)`。

## 单项营养每元价格
`nutrient_per_CNY = nutrient_per_100g * 10 * edible_fraction * (1-extra_waste_fraction) / price_per_kg`。
数值只有在 price_per_kg > 0 且营养数值不缺失时定义；本实现明确拒绝免费商品价格，避免无限效率下比较失效及库存无限的问题。

## 目标约束
每个食用日满足 `daily_min_g <= edible_fruit_grams <= daily_max_g`。
可选能量上限：`sum(energy_per_100g * edible_g / 100) <= max_daily_energy_kcal`。
营养目标：`sum(all_days, fruit_g / 100 * nutrient_per_100g) >= days * nutrient_target_per_day`。
`maximin` 目标松弛为 `total_nutrient >= days * target * t`；先最大化 t，t 在0到1，再最小化成本（t基本不变）。

## 包装与保质期
对于包装水果，购买日 p 整数包数 z[p,i]，各日消耗 q[p,d,i] >= 0，满足 `sum_d q[p,d,i] <= package_kg * 1000 * edible_fraction * (1-loss) * z[p,i]`。只有 d 在 p..p+shelf_days-1 内才生成 q。散称水果按需购买，q[p,p,i] 按有效可食克数计费；没有跨日散称库存。

## 有关严格最优性的限定
MILP求解器状态为`0`（达到最优证明）才报告 `optimal`，状态不可行或未证最优直接报错。最优性相对于录入的候选水果、营养值、价格、货架期与数学约束，绝不是所有市场水果的全球最优。若使用过时、模拟或假设价格，则只是相应情景最优。

## 帕累托比较
一水果相对另一水果，在每元产出的全部指定营养素上均不小（容差内），且至少一项严格大，才能支配它；未知营养字段导致该水果从该次帕累托分析候选中排除，不把未知设为0。`frontier` 只计算用户提供的离散预算列表的样本非劣点，不声称完整连续前沿。
