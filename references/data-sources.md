# 数据来源及口径

## USDA FoodData Central

- https://fdc.nal.usda.gov/
- API 指南：https://fdc.nal.usda.gov/api-guide/
- CSV 和 JSON 下载：https://fdc.nal.usda.gov/download-datasets/
- 公开下载文件不需要 API Key；普通用户新增水果优先由 Agent 打开官方网页或下载原始数据，按 [联网查证与导入](web-retrieval.md) 保存证据。API 是独立保留的开发者选项。
- 本技能内置8条条目，详见 `data/fruits.usda-sr-legacy.snapshot.json` 里的 `record_id` 与 `source.url`；这些都是历史 SR Legacy（April 2018）数据。
- USDA 不等于中国当地市场的精确品种营养；某些水果需视情况优先使用更相关的本地食物成分条目。
- `data/web-evidence.mango-tommy-atkins.json` 摘自 2026-04 Foundation 官方 JSON 下载包，FDC 2710833，原始描述为 `Mango, Tommy Atkins, peeled, raw`，访问日期 2026-10-17。能量采用原记录的 Atwater Specific Factors 值；未将另一能量定义平均，也未补齐缺失的糖/叶酸。

## 中国食物成分查询平台与膳食参考

- 中国食物营养成分查询平台：https://nlc.chinanutri.cn/fq/
- 中国营养学会：https://www.cnsoc.org/
- 《中国居民膳食营养素参考摄入量（2023版）》相关信息：https://www.cnsoc.org/drpostand/
- 中国居民膳食指南（2022）：一般成年人的新鲜水果200～350g参考区间；不作为针对所有人的最大安全摄入量。
- 导入本地营养条目需核验各平台的开放获取与商业使用条款，不得未经许可批量转载受限数据库。

## 零售市场价格

- 用户的实际小票、价签或当地零售电商商品页优先。记录日期、城市、规格、货币、可核验来源。
- 全国批发市场价格只能用于解释趋势，不能作为某用户当地实际零售价。
- 价格超过7天默认拒绝作为当前售价；允许用户明确改作历史情景分析。
- 价格来自不同地区须先统一采购市场，否则默认不可比。

## 可食率与储存天数

- USDA `nutrition_per_100g_edible` 不提供用户具体采购商品果皮与果核的实际占比。
- 内置 yield 与 shelf_days 参数是**模型假设**，在对应条目单独说明；推荐用户实际称重后用 `--yields` 覆盖。

