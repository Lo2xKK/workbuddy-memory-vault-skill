# Changelog

本文件记录 `memory-vault-skill` 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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

[1.0.0]: https://github.com/Lo2xKK/workbuddy-memory-vault-skill/releases/tag/v1.0.0
