# Spec-Centric Function Contract Graph for LLM-Based Mobile GUI Testing

- **Status**: Draft v0.2 (LLM-native)
- **Date**: 2026-11-10
- **Project**: StarTrek
- **Working title**: SpecFCG / FuncCard Graph

---

## 0. 摘要

本文提出一种面向 Android app 的 GUI 测试生成方法：从执行轨迹中归纳**用户级 function contract**（function card），把它们组织成**Function Contract Graph（FCG）**，再用**目标驱动的图遍历**合成测试步骤；执行反馈持续精化卡片和边；当目标不可达时，LLM 预测缺失能力，生成探针，执行验证后补进图里。

核心主张：现有工作要么**有图无 contract**（FuncDroid、GraphDroid、ProphetAgent），要么**有 contract 无图**（PropGen）。本文把两者统一起来，并用 LLM-native 的自然语言表示降低工程复杂度，让图算法负责组合与搜索，LLM 负责语义判断与缺失能力推断。

---

## 1. 背景与问题

移动 app 的 GUI 测试长期依赖人工编写脚本。工业界维护大量自然语言测试用例，但从“文字用例”到“可执行 UI 动作”仍有鸿沟。近年 LLM-based GUI testing 主要沿着三条线发展：

1. **NL 用例 → 可执行测试**：ProphetAgent 用 CUTG 匹配步骤与事件，但只能覆盖已探索场景，且每句必须是单动作。
2. **功能图 + 探索**：FuncDroid 用 FFG（功能节点 + 状态条件流）指导跨功能探索，但节点是行为簇而非可调用 contract，也没有图搜索规划。
3. **属性 / spec 生成**：PropGen 从轨迹归纳 `(P, I, Q)` 属性并做 property-based testing，但属性是单功能 oracle，不可组合。
4. **图 + intent / agent**：GraphDroid 用 UTG + cluster memory 生成覆盖导向 intent；ScenGen / DroidAgent 用多 agent + memory 执行场景/意图，但没有可复用的 function-level 模型。

**空白**：没有一个工作同时具备

- 用户级 function contract（参数、前后置条件、输出、步骤）；
- 可组合的 function graph（enables / dataflow / sequence）；
- 目标驱动的图遍历（不是逐步事件匹配，也不是纯 agent 自由探索）；
- 目标不可达时的缺失能力预测与补全。

本文填补这个空白。

---

## 2. 核心主张与贡献

1. **Function card 作为可组合单元**：每个用户级任务（如 `create_note`、`attach_photo`、`share_note`）用自然语言 contract 描述，带最小结构字段（inputs/outputs/pre/post/steps/evidence）。
2. **Function Contract Graph（FCG）**：节点是 function card，边是 `enables` / `dataflow` / `sequence`（可选 `calls`），边用自然语言描述语义，只用 type tag 支持遍历排序。
3. **Goal-driven graph traversal**：给定自然语言 goal，Planner 在 FCG 上做 BFS/DFS/A\*；LLM 只判断“当前状态能否执行该 function、参数是什么、是否推进 goal”，全局路径搜索由算法完成。
4. **LLM-native graph maintenance**：执行结果直接触发卡片/边的 patch；图随使用变强，而不是一次性构建。
5. **Abductive capability completion**：目标不可达时，LLM 推断缺失能力，生成 probe，执行验证后补图；失败记为 negative capability。

---

## 3. 设计原则（LLM-native）

1. **自然语言是接口**：卡片、状态、边、goal、失败原因都用自然语言。
2. **只保留算法必需的最小结构**，不定义复杂 schema；不做 typed predicate、不做符号求值器。
3. **LLM 做语义判断，算法做图遍历**：LLM 不替代图结构，schema 不限制 LLM 理解。
4. **能合并的模块合并**：Card Miner 与 Graph Updater 都是“LLM 读写图”，合成 Graph Maintainer。
5. **一切以执行证据为准**：LLM 的假设不能直接进图，必须经过执行/重放验证。

