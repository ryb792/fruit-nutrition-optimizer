# 水果营养性价比优化器 V1.1（Fruit Nutrition Optimizer）

**本文为开发者与命令行高级用法。**普通用户应优先按 [Skill 安装指南](INSTALL-SKILL.md) 在支持的 AI 宿主中安装，通过自然语言使用本技能，无需学习下列命令。数值计算在明确价格、可食率和营养目标后执行。

## 完整能力

- 输入水果名：内置8种常见鲜果的 USDA 食物成分历史条目（香蕉、甜樱桃、苹果、橙子、绿心猕猴桃、草莓、菠萝、西瓜）；支持别名。
- 输入水果照片：**使用宿主 ChatGPT 多模态视觉识别**，然后调用本 Skill。Python CLI 本身不能独立识别图片。
- 查询营养、来源ID与链接、同地区零售价换算、可食率、额外损耗、单营养价格排序、双水果对比、经济替代、临界售价、每元营养帕累托前沿。
- V1.1：多日混合整数规划（整盒购买、采购时机与储存窗口、连续散称、预算、营养目标、每日可食克数、品种最少食用量、每日能量上限、采购日固定费用）；预算内营养达标率优先的两阶段优化；离散预算样本非劣组合。
- 数据质量：来源留痕、未知营养为 `null`、拒绝未授权的模拟报价、默认拒绝超过7日的过期报价、拒绝直接跨地区比较、拒绝不可行方案。

## 安装计算引擎（Windows 10/11；开发者选读）

1. 安装 Python 3.11 或以上。解压 zip 到任意目录。
2. 打开 PowerShell：

```powershell
cd "D:\你的路径\fruit-nutrition-optimizer"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests -q
```

如果 PowerShell 限制运行激活脚本，可直接使用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`，后续运行同理。

## 快速运行

```powershell
# 无价格也可查询主要营养数据和官方记录地址
python -m fruit_optimizer profile 香蕉
python -m fruit_optimizer --format md profile 樱桃

# 以下明确使用假设价格，仅用来验证计算器，不代表市场价
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation rank 钾
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation compare 香蕉 樱桃
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation substitutes 樱桃 --nutrients 钾 维生素C
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation pareto 钾 维生素C 膳食纤维
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation threshold 香蕉 樱桃 钾

# V1.1 七天最小化水果采购成本，要求至少三种水果
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation --format md --output reports/example-plan.md optimize --days 7 --min-types 3 --targets data/targets.EXAMPLE.json

# V1.1 每周预算20元：预算内尽量改善最差营养目标覆盖率
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation optimize --days 7 --budget 20 --objective maximin --targets data/targets.EXAMPLE.json --min-types 3

# 每次采购日额外加 2 元交通/配送成本
python -m fruit_optimizer --prices data/prices.SIMULATION.json --allow-simulation optimize --days 7 --trip-fee 2

# 覆盖自己的水果可食率、坏损率和可保存天数
python -m fruit_optimizer --yields data/yields.template.json profile 香蕉
```

**请注意：** `--format md`、`--output`、`--prices` 是全局参数，必须放在 `optimize` 等子命令之前。

## 使用真实价格

复制 `data/prices.template.json` 为 `data/prices.local.json`，修改其中的 `amount_cny`，填实际可核查日期和城市/门店、商品链接或小票说明、计量方式：

- `measure: kg`：每公斤多少元；
- `measure: jin`：每市斤（500g）多少元；
- `measure: pack`：整包装多少元，必须给 `package_kg`；
- 如果是整盒不可拆卖，即使报价为 `kg` 仍可填写 `package_kg` 表示只能整包采购；
- 零售 `kind=retail`，实际小票 `kind=user_receipt`，模拟价格 `kind=simulation`；
- `observed_on` 为 `YYYY-MM-DD`；`source_url` 或 `source_note` 必填；`location` 必填。

```powershell
python -m fruit_optimizer --prices data/prices.local.json rank 钾
```

日期超过7天会提示拒绝；只有用户明确接受旧价格作参考时才使用 `--allow-stale`。跨地区报价默认不能混比。**系统不会自动获取未验证的实时零售价。** 本地价格模板 `amount_cny=0` 是待填写值，不能直接作为零售价运行。

`data/targets.EXAMPLE.json` 的维生素C、钾、膳食纤维目标是**数学例题**，不是《中国居民膳食营养素参考摄入量》中的推荐值，也不是医疗建议。设置自己的水果营养目标时必须说明具体来源。

## 在线增补营养条目（可选）

FoodData Central 免费 API 要求 Data.gov API Key，申请地址：<https://fdc.nal.usda.gov/api-guide/>。安装环境需能访问 `api.nal.usda.gov`。不需要联网的基础分析可用内置历史数据。

```powershell
$env:FDC_API_KEY="你的密钥"
python -m fruit_optimizer import-fdc 173944 --id banana_new --name "新香蕉条目" --edible-fraction 0.65 --out-catalog data/fruits.custom.json
```

导入完成后需人工检查条目品种、生熟、可食部、日期和 aliases，避免把相同水果不同条目直接当作独立品种。后续用 `--catalog data/fruits.custom.json` 调用。注意不要在公开代码仓库中提交 API Key。

## 质量、可信度与局限

- **USDA来源**：每个水果记录包含 FDC ID 和官方条目链接，内置的是历史公开 SR Legacy 食物成分数据，并非用户所买果实的实测结果，品种、产地和成熟度可能造成波动。官方数据入口：<https://fdc.nal.usda.gov/>。
- **样本覆盖**：目前内置仅8种，结果只能称“在已覆盖的候选中最优”。可追加新鲜水果条目扩大覆盖。
- **价格**：默认只有模拟例子，必须填本地可靠报价才能进行实际价格比较。
- **可食率**：内置率是明确标记的**规划假设**，不是USDA原始食物成分中已核验的食部比例；食材最优结果可能对其非常敏感。请用去皮去核称重或来源可靠的数据修改。保质期也为场景假设。
- **科学意义**：最小化的是约束模型中的买水果成本，不是保证各类营养素都能由水果供给；对健康的收益还涉及整日膳食、吸收、个人状态等复杂因素。
- **采购精度**：散称模型允许购买任意重量，并假设当日购买食用；整包装模型严格按包装整数计数。包装未吃完的余量单独显示，不一定已经腐坏。订购最低金额、动态阶梯运费、多次平台配送价等尚未建模；可以用每采购日的固定成本近似，但需要明确标注。
- **视觉**：只有在 ChatGPT / 支持视觉的宿主中才能通过照片识别水果；CLI 不包含视觉模型。我们无法在当前测试环境中对真实相机照片模型准确率做端到端保证。
- **在线同步**：FDC 接口逻辑采用模拟HTTP单元测试验证，当前运行环境禁止外网访问，因此**没有**实测公网调用成功；需要你在可联网环境验证并保存实际请求日志。

## 测试与验收

`python -m pytest tests -q` 全部单元与约束测试必须通过。特别包括：营养源ID、价格单位、真假价格区分、过期价格、维生素缺失状态、整数包装与独立穷举证明、日程和保质期、预算限制、目标不可行、最差覆盖率及采购费用校验。

`reports/` 提供两个版本的测试记录、模拟方案与审计输出。详情：`reports/TEST-REPORT.md`。
