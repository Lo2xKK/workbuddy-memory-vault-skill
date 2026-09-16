# 记忆库生成器（workbuddy-memory-vault-skill）

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/Lo2xKK/workbuddy-memory-vault-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/Lo2xKK/workbuddy-memory-vault-skill/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.1.0-brightgreen)](CHANGELOG.md)
[![WorkBuddy](https://img.shields.io/badge/for-WorkBuddy-7C3AED)](https://www.workbuddy.cn/)

把 **WorkBuddy** 的记忆与历史对话，编译成 **Obsidian 图谱记忆库**——按「主题 / 时间 / 人物」三个维度自动建立节点与双链关联。

<p align="center">
  <img src="docs/architecture.svg" alt="架构：五阶段流水线 + 三维节点" width="860"/>
</p>

> 灵感来自 GitHub 上的 `Ar9av/obsidian-wiki`（「编译而非堆积」）、`alvaroum/agents-vault-memory`（时间分层）、`broomva/control-metalayer`（会话文档 + MOC）。本项目借鉴其结构，针对 WorkBuddy 的数据源落地。

## 一句话

你周二解决了一个难题，三个月后又在另一个项目里从头解决一遍——因为答案躺在一个你永远找不到的聊天记录里。这个工具把那些记录**编译**成互联的 markdown，你拥有它、能搜它、能用图谱看它。

## 它解决什么

| 维度 | 节点 | 关联方式 |
|---|---|---|
| **主题** | `10-主题/<主题> 会话索引.md` | 规则分类 + 会话归类 |
| **时间** | `40-时间线/YYYY-MM.md` | 会话 ↔ 月节点双向链接 |
| **人物** | `30-人物/<name>.md` | 身份提炼 + 关联主题 |

配合 `20-对话归档/`（会话全文）、`30-我的记忆/`（身份快照 + 项目记忆）、`90-原始数据/`（jsonl 备份），构成一张可检索、可追溯、成网的知识图谱。

## 快速开始

```bash
# 1. 把脚本复制进你的 vault（脚本自定位 vault 根）
cp -r scripts/* <你的vault>/_tools/

# 2. 从模板复制出你的配置（个人配置不进版本库）
cp config/topics.example.json <你的vault>/_tools/topics.json
# 编辑 <你的vault>/_tools/topics.json：改 person / topics / rules / projects / memory_roots

# 3. 先空转预览，确认分类无误
python <你的vault>/_tools/ingest.py --list

# 4. 正式生成
python <你的vault>/_tools/ingest.py

# 5. 体检（目标：断链 0、孤岛 0）
python <你的vault>/_tools/check.py
```

用 managed Python（Windows）：`~/.workbuddy/binaries/python/versions/3.13.12/python.exe`（替换成你的实际用户名路径）

## 命令行参数

| 参数 | 作用 |
|---|---|
| `--list` | 空转，只列会话与分类，不写文件 |
| `--full` | 忽略 `.manifest.json`，强制全量重建 |
| `--vault <目录>` | 指定输出 vault（默认自定位） |
| `--only <ID前缀>` | 只同步一个会话（调试） |
| `--no-raw` | 不备份 jsonl 到 `90-原始数据/` |
| `--no-tools` | 不输出工具调用轨迹 |
| `--no-memory` | 不同步 `30-我的记忆/` |
| `--no-timeline` | 不生成 `40-时间线/` |
| `--no-person` | 不生成 `30-人物/` |

**幂等**：重复跑只覆盖自己生成的文件（`generated_by: ingest.py` 标记），绝不碰手工目录。
**只读**：不修改 `~/.workbuddy/` 下任何东西。
**增量**：`.manifest.json` 记录每个会话的 mtime，第二次运行只处理新增/变更。

## 目录结构与四层职责

```
<vault>/
├── 00-总览/            索引层：只做导航，绝不写细节
├── 10-主题/            知识层：结论 / 卡片 / 会话索引
├── 20-对话归档/        原料层：会话全文（机器生成，不手改）
├── 30-我的记忆/        原料层：身份快照 / 用户画像 / 项目记忆
├── 30-人物/            实体层：人物节点（「我」的图谱锚点）
├── 40-时间线/          时间层：月节点（会话 ↔ 月双向链接）
├── 90-原始数据/        原始 jsonl（务必 gitignore）
├── .manifest.json      增量台账
└── _tools/             ingest.py + check.py + topics.json
```

## 配置（topics.example.json → topics.json）

仓库只分发通用模板 `config/topics.example.json`；你把它复制成 `topics.json` 后改成自己的（`topics.json` 已 gitignore，不会泄露）。

```json
{
  "person": { "name": "我", "label": "我" },
  "topics": { "工程与工具": { "note": "工程与工具 总览", "label": "工程与工具" } },
  "rules": [ { "topic": "工程与工具", "match": ["skill", "github", "mcp", "obsidian"] } ],
  "default": "日常与运维",
  "title_overrides": { "<session-id 前缀>": "人工标题" },
  "projects": { "d:\\path\\to\\your-project": "项目名" },
  "project_default": "临时工作区",
  "memory_roots": ["D:/path/to/你的工作区根目录"]
}
```

- `rules` 顺序匹配、先中者胜，对「标题 + cwd」做包含判断
- 改完先跑 `--list` 空转看分类，确认无误再正式跑
- 找不到 `topics.json` 时脚本自动回退到 `topics.example.json`（零配置也能跑出结果）

## 隐私红线（开源前必读）

1. `90-原始数据/` 含本机路径、微信临时文件路径、个人成绩等敏感信息——**已 gitignore，公开前务必再确认**。
2. `20-对话归档/` 是清洗后的全文，仍可能含敏感细节——**公开前逐篇检查**。
3. 本项目**不打包任何受版权保护的数据**（规则正文、PDF 等），只开源导入脚本与结构。

## 已知局限

- 「人物」维度目前是「用户本人」单一节点（从 `USER.md` 提炼），对话中提到的**第三方人物**尚未自动提取——这是后续可扩展点（需引入实体识别或 LLM 提取）。
- 主题分类是**规则匹配**（关键词包含），不是语义理解；复杂语义需人工调 `rules` 或后续加 LLM 提取。
- 增量判断依赖 jsonl 的 `mtime`，若外部工具改了 mtime 会误判为变更（代价只是多跑一次，无副作用）。

## 开发与测试

```bash
pip install pytest
pytest -q                 # 35 个单测，只覆盖纯函数，不读真实数据
python -m py_compile scripts/*.py
```

单测跑在 `tests/`，CI（Python 3.10 / 3.12 / 3.13 矩阵）在每次 push 与 PR 时自动执行。参与开发前请先读 [CONTRIBUTING.md](CONTRIBUTING.md)（环境准备 / 目录约定 / PR 流程 / 隐私红线）。

## License

MIT