---

## 4. 概念与数据模型

### 4.1 Function card（= spec）

一个用户级任务的**自然语言 contract**。一个函数一个 Markdown 文件。

```markdown
# create_note

**Intent**: Create a new note with a title and optional content.
**Inputs**: title (text), content (text, optional)
**Preconditions**: Logged in; on the notes list screen.
**Postconditions**: A note with the given title appears in the notes list.
**Effects/Outputs**: Adds a note to the list; the new note is identified by its title.
**Steps**:
1. Tap "+".
2. Enter the title.
3. Enter the content.
4. Tap "Save".
**Evidence**: traces t1, t2; 2/2 successes.
```

字段最小集：

| 字段 | 作用 |
|---|---|
| `Intent` | 语义检索、LLM 判断 |
| `Inputs` | 参数绑定 |
| `Preconditions` | Planner 判断能否执行 |
| `Postconditions` | 执行后校验、目标判定 |
| `Effects/Outputs` | 数据流边、参数传递 |
| `Steps` | 合成测试步骤 |
| `Evidence` | 路径排序、置信度（成功数/总数 + trace 引用） |

### 4.2 Function Contract Graph（FCG）

有向图 `G = (C, E)`：

- 节点 `c`：function card。
- 边 `e = (from, to, type, description, evidence)`：
  - `enables`：执行 from 后，to 的 preconditions 更可能满足；
  - `dataflow`：from 的 outputs 被 to 的 inputs/preconditions 使用；
  - `sequence`：轨迹中观测到 from 后紧接 to；
  - `calls`（可选）：from 的 steps 内部包含 to；用户级粒度下较少使用。

边的 `description` 是自然语言，例如：

```json
{"from":"create_note","to":"attach_photo","type":"enables",
 "description":"After create_note, the new note exists, so attach_photo can add a photo to it.",
 "evidence":["t1","t3"]}
```

### 4.3 State summary

Executor 每步之后生成的自然语言状态摘要，供 Planner 和 LLM 判断使用：

```markdown
Current screen: Notes list
Visible: search bar, 3 note cards, "+" button
User: logged in as test@example.com
Known entities: note "Shopping list", note "Ideas"
Recent actions: opened app, tapped "+"
```

不做 typed AppState，不做符号状态跟踪。

### 4.4 Goal

自然语言目标，例如：

> Create a note titled "Trip", attach a photo, and share it via email.

可附带可选提示（hints）：期望用到的 function、必须使用的新实体。hints 不是硬约束。

### 4.5 Test plan

```json
{
  "goal": "Create a note titled 'Trip', attach a photo, and share it via email.",
  "path": ["create_note", "attach_photo", "share_note"],
  "bindings": {
    "create_note.title": "Trip",
    "attach_photo.note": "$create_note.output",
    "share_note.channel": "email"
  },
  "steps": [
    "Tap +", "Enter title 'Trip'", "Tap Save",
    "Tap attach", "Choose photo", "Tap share", "Choose email"
  ],
  "assertions": [
    "A note titled 'Trip' exists",
    "The note has a photo attachment",
    "The note was shared via email"
  ]
}
```

### 4.6 Capability gap / negative capability

- **Capability gap**：goal 的某个必要条件无法由现有卡片满足。
- **Missing capability hypothesis**：LLM 提出的候选 function card（尚未入图）。
- **Negative capability**：经过 probe 仍无法实现的能力，记录为负知识，避免重复尝试。

### 4.7 术语与度量定义

- **Card validity**：人工判定卡片的 Intent / Preconditions / Postconditions / Steps 是否正确且可执行。
- **Path recall**：held-out trace 的 function 序列能否在 FCG 中重建为一条路径；按 trace 比例计算。
- **Evidence success rate**：`Evidence` 中成功次数 / 总尝试次数，用于路径排序。
- **Goal relevance**：LLM 对“该 function 是否推进当前 goal”的 0–1 评分。
- **Coverage gain**：路径带来的新增 node/edge 数，按图中总量归一化。

