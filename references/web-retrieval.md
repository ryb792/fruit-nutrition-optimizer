# 免密钥联网查证与导入

## 检索与核对

1. 在当前目录执行 `profile 水果名`，确认是缺少记录还是别名/品种问题。记录当前使用的 `--catalog`，追加时以该目录为输入。
2. 使用宿主联网工具搜索权威原始来源，优先 USDA FoodData Central、中国食物营养成分查询平台或其他政府/研究机构官方数据库。必须实际打开正文或原始下载数据；搜索摘要和转载网站不能代替原始表格。
3. USDA 动态条目未显示营养表时，打开 <https://fdc.nal.usda.gov/download-datasets/>，选择官方公开 JSON 或 CSV。下载不需要 API Key；JSON 的 `FoundationFoods` / `SRLegacyFoods` 中按 `fdcId` 和完整描述选取单一记录。不要下载庞大的全库或品牌食品包来查询一种鲜果。
4. 确认水果品种、raw 生鲜、皮核是否排除、营养值是否按可食部及对应克数。不可将冻干、果干、果汁或糖水罐头映射成鲜果。未能确认口径则停止导入；无法确定具体品种时说明采用的参考品种并保留完整名称。
5. 仅转录实际读到的值：钾、钙、镁、维C、B6、总膳食纤维、总糖、总叶酸、能量。区分 total folate / DFE、total sugars / added sugars、不同能量定义；不可用相近名称代替。USDA `foodNutrients[].amount` 是对应原始记录的每100g可食部成分，不是 `foodPortions` 的整份总量。能量有多种定义时只选一种并保留原名；不要平均。
6. 记录来源 URL、机构、数据集、条目 ID、访问日期、原始数值/单位和表格行或 JSON 定位。缺失字段可省略或写 `null`，不得填 0；`<0.1` 等界限值不可改为精确值，先保留为缺失并说明。
7. 将证据存为独立 JSON，运行 `import-web`。可食率用用户称重或明确披露的规划假设；它是购入重量到可食重量的转换，不用于再次扣减来源已按可食部给出的营养值。
8. 后续所有计算使用生成目录；无可靠价格时只给营养结论。缓存已核验记录并保留访问日期，除非用户要求更新或发现来源问题，不必重复下载。营养历史条目不会因刚访问就变成实时检测。

## 证据格式 v1

完整、真实的实例是 `data/web-evidence.mango-tommy-atkins.json`：2026-10-17 从 USDA Foundation 2026-04 官方下载包读取 FDC 2710833。它代表 **Tommy Atkins 去皮生芒果**，不可声称为所有中国芒果的精确实测值。来源记录发表于 2024-10-31；访问日期不等于数据发布日期。

顶层仅接受 `schema_version`、`source`、`basis`、`nutrients`：

| 字段 | 必填内容 |
| --- | --- |
| `schema_version` | 整数 `1` |
| `source` | `publisher`、`dataset`、`record_id`、`url`（HTTPS）、`accessed_on`（YYYY-MM-DD）、`food_description`（原始完整描述）、`food_state`（`raw`）、`edible_portion`（皮核食部说明）；可选 `publication_date` |
| `basis` | `amount_g`（原始表格对应的正数克重）、`portion`（`edible`） |
| `nutrients` | 数组；每项包含 `key`、`value`（非负数字或 `null`）、`unit`、`source_label`（原名）、`locator`（表格行/JSON 定位） |

营养 key：`potassium_mg`、`vitamin_c_mg`、`vitamin_b6_mg`、`fiber_g`、`magnesium_mg`、`energy_kcal`、`sugar_g`、`folate_ug`、`calcium_mg`。质量单位接受 `g/mg/ug/µg/μg`；能量接受 `kcal/kJ`（1 kcal = 4.184 kJ），其他单位拒绝。程序统一转换为每100g可食部以及 key 指定的单位，原值和转换依据保留于 `source`。不支持 IU、%DV、每个水果或干物质计量，除非权威来源给出明确可食克重且先核实。

## 可运行示例

从 Skill 根目录执行，证据文件由 Agent 完成，普通用户无需手工配置：

```bash
python -m fruit_optimizer import-web data/web-evidence.mango-tommy-atkins.json \
  --id mango_tommy_atkins --name "芒果（Tommy Atkins，去皮生鲜）" --alias "Tommy Atkins芒果" \
  --edible-fraction 0.70 --yield-note "演示规划假设70%，并非USDA测定；实际请称重" \
  --shelf-days 5 --out-catalog data/fruits.local.json
python -m fruit_optimizer --catalog data/fruits.local.json profile "Tommy Atkins芒果"
python -m fruit_optimizer --catalog data/fruits.local.json compare "Tommy Atkins芒果" 香蕉 --nutrients 钾 维生素C
```

`--out-catalog` 必须不同于输入目录和证据文件；原目录保持不变。先校验合并目录的 ID/别名冲突，再原子写入结果；失败不覆盖已有输出。成功会替换指定的已有输出文件，因此更新已有自定义目录时，把它作为 `--catalog` 并选择另一个输出文件。返回原始证据文件及结果目录 SHA256，计算报告也保留来源和证据。

该命令不执行网络请求。宿主负责来源真实性和条目匹配，程序负责结构、数值、单位、食部口径和合并校验。不要将“导入校验通过”表述成“程序证明网页数据真实”。
