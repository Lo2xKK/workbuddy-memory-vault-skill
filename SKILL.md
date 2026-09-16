---
name: workbuddy-memory-vault-skill
description: 把 WorkBuddy 的记忆与历史对话编译成 Obsidian 图谱记忆库，按「主题 / 时间 / 人物」三个维度自动建立节点与双链关联。当用户要求"整理对话到 Obsidian"、"建记忆库/知识库"、"导出历史对话"、"生成对话图谱"、或要同步/更新这类仓库时使用。含数据源位置、jsonl 解析、噪音清洗、manifest 增量、三维节点生成、双链规范与全部踩坑记录。触发词：Obsidian、记忆库、知识库、对话归档、图谱、时间线、人物节点、同步记忆、vault。
agent_created: true
---

# 记忆库生成器：WorkBuddy 记忆 → Obsidian 图谱记忆库

把 `~/.workbuddy/` 下的记忆与历史对话，清洗成结构化 markdown 灌进 Obsidian 仓库，并**按三个维度自动建节点与关联链接**：

- **主题** —— 规则分类（`topics.json`），会话归类 + 主题聚合页
- **时间** —— `40-时间线/YYYY-MM.md` 月节点，会话 ↔ 月节点双向链接
- **人物** —— `30-人物/<name>.md` 人物节点，从身份文件提炼「我」的图谱锚点

> 本 skill 是 v2：在 v1（早期 `sync.py` 四层结构）基础上新增 `.manifest.json` 增量 + 时间线 + 人物三维节点。
> 脚本在 `scripts/ingest.py`，配置模板在 `config/topics.example.json`。
> **要新开一个 vault：把 `scripts/` 和 `config/` 的内容复制到 `<vault>/_tools/`，把 `topics.example.json` 复制成 `topics.json` 后改 projects / memory_roots / person**（脚本用 `__file__` 自定位 vault 根；找不到 `topics.json` 会自动回退到 `topics.example.json`）。

---

## 零、先给方案再动手（硬性）

用户偏好「先给方案、经同意再动手」。开跑前应当：

1. 盘点数据源实际体量（文件数、MB、会话数）——**用真实数字说话**
2. 给结构图 + 决策点让用户选（归档粒度 / 分类体系 / 是否要三维节点）
3. 用户拍板后才开工

---

## 一、输入（数据源在哪）

| 内容 | 位置 | 说明 |
|---|---|---|
| **会话标题 / cwd / status** | `~/.workbuddy/workbuddy.db` → `sessions` 表 | 只读 URI 打开，不影响运行中的 App |
| **对话全文** | `~/.workbuddy/projects/<workspace-slug>/<session-id>.jsonl` | `glob("projects/*/*.jsonl")`，stem 即 session id |
| 身份文件 | `~/.workbuddy/{SOUL,IDENTITY,USER,MEMORY}.md` | 支撑「人物」维度（USER.md 的 Name/City/Notes） |
| 用户画像 | `~/.workbuddy/memory/<uid>_memory.md` | 服务端维护 |
| 项目记忆 | `<项目根>/.workbuddy/memory/*.md` | 扫描根在 `topics.json` 的 `memory_roots` |

### jsonl 自省要点

| type | 用途 | 处理 |
|---|---|---|
| `message` + `role=user` | 用户提问 | 必须剥离 system-reminder 样板 |
| `message` + `role=assistant` | 助手回复 | 按 user 消息分组拼接（碎片化） |
| `function_call` | 工具调用 | 留 name + arguments 前 160 字符 |
| `function_call_result` / `reasoning` / 文件快照 | 噪音 | 丢弃 |

**真实体量参考（33 会话）**：43 MB 原始 → 清洗后 1.7 MB，噪音占 95%+。

---

## 二、处理流程（五阶段）

1. **Survey 盘点增量** —— 读 `.manifest.json`，按 jsonl 的 mtime 判断新增/变更，跳过未变会话（`--full` 强制全量）。
2. **Parse 解析对话** —— 按 `type` 分类，user 消息分组、拼接 assistant 碎片、剥 system-reminder。
3. **Extract 提取实体** —— `classify()` 按规则分类主题；`extract_person_fields()` 从 USER/IDENTITY 提取人物字段；时间锚点取会话时间戳。
4. **Graph 建图谱关系** —— 会话归档链向「主题 + 时间线月节点」；时间线月节点显式列当月会话 + 链主题；人物节点链主题 + 身份快照。
5. **Verify 输出 + 体检** —— 生成 markdown 后跑 `check.py`，强制**断链 0 / 孤岛 0**。