---

## 5. 架构

### 5.1 模块

```text
                 ┌──────────────── new traces ────────────────┐
                 ▼                                            │
[Trace Collector] ──► [Graph Maintainer] ──► [Graph Store] ──► [Planner] ──► [Executor]
                              ▲                                                 │
                              └───────────── execution results ◄───────────────┘
```

| 模块 | 职责 | 关键接口 |
|---|---|---|
| **Trace Collector** | 用 ProphetAgent/Droidbot 执行用例或探索；记录状态、动作、截图、view tree、日志 | `collect(app, policy) -> Trace[]` |
| **Graph Maintainer** | LLM 读轨迹/执行结果，写/改 function card 和边；拆分/合并；处理补全 | `mine(trace) -> CardPatch`；`update(result) -> GraphPatch` |
| **Graph Store** | 存 cards + edges；提供 BFS/DFS/A\*、邻接查询、版本备份 | `load()`, `neighbors(card)`, `search(goal, ...)`, `apply(patch)` |
| **Planner** | goal + state summary → 图搜索 → function 序列 + 参数绑定 + 测试步骤 | `plan(goal, state) -> TestPlan` |
| **Executor** | 把步骤落地成 UI 动作；执行；生成 state summary；校验 postcondition/goal | `execute(plan) -> RunResult` |

### 5.2 数据流

1. Collector 产生 `Trace`。
2. Maintainer 把 Trace 变成 `CardPatch`（新增/更新卡片、边）。
3. Store 应用 patch，更新 FCG。
4. Planner 读 goal + state summary + FCG，产出 `TestPlan`。
5. Executor 执行 `TestPlan`，产出 `RunResult` + 新 Trace。
6. Maintainer 读 `RunResult`，产出 `GraphPatch`；必要时触发 capability completion，回到 1。

### 5.3 目录结构

```text
project/
  cards/                    # 一个 function 一个 .md
  graph/
    edges.jsonl             # 边
    versions/               # 每次 patch 前的备份
  traces/                   # 原始轨迹 + 截图
  runs/                     # TestPlan + RunResult + 日志
  state/                    # 最新 state summary
  completion/
    hypotheses/            # 缺失能力假设
    negative.jsonl         # 失败/负知识
  config/
    llm.yaml
    device.yaml
```

---

## 6. 工作流

### 6.1 Trace collection

- 复用 ProphetAgent 的 GUI Explorer / Droidbot，执行 NL 用例或自主探索。
- 记录最小 trace：

```json
{
  "trace_id": "t1",
  "app": "omninotes",
  "steps": [
    {"before": "Notes list", "action": "click", "target": "+ button",
     "after": "Note editor", "screenshot": "traces/t1/0001.png",
     "view_tree": "traces/t1/0001.xml", "log": "opened editor"}
  ]
}
```

- 后续可导入已有测试脚本的执行轨迹。

### 6.2 Card mining（Graph Maintainer）

输入：一条或多条 trace。

步骤：

1. **切分**：LLM 根据页面变化、动作语义、目标完成信号，把 trace 切成用户级 function episode。
2. **写卡**：每个 episode 生成一张 function card（Intent / Inputs / Pre / Post / Effects / Steps / Evidence）。
3. **合并**：与已有卡片比较；同一 function 则合并 evidence、保留 steps 变体。
4. **拆分**：若一张卡片的 evidence 内部差异大，拆成多张。
5. **校验**：重放步骤；成功才写入图；失败则降低 evidence 或丢弃。

```text
Trace ──► LLM segmentation ──► per-episode card draft ──► merge/split ──► replay ──► GraphPatch
```

### 6.3 Graph building

