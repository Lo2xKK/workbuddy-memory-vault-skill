# Changelog

本文件记录 `memory-vault-skill` 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-09-17

### 变更

- **重构**：`ingest.py`（单文件 1269 行）按职责拆为五模块——`common.py`（常量 / 清洗 / 工具）、`config.py`（配置 / 分类 / 增量台账）、`parse.py`（jsonl 解析）、`render.py`（全部渲染）、`ingest.py`（仅留 `main` 编排）。拆分的直接收益是纯函数脱离 I/O，可被单测覆盖。

### 新增

- **单元测试**：`tests/` 共 35 个用例，覆盖 `clean_text` / `demote_headings` / `slugify` / `yaml_quote` / `fmt_ts` / `classify` / `project_name` / `resolve_title` / `is_changed` / `parse_transcript`；只测纯函数，不触碰真实 `~/.workbuddy` 数据。
- **持续集成**：GitHub Actions `CI` 工作流，Python 3.10 / 3.12 / 3.13 矩阵跑 `pytest` + `py_compile`。
- **贡献指南**：`CONTRIBUTING.md`（环境准备 / 跑测试 / 目录约定 / PR 流程 / 隐私红线）。
- `pyproject.toml`：声明 `requires-python >= 3.10` 与项目元数据，并承载 pytest 配置；`.gitattributes` 统一 LF 换行。

### 修复

- `created_at` 为 `None` 时的兜底，避免时间线节点因缺时间戳而断链。
- sqlite URI 统一用 `as_posix()` 构造，消除 Windows 下路径分隔符导致的连接失败。
- `classify` 跳过空关键字，避免空串命中所有标题。
- `copy_raw_files` 由静默吞错改为显式报错，原始备份失败不再无声。
- `slugify` 处理 Windows 保留名（`CON` / `PRN` / `AUX` / `NUL` 等），避免生成无法创建的文件名。
- **`title_prefix_rules` 配置格式与解析代码错配**：真实配置是对象数组，代码却按元组解包，导致规则静默永不命中。
- **`memory_roots` 硬编码改配置化时漏迁默认值**：导致「项目记忆同步」整块静默失效（记忆副本 45 → 5 且不报错）。

### 移除

- `config/topics.example.json` 中未生效的 `person.folder` / `person.note` 死配置。
- 会话 frontmatter 中未被读取的 `month` 字段。

## [1.0.0] - 2026-09-16

### 新增

- 五阶段流水线：Survey（manifest 增量）→ Parse（解析对话）→ Extract（提取实体）→ Graph（建图谱关系）→ Verify（体检）。
- 三维节点：`10-主题`（概念）、`40-时间线`（月节点）、`30-人物`（「我」的图谱锚点）。
- `.manifest.json` 增量台账，第二次运行只处理新增/变更会话（`--full` 强制全量）。
- `check.py` 体检 v2：断链 / 孤岛 / 边分层分布检测，目标断链 0、孤岛 0。
- 配置模板 `topics.example.json`（零配置回退），个人配置 `topics.json` 本地化（gitignore）。
- `--list` 空转预览、`--vault` 指定输出、`--only` 单会话调试、`--no-*` 系列开关。

### 借鉴

- `Ar9av/obsidian-wiki`：「编译而非堆积」哲学、声明溯源标注、`.manifest.json` 增量。
- `alvaroum/agents-vault-memory`：会话 / 日 / 周 / 月 / 年的时间分层。
- `broomva/control-metalayer`：会话文档 + MOC 索引 + frontmatter 元数据。

[1.1.0]: https://github.com/Lo2xKK/workbuddy-memory-vault-skill/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Lo2xKK/workbuddy-memory-vault-skill/releases/tag/v1.0.0
