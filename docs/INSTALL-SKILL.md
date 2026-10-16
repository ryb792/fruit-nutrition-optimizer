# 安装 Fruit Nutrition Optimizer — Agent Skills

**GitHub 项目地址：** <https://github.com/ryb792/fruit-nutrition-optimizer>

这是一个采用 Agent Skills 结构的技能包，不是独立桌面程序。`SKILL.md` 提供技能指令；`fruit_optimizer/`、`data/`、`references/` 和 `requirements.txt` 是运行与复核分析所需的项目文件。

## 通过 Agent 安装

在具备仓库访问能力且支持安装 Agent Skills 的 Agent 中发送：

> 请安装 https://github.com/ryb792/fruit-nutrition-optimizer 中的 `fruit-nutrition-optimizer` Agent Skill。先审查仓库内容和依赖，按照**当前 Agent 平台官方的技能安装机制**安装或导入完整技能目录，保留 `SKILL.md`、`fruit_optimizer/`、`data/`、`references/` 和 `requirements.txt` 的相对位置。不要假定所有 Agent 使用相同的安装路径。具备 Python 执行环境时，请安装依赖并运行 `python -m pytest tests -q`，确认技能可加载，并反馈实际安装位置、测试结果及是否需要重新加载。若无安装或执行权限，请如实说明并提供当前平台对应的手动步骤，勿虚报安装成功。

如 Agent 缺少联网、下载、文件写入或 Python 执行权限，相关操作可能无法自动完成。技能运行方式以所用 Agent 平台的官方支持说明为准。

## 手动安装

1. 访问仓库主页，选择 **Code → Download ZIP**，并解压。
2. 保留完整 `fruit-nutrition-optimizer/` 目录，确认目录根部有 `SKILL.md`，且同级存在 `fruit_optimizer/`、`data/`、`references/`、`requirements.txt`。
3. 根据**当前 Agent 平台**的官方文档，找到 Skills 安装入口、技能目录或导入功能，将完整目录添加进去。不同 Agent 的安装路径不同，不能统一使用某一个固定目录。
4. 根据平台要求刷新或重新加载技能，并尝试输入：“请使用 fruit-nutrition-optimizer Skill 分析香蕉和樱桃的补钾成本。”
5. 要进行准确的成本排名、帕累托分析或组合优化，确认 Agent 可以运行项目自带的 Python 脚本；不能执行时应将结果明确标为未验证计算。

## 配置精确计算所需依赖

在具备 Python 3.11+ 的可执行环境中，进入 Skill 根目录运行：

```bash
python -m pip install -r requirements.txt
python -m fruit_optimizer profile 香蕉
python -m pytest tests -q
```

运行依赖包括 `numpy`、`scipy`、`requests` 等，具体以 `requirements.txt` 为准。若由 Agent 执行，应优先使用隔离环境并审核第三方代码与权限。没有可用的 Python 环境时可以说明已知水果营养信息，但不能声称已执行混合整数规划或精确计算。

## 数据与价格

内置营养快照包含 USDA FoodData Central 条目 ID；`data/prices.SIMULATION.json` 是纯模拟报价，不能用于真实采购结论。

实际价格请按照 `data/prices.template.json` 提供有来源的售价、地区和采集时间，另存为本地文件，避免提交私人采购信息。

更多计算命令见 [开发者与命令行指南](ADVANCED.md)。照片识别依赖所使用的 Agent 是否具备视觉输入能力；本项目 Python 组件不包含独立的视觉识别模型。