- 对每对卡片 `(f, g)` 生成候选边：
  - `enables`：LLM 读 `f.Postconditions` 与 `g.Preconditions`，判断是否满足/可能满足；
  - `dataflow`：LLM 读 `f.Effects/Outputs` 与 `g.Inputs`，判断是否有数据依赖；
  - `sequence`：trace 中相邻出现；
  - `calls`（可选）：`f.Steps` 包含 `g.Steps`。
- 边写入 `edges.jsonl`，带 `description` 和 `evidence`。
- 无证据的边不入图；`sequence` 边可作为低优先级先验。
- 定期人工抽检边的 precision。

### 6.4 Planning

1. **候选召回**：默认用 embedding 粗筛出 top-N 卡片，再由 LLM 确认与 goal 相关的子集；卡片数量少时可直接全量交给 LLM。
2. **图搜索**：BFS/DFS/A\*。每扩展一个候选 `f`，LLM 读 `state summary + f.card`，回答：
   - 现在能执行吗？（preconditions 是否满足）
   - 参数填什么？
   - 执行后能推进 goal，或能解锁后续 function 的 preconditions 吗？
   只有“能执行且（推进 goal 或解锁后续能力）”才扩展。
3. **路径排序**：按 evidence 成功率、路径长度、LLM 评分排序；取 top-k。
4. **参数绑定**：优先用 goal 中的值；其次用前序卡片的 `Effects/Outputs`；再次用 state summary 中的实体；最后 LLM 生成合理值。
5. **步骤合成**：把路径上各卡片的 `Steps` 按参数拼接；必要时让 LLM 做平滑/补充。
6. **无路径**：触发 capability completion。
7. **输出**：`TestPlan`（JSON）+ 可执行步骤。

### 6.5 Execution

- 复用 ProphetAgent 的 CUTG/事件匹配与 uiautomator2 执行。
- 每步之后：
  - 生成新的 state summary；
  - 记录实际动作、截图、日志；
  - 若控件找不到，尝试 CUTG 匹配/回滚，或触发重新规划。
- 每个 function 之后：LLM 读 state summary + card.Postconditions，判断是否满足。
- 整条路径之后：LLM 读 goal + state summary，判断 goal 是否达成。
- 产出 `RunResult` + 新 trace。

### 6.6 Graph maintenance

Maintainer 读 `RunResult` + 当前图，输出最小 patch：

```json
{
  "card_updates": [
    {"name": "create_note", "fields": {
      "Preconditions": "Logged in; on the notes list screen.",
      "Evidence": "3/4 successes"
    }}
  ],
  "new_cards": [
    {"name": "attach_photo", "card": "cards/attach_photo.md"}
  ],
  "edge_updates": [
    {"from": "create_note", "to": "attach_photo", "type": "dataflow",
     "action": "add", "description": "attach_photo uses the note created by create_note.", "evidence": ["t5"]}
  ],
  "split": [],
  "merge": [],
  "reason": "attach_photo was observed and is required by the goal"
}
```

- 应用 patch 前备份 `graph/versions/<timestamp>/`。
- 如果 patch 后关键指标（pass rate / coverage）下降，恢复上一版。
- 失败分类：
  - precondition mismatch → 修 `Preconditions`；
  - widget/grounding failure → 增加 steps 变体；
  - trace failure → 补 guard/分支；
  - postcondition failure → 先怀疑 spec，再怀疑 bug；
  - goal failure → 触发补全；
  - environment failure → 记录，不改图。

### 6.7 Capability completion

**触发**：Planner 无路径，或唯一路径被不可满足的 precondition 卡住。

**分工**：Planner 负责检测无路径并触发；Graph Maintainer 负责生成假设、归纳卡片、写图；Executor/Trace Collector 负责执行 probe。

**流程**：

```text
no path / blocked
   │
   ▼
LLM reads goal + cards + state
   │
   ▼
propose top-k missing capabilities
   { name, intent, pre, post, inputs, probe }
   │
   ▼
execute probe (default: ProphetAgent/Droidbot explorer with the NL probe as goal; fallback: LLM agent)
   │
   ├─ success → induce card from probe trace → replay → add card + edges → re-plan
   │
   └─ failure → record negative capability → next hypothesis
```