---

## 三、输出（Obsidian 目录结构）

```
<vault>/
├── 00-总览/            Home / 主题地图 / 时间线总览        ← 手工，索引层
├── 10-主题/            主题总览 + 卡片 + <主题> 会话索引.md  ← 知识层
├── 20-对话归档/        YYYY-MM/YYYY-MM-DD-HHMM-标题.md     ← 原料层（自动）
│   ├── 对话索引.md / 对话索引.base
├── 30-我的记忆/        身份快照 / 用户画像 / 项目记忆        ← 原料层（自动）
├── 30-人物/            <name>.md 人物节点                   ← 实体层（自动）
├── 40-时间线/          YYYY-MM.md 月节点                    ← 时间层（自动）
├── 90-原始数据/        jsonl 只读副本（务必 gitignore）
├── .manifest.json      增量台账（自动）
└── _tools/             ingest.py + check.py + topics.json
```

### 归档文件 frontmatter

```yaml
---
title: "..."
type: conversation
topic: "RoboMaster"
session_id: uuid
date: 2026-09-15
timeline: "2026-09"      # 时间维度
person: "我"             # 人物维度（取 topics.json 的 person.name）
project: "MATLAB 作业"
turns: 3
tool_calls: 12
tags: [对话归档, RoboMaster]
generated_by: ingest.py
---
```

---

## 四、八个必踩的坑（继承自 v1，别重踩）

1. **助手回复碎片化** —— 必须按 user 消息分组后 `\n\n` 拼接。
2. **system-reminder 样板必须剥** —— 非贪婪正则 DOTALL 反复剥 4 轮。
3. **正文标题污染大纲** —— 降一级，跳过代码块内 `#`。
4. **项目记忆路径** —— 项目根是 `d.parent.parent`，不是 `parent.parent.parent`；根工作区自己的 memory 要单独加。
5. **未登记项目同名覆盖** —— 来源目录名压进文件名，别多开一层目录。
6. **双链写法** —— 会话归档用纯文件名 stem；时间线/人物用 vault 相对全路径（`[[40-时间线/2026-09]]`）；表格内 alias 用 `\|`。
7. **图谱默认毛球** —— 必须配 `graph.json` 的 `search` + `colorGroups`，过滤原料层。
8. **索引层重复列举制造无信息边** —— 会话清单交 Bases 动态渲染；归档面包屑只留 1-2 个语义出口。

### v2 新增的坑（本 skill 落地时踩的）

9. **PowerShell 重定向写 UTF-16** —— Windows 下 `python ingest.py > log.txt` 会写 UTF-16，中文乱码；验证输出要么脚本内 `sys.stdout.reconfigure(encoding="utf-8")`，要么用 Python `subprocess.run(..., capture_output=True, encoding="utf-8")` 兜住再落盘。
10. **人物节点增量漏主题** —— `topics_touched` 若只取「本次新增的 rows」，增量模式下人物节点只显示最近一批主题；必须扫描整个 `20-对话归档/` 的 frontmatter `topic` 字段（同时间线月节点的做法）。
11. **时间线「上月/下月」导航断链** —— 直接 `[[40-时间线/{prev_month}]]` 会链向不存在的月份；导航只出现在骨架 `时间线.md` 里且只列「已存在的月份」，月节点自身不放 prev/next 链接。

---

## 五、图谱卫生四条判据

| 判据 | 目标 |
|---|---|
| 断链 | 0 |
| 零入链孤岛 | 0 |
| `知识层 → 知识层` 边 | 越多越好（网 vs 辐射的分水岭） |
| `会话 → 索引层` 边 | 越少越好 |

---

## 六、收尾必做

1. 跑 `check.py` 体检，目标断链 0、孤岛 0。
2. `.gitignore` 排除 `90-原始数据/`（含本机路径等隐私）。
3. README 写清四层职责、三维节点、更新命令、隐私提醒、开源口径。
4. **隐私红线**：公开前逐篇检查 `20-对话归档/`；对话全文含敏感信息。

---

## 七、环境注意

- Python 用 managed 版（WorkBuddy）：`~/.workbuddy/binaries/python/versions/3.13.12/python.exe`
- Windows 下脚本开头 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
- 写文件统一 `encoding="utf-8", newline="\n"`
- Obsidian 不索引 `.` 开头目录，项目记忆必须复制进仓库才可见
