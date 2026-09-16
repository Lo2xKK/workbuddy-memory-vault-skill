# 贡献指南

感谢你想为这个项目出力。这是一个把 WorkBuddy 对话「编译」成 Obsidian 图谱记忆库的小工具，代码量不大，欢迎任何形式的贡献。

## 环境准备

项目**零第三方运行时依赖**（只用 Python 标准库），但跑测试需要 pytest：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install pytest
```

要求 **Python 3.10+**（代码用了 `str | None` 等新语法）。

## 跑测试

```bash
pytest            # 全部单测
pytest -q         # 精简输出
```

## 目录约定

```
scripts/           主引擎（ingest.py 是入口，common/config/parse/render 是被它引用的模块）
config/            topics.example.json 是通用模板；个人 topics.json 已 gitignore
tests/             pytest 单测（只测纯函数，不碰真实 ~/.workbuddy 数据）
```

## 提 PR 的流程

1. Fork 本仓库，从 `main` 切出功能分支
2. 改代码，**补/改对应测试**
3. 本地跑 `pytest` 全绿，再跑 `python -m py_compile scripts/*.py` 确认语法
4. 提交（commit message 用 `type: 简述`，如 `fix: ...` / `feat: ...`）
5. 开 PR，描述「改了什么 + 为什么 + 怎么验证」

## 代码风格

- 函数命名 snake_case，常量 UPPER_CASE；注释与 docstring 用中文
- 纯函数优先、可测优先：解析/清洗/分类逻辑尽量独立，方便单测
- 写文件统一 `encoding="utf-8", newline="\n"`

## ⚠️ 隐私红线（务必遵守）

- 不要把 `90-原始数据/`、`config/topics.json`、`.workbuddy/`、`HANDOFF.md` 提交进仓库——它们含个人路径/会话内容，已 gitignore
- 不要提交任何真实的对话正文作为测试样例；测试用构造的最小 jsonl
- 本项目只开源「导入脚本 + 结构」，**不打包任何受版权保护的规则正文 / PDF**

## 报告问题

提 Issue 时请带上：Python 版本、运行命令、报错信息（脱敏后）。如果是分类不准确，附上会话标题 + 当前 `topics.json` 的 rules（隐去敏感字段）。