**护栏**：

- 每个 goal 最多 5 个假设、每个假设最多 3 次 probe；最多 2 轮补全。
- 只有执行证据能新增卡片；LLM 的假设不能直接入图。
- 失败的假设写入 `completion/negative.jsonl`，包含 goal、缺失能力、probe、失败原因。
- 补全后重新规划；若仍不可达，停止并报告。

### 6.8 Multi-round loop

每轮：`plan → execute → maintain → (completion)`。

记录：图规模、node/edge/path 覆盖、pass rate、bug 数、LLM 成本。

停止条件：

- 目标 goal 集合全部通过；
- 覆盖准则达标；
- 预算耗尽；
- 最近一轮无新增卡片/边，且覆盖率增益 < 2%。

评测固定轮数（如 5 轮），并保留 held-out goals。

---

## 7. 图算法与覆盖准则

### 7.1 搜索

- **BFS**：最短路径、节点覆盖。
- **DFS**：深度组合、路径覆盖。
- **A\***：goal 导向；代价 = 预计步数 + LLM 调用成本 + `(1 - evidence_success_rate)`；启发式 = 到目标相关卡片的图距离 + 未满足条件数。
- **Beam search**：状态/分支过多时保留 top-k。

LLM 只提供局部转移判断（能否执行、参数、是否推进），不负责全局枚举。

### 7.2 覆盖准则（NL 版本）

| 准则 | 定义 | 用途 |
|---|---|---|
| Node coverage | 每张卡片至少执行一次 | 功能覆盖 |
| Edge coverage | 每条边至少穿越一次 | 组合覆盖 |
| Path coverage | 入口到目标的简单路径（长度 ≤ k）至少各执行一次 | 跨功能流程 |
| Input-output coverage | 每张卡片的 outputs 至少被另一张卡片消费一次 | 数据流代理 |
| Precondition-boundary coverage | 每张卡片的 pre 在 true / false / 边界下各执行一次 | 负向/鲁棒性测试 |

这些指标同时用于测试生成目标和实验评测。

### 7.3 路径排序

`score = w1 * evidence_success_rate + w2 * goal_relevance + w3 * coverage_gain - w4 * path_length - w5 * cost`

权重先用人工设定，后续可用小规模调参；不需要学习模型。

---

## 8. 评测

### 8.1 Research Questions

- **RQ1（Card 质量）**：轨迹 → function card 的 validity、可执行性、pre/post 准确性如何？
- **RQ2（Graph 质量）**：边 precision/recall、held-out path recall 如何？
- **RQ3（Planning 有效性）**：goal-driven 图遍历是否优于逐步匹配/agent baseline？完成率、动作准确率、成本如何？
- **RQ4（覆盖与 bug）**：node/edge/path/input-output 覆盖是否 correlate 并提升 bug 发现？
- **RQ5（Capability completion）**：补全是否发现 baseline 发现不了的新功能/新场景/新 bug？
- **RQ6（消融与成本）**：各组件贡献、LLM/时间成本。

### 8.2 Benchmarks

**Stage 1（8 周 MVP）**

- 6 个开源 app：AnkiDroid、AmazeFileManager、OmniNotes、NewPipe、ActivityDiary、AntennaPod。
- 60 条 NL 用例（10/app，来自 ProphetAgent）。
- 30 个组合目标（5/app，自建；人工写 oracle）。
- held-out traces 用于 path recall。

**Stage 2**

- Themis 50 apps / 50 crash bugs（FuncDroid / DroidAgent benchmark）。
- ScenGen 的 92 apps / 99 tasks。
- 10–20 个商业 app（Google Play / 华为应用市场）。
- 组合目标 benchmark 扩展到 50–100 个。

### 8.3 Baselines

| 类型 | 工具 |
|---|---|
| NL → 测试 | ProphetAgent（同 backbone 直接对比） |
| 功能图 + 探索 | FuncDroid |
| 属性 / spec | PropGen |
| 图 + intent | GraphDroid |
| 场景 agent | ScenGen |
| 自主 intent agent | DroidAgent |
| 传统 / 其他 | GPTDroid、VisionDroid、AppAgent、AutoDroid、Droidbot/Fastbot（可选） |

公平性：同一 LLM、同一时间预算（如 60 min/app）、同一模拟器、3 次运行取中位数/均值；记录 token/$。

### 8.4 Metrics

- **Card**：validity（人工）、executability、pre/post precision/recall。
- **Graph**：node/edge precision/recall（人工标注子集）、path recall（held-out traces）。
- **Planning**：goal completion、action accuracy、steps/time/tokens per goal、unseen-goal completion。
- **Coverage**：node/edge/path/input-output coverage；activity/code coverage 用于与 baseline 对齐。
- **Bugs**：crash / non-crash、unique bugs、false positives（人工确认）、new capabilities discovered。
- **Cost**：LLM calls/tokens/$ per app/test。

### 8.5 Ablations

1. **Pure LLM agent**：无图，LLM 自由规划（近似 DroidAgent）。
2. **CUTG-only**：页面/事件图，无 function card（近似 ProphetAgent）。
3. **Cards-only**：有卡片，无边，Planner 只能顺序尝试。
4. **Graph-but-no-planner**：有图，但 LLM 自由选 function，不做图搜索。
5. **Full v0.2**。
6. **No maintainer**：图只构建一次，不精化。
7. **No completion**：不做缺失能力补全。

### 8.6 Threats to Validity

- **LLM 泄漏**：开源/held-out app；检查发布日与训练截止时间；多模型复现。
- **Oracle 有效性**：人工复核 postcondition 和 bug；LLM oracle 与日志/crash 交叉验证。
- **Benchmark 偏差**：多 benchmark、多类别 app。
- **可复现性**：temperature 0、固定 seed、缓存 LLM 响应、公开卡片/图/脚本/traces。
- **公平性**：同 LLM/预算；重跑 baseline；报告方差。
- **人工标注偏差**：双人独立标注，计算 Cohen's κ，分歧讨论达成一致。

---

## 9. 里程碑与阶段门

| 周 | 交付 | 阶段门 |
|---|---|---|
| W1–2 | 环境 + 复现 ProphetAgent + 采集 60 条轨迹 | baseline 数字可复现 |
| W3–4 | Graph Maintainer（card mining）+ Store | 50 张卡人工抽检 validity ≥ 80% |
| W5–6 | Planner + Executor | held-out path recall ≥ 70%；已知用例 completion ≥ 70%；30 个组合目标 completion ≥ 50%，且比 ProphetAgent 高 ≥ 20 个点 |
| W7–8 | 精化 + 补全 v0 | 多轮迭代有增益；≥ 3 个新能力/新 bug；决定是否进入 Stage 2 |
| W9–16 | 全量 benchmark + baseline + 消融 + 写作 | 投稿 |

**Gate 1 失败** → 简化卡片字段或改轨迹切分。\
**Gate 2 失败** → 聚焦图规划，砍掉 completion。\
**Gate 3 失败** → completion 作为负结果/未来工作，论文主张改为 card + planning。

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 判断不稳定 | 规划/校验波动 | temperature 0；多次运行；缓存；多模型复核 |
| 卡片质量差 | 图和规划都不可靠 | 重放校验；人工抽检；证据阈值；失败回滚 |
| 组合落地失败 | 数据/状态传递断裂 | 强化 `Effects/Outputs`；LLM 参数绑定；执行后重规划 |
| 图爆炸 | 搜索慢、成本高 | 证据剪枝；路径长度限制；beam search；只保留相关子图 |
| 补全幻觉 | 假功能入图 | 只有执行证据能入图；negative capability；预算上限 |
| Baseline 不公平 | 结果不可信 | 同 LLM/预算/设备；重跑；报告方差 |
| 训练数据泄漏 | 高估效果 | 开源/held-out app；检查截止时间；多模型 |
| Scope creep | 8 周做不完 | 阶段门；YAGNI；先做 Stage 1 |

---

## 11. 非目标

- 不提供形式化验证或完备性保证。
- 不构建 Android 静态方法调用图；本文的“function”是用户级任务。
- 不覆盖所有 app 类别；MVP 以 6 个开源 app 为主。
- MVP 不部署真机农场；先在 emulator 上验证。
- 不替代人工 oracle；LLM oracle 需要人工抽检。

---

## 12. 与 v0.1 的差异

| 环节 | v0.1（已废弃） | v0.2（本设计） |
|---|---|---|
| Spec | JSON DSL + typed predicates | Markdown function card |
| State | typed AppState + 符号求值 | 自然语言 state summary |
| 边 | 4 类型 + condition + confidence 公式 | type tag + NL description + evidence |
| Planner | A\* + 符号状态模拟 + cost model | BFS/DFS/A\* + LLM 局部判断 |
| 参数 | dataflow 绑定图 + 拓扑赋值 | LLM 从 goal/state/outputs 绑定 |
| 精化 | GraphDelta + rollback | LLM patch + 文件版本备份 |
| 补全 | 5 阶段 pipeline | Planner fallback + probe |
| 模块数 | 8 | 5 |

v0.2 的代价是形式严谨性下降，因此评测必须保留“纯 agent”“CUTG-only”“cards-only”等 ablation，证明图与 contract 的增益不是 LLM 自身能力带来的。

---

## 13. 参考文献

1. **ProphetAgent**: Qichao Kong et al. "ProphetAgent: Automatically Synthesizing GUI Tests from Test Cases in Natural Language for Mobile Apps." FSE 2025 Companion. [PDF](https://tingsu.github.io/files/fse2025-ProphetAgent.pdf) · [Code](https://github.com/ProphetAgent/Home)
2. **FuncDroid**: Jinlong He et al. "FuncDroid: Towards Inter-Functional Flows for Comprehensive Mobile App GUI Testing." ISSTA 2026. [arXiv](https://arxiv.org/abs/2602.12834) · [Code](https://github.com/SQUARE-RG/FuncDroid)
3. **ScenGen**: Shengcheng Yu et al. "LLM-Guided Scenario-based GUI Testing." TOSEM 2025. [arXiv](https://arxiv.org/abs/2506.05079) · [Code](https://github.com/iGUITest/ScenGen)
4. **DroidAgent**: Juyeon Yoon, Robert Feldt, Shin Yoo. "Autonomous Large Language Model Agents Enabling Intent-Driven Mobile GUI Testing." arXiv 2023. [arXiv](https://arxiv.org/abs/2311.08649) · [Code](https://github.com/coinse/droidagent)
5. **PropGen**: Yiheng Xiong et al. "PropGen: Automated Property Generation for Property-Based Testing of Mobile Apps." ASE 2026. [arXiv](https://arxiv.org/abs/2604.13463)
6. **GraphDroid**: Xiaolei Li et al. "GraphDroid: Asynchronous LLM-Based Mobile App GUI Testing via History-Aware Exploration and Hybrid Intent Fulfillment." ISSTA 2026. [arXiv](https://arxiv.org/abs/2609.10031)
7. **GAPS**: "GAPS: Guiding Dynamic Android Analysis with Static Path Synthesis." arXiv 2025. [arXiv](https://arxiv.org/abs/2511.23213)
8. **GPT-Monkey**: "GPT-Monkey: Enhancing Automated GUI Testing for Android Apps via LLM-Driven Interface Understanding and Function Segmentation." IET Software 2026. [DOI](https://doi.org/10.1049/sfw2/9976714)
