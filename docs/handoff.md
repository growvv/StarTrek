# 交接文档 — SpecFCG / StarTrek

> 面向接手开发的工程师。最后更新：2026-11-18。
>
> 建议阅读顺序：本文 → [设计文档](superpowers/specs/2026-11-10-spec-fcg-mobile-gui-testing-design.md)
> → [实施计划](superpowers/plans/2026-11-10-specfcg-mvp.md) 的 **Next Round** 一节
> → [公开实验报告](reports/mobileworld.html)。

## 1. 一句话状态

MVP（计划 Task 1–17）已实现并在真机上验证，当前 **448 个测试通过**
（CI 覆盖 Python 3.10 / 3.12）。四个 app 各建了一张 Function Contract
Graph，`runs/mobileworld/score-history.json` 记录了 7 次迭代的分数，最新
综合 **71.7**。

代码**尚未**进入下一轮架构调整，计划已写好并提交（`5da1862`），下一步是
Task F。README 里“卡片含 Steps / 编译成动作”描述的是**旧架构**，正是
Next Round 要删除的部分，不要把它当最终形态。

## 2. 现在系统怎么工作（as built）

一次完整链路：

```
轨迹采集 (traces/) → 卡片归纳 (maintainer/miner) → 建边 (maintainer/builder)
    → 图存储 (graph/store) → 规划 (planner: retrieval + binding + A* + compiler)
    → 执行 (executor: 真机 + LLM 状态判断) → 失败修补 (maintainer/updater)
    → 能力补全 (completion: 预测缺失能力 + 设备探针)
```

| 模块 | 职责 | 关键文件 |
|---|---|---|
| `specfcg/traces/` | 脚本化轨迹采集、解析、ProphetAgent 适配 | `collector.py`, `scripted.py`, `recorder.py` |
| `specfcg/cards/` | function card 的 Markdown 解析与落盘 | `parser.py`, `store.py` |
| `specfcg/maintainer/` | LLM 归纳卡片、建边、失败后修补图 | `miner.py`, `builder.py`, `updater.py` |
| `specfcg/graph/` | 图存储、BFS/DFS/A* 搜索 | `store.py`, `search.py` |
| `specfcg/planner/` | 卡片检索、参数绑定、路径规划、动作编译 | `retrieval.py`, `binding.py`, `planner.py`, `compiler.py` |
| `specfcg/executor/` | 设备抽象、状态摘要、执行计划 | `device.py`, `summarizer.py`, `executor.py` |
| `specfcg/completion/` | 缺失能力预测与探针验证 | `completer.py`, `probe.py` |
| `specfcg/benchmark/` | 任务套件、agent、oracle、分数卡、报告 | `suite_runner.py`, `agents.py`, `scorecard.py` |
| `mobile_agent/` | 仓库内的 GUI agent（截图优先的 VLM 工具调用） | `agent.py`, `device.py`, `prompts.py` |
| `scripts/` | 采集、建图、跑批、记录分数、生成报告与站点 | 见第 5 节 |

数据模型（当前）：`FunctionCard` 含
`intent / inputs / preconditions / postconditions / effects_outputs /
steps / evidence`；`TestPlan` 含卡片路径与编译出的 `steps`；边类型为
`enables / dataflow / sequence / calls`。

## 3. 下一轮的目标架构（尚未实现）

核心修正：**图是用来描述 app 的功能、指导下一次任务生成的，不是用来回放
上一次的具体动作的。**

- 卡片变成**契约**：有意图、输入、前后置条件、产出、证据，**没有 UI 动作**；
- Planner 输出 **TaskPlan.description**：把路径上的契约串成整体 goal + 有序
  subgoals 的结构化文本，由确定性的 `TaskDescriber` 渲染（不用 LLM）；
- Executor 把这段描述交给 **GUI agent** 执行；没有任何录制动作被回放；
- 验证方式：同一个 agent、同一台设备、同一批任务，原始 goal（对照）vs
  图生成的任务描述（处理），统计配对差异。

执行顺序与字母映射（详见计划 `## Next Round`）：

| 顺序 | 任务 | 做什么 | 依赖 / 判据 |
|---|---|---|---|
| 1 | **F** | 卡片去步骤；`TestPlan` 改 `description`；删 compiler / `PlanStep` / `execute_plan` / `DeviceProbe` / granularity；新增 `GuiAgent` + `MobileAgentBackend`；重写 Executor；agent 不再自己启动 app | 一个 commit；迁移 93 张旧卡片；真机 smoke |
| 2 | **G** | 探针与能力补全走 agent 端到端（completer 传 package、CLI 接 `AgentProbe`、`run_probes` 走 executor） | F |
| 3 | **H** | 消融：`GraphAgent` vs `RawGoalAgent`，程序化 oracle 判成功；分数卡的 `task` 读 graph 臂，`raw` 只作对照 | F |
| 4 | **C** | 重复功能检测改为从契约读（与语义建边同一次调用），只报告、不评分、不自动合并 | F |
| 5 | **A** | 用当前 builder 从已有轨迹重建四个图 | C |
| 6 | **B** | 重测设备维度：random 遍历、探针、两臂 bench；`record_score.py --label agent-execution` | A |
| 7 | **D** | 标定改为对 agent 运行结果；若 B1 的预测置信度仍是常数，先修估计器 | B（有条件） |
| 8 | **E** | 勾掉计划步骤、记录命令与结果 | 以上每步 |

注意：Task F 之后 `task` 维度含义改变（从“编译脚本回放成功”变成“agent
按图描述达成目标”），分数曲线在此处**不连续**，报告要明确画断点，不能
连成一条线。

## 4. 环境搭建

- Python 3.10+（开发机为 3.12.6）。
- 安装：`pip install -e ".[dev,device]"`（`device` extra 提供
  uiautomator2）。
- 一台连着 `adb` 的 Android 设备（开发机是 Pixel 9 Pro XL，Android 16，
  1008×2244），以及一个 OpenAI 兼容网关。
- LLM 配置：
  - `config/llm.yaml`（**gitignored**，本机主配置，scripts 的默认 `--config`）：
    模型 `auto/hy4free`，网关 `http://127.0.0.1:3425/v1`，key 由环境变量
    `OPENAI_API_KEY` 提供；设备序列号也在这里。
  - `config/llm.bench.yaml`（**入库**）：benchmark 专用模型
    `auto/deepseek-v4.1-flash`，缓存 `.cache/llm-bench`，保证实验记录能对上是
    哪个模型产出的。
  - 模板：`config/llm.example.yaml`。
- Windows 注意：
  - 脚本一般需要 `PYTHONPATH=.`；
  - 通过 Git Bash 调 `adb shell` 带设备内路径时加 `MSYS_NO_PATHCONV=1`。

## 5. 常用命令

```bash
# 测试（无设备）
python -m pytest -q                      # 448 passed

# 无设备的端到端冒烟
python -m specfcg.cli plan --config config/llm.yaml --fake-llm --fake-device \
    --goal "Create a note titled Trip"

# 重建一个 app 的图（--skip-collect 用磁盘上已有轨迹）
PYTHONPATH=. python scripts/build_app_graph.py --app omninotes --skip-collect \
    --config config/llm.bench.yaml

# 建图 + 测量（random 遍历与探针）
PYTHONPATH=. python scripts/run_graph_experiments.py --app omninotes \
    --serial <serial> --config config/llm.bench.yaml

# 跑 benchmark 的一个 app（当前是 specfcg / random）
PYTHONPATH=. python scripts/run_mobileworld_bench.py --app omninotes \
    --config config/llm.bench.yaml --agent specfcg

# 把磁盘上的实验记录算成一个分数点
python scripts/record_score.py --label <label>

# 重新生成报告
python scripts/build_bench_report.py
```

四个 app 的 suite 定义在 `benchmark/mobileworld/suite.yaml`：4 apps × 5
tasks，20 步上限，程序化 oracle（只看执行结束后的 UI/窗口/文件状态）。

## 6. 数据与产物（哪些入库、哪些不在）

| 路径 | 是否入库 | 说明 |
|---|---|---|
| `runs/` | 否 | 图、轨迹、实验记录、`score-history.json`；交接时需连同本机目录一起交接，或按第 5 节重采 |
| `docs/evidence/` | 是 | `runs/` 中关键结果的公开副本（卡片、边、journal、真机截图） |
| `docs/reports/` | 是 | 生成的 HTML 报告（含分数曲线、每 app 维度） |
| `docs/assets/`、`docs/demo/`、`docs/graph/` | 是 | GitHub Pages 站点素材 |
| `.cache/` | 否 | LLM 回复缓存（`.cache/llm`、`.cache/llm-bench`） |
| `config/llm.yaml` | 否 | 本机网关与设备序列号 |
| `.tmp/` | 否 | 开发期临时截图/日志，约 515 MB，如无需保留可删除 |
| `papers/`、`third_party/`、各 venv | 否 | 依赖与本地产物 |

## 7. 当前测量状态与限制

`runs/mobileworld/score-history.json` 的 7 个点（四维等权，随机遍历作对照
不计入分数）：

| # | label | graph | calibration | selfopt | task | overall | random |
|---|---|---|---|---|---|---|---|
| 0 | baseline | 100.0 | 84.0 | 7.8 | 30.0 | 55.5 | 41.1 |
| 1 | parser-and-row-scope | 100.0 | 84.0 | 7.8 | 70.0 | 65.5 | 41.1 |
| 2 | scroll-and-generality | 100.0 | 84.0 | 7.8 | 75.0 | 66.7 | 41.1 |
| 3 | selfopt-fresh-launch | 100.0 | 84.0 | 18.2 | 75.0 | 69.3 | 41.1 |
| 4 | ime-and-shared-ids | 100.0 | 84.0 | 18.2 | 85.0 | 71.8 | 41.1 |
| 5 | coverage-and-selfopt-honesty | 100.0 | 84.0 | 18.2 | 100.0 | 75.5 | 41.1 |
| 6 | honest-graph-coverage | 84.5 | 84.0 | 18.2 | 100.0 | 71.7 | 41.1 |

限制，报告里必须原样保留：

- 只有 4 apps × 5 tasks，**20 个任务不足以做显著性结论**；
- 标定维度是 bias-only，常数预测也能拿到基率（Task D 要处理）；
- 图完整度已剔除 inventory 的 `cards:` 答案键，84.5 是诚实值；
- omninotes 的 193 条边里有 157 条是 LLM 断言、没有执行证据的 `enables`；
- 到 2026-11-18 为止，图中没有任何 `calls` 边（F 会移除该类型）。

## 8. 开发约定

- **TDD**：先写失败测试，再实现；计划里每一步都有可验证结果。
- **计划即规格**：改动前先看 `docs/superpowers/plans/2026-11-10-specfcg-mvp.md`
  的对应任务；完成一步就勾掉并记录命令与结果（Task E 的要求）。
- **不许打补丁/兜底**：要改就改设计本身，保证可泛化；不引入只为当前
  case 服务的分支、别名或 fallback。
- **指标必须真的在测量**（见 `docs/reports/mobileworld.html` 的措辞）：
  - 空记录（没测到东西）不能算分；
  - 分子分母必须来自同一集合；
  - 不能用由被测对象产出的“答案键”当判据；
  - 常数估计只能拿基率，不能伪装成有区分度的标定。
- **报告要有证据**：HTML 报告附截图、逐步记录、模型输入输出。
- 不提交 `runs/`、缓存、密钥、`.tmp/`；公开副本放 `docs/evidence/`。

## 9. 已知坑

1. `mobile_agent.run()` 目前会自己 `start_app()`（`app_start(..., stop=True)`
   + onboarding 点击），会清掉 benchmark 准备好的状态。Task F 删除这段，
   启动 app 交给调用方（`prepare_state` / `fresh_app` / 脚本）。
2. 解析器当前把 `Steps` 当必填段落；Task F 后旧卡片必须先用
   `scripts/migrate_cards.py` 迁移，解析器会显式拒绝 `**Steps**`（抛
   `CardParseError`），不会静默吞掉。
3. `granularity.py` / `scripts/measure_granularity.py` 依赖编译后的动作集，
   Task F 会删除，由 C 的契约级重复检测替代。
4. 网关模型名（`auto/hy4free`、`auto/deepseek-v4.1-flash`）是本地网关的
   路由名，换环境要同步改配置。
5. `runs/` 不入库：新机器 clone 后没有图。要么连同本机 `runs/` 一起交接，
   要么按 `scripts/build_app_graph.py`（不带 `--skip-collect`）重新采集
   （需要设备）。
6. 探针/标定的“实际值”与预测必须指向同一件事；Task D 之前不要用旧的
   calibration 数字下结论。

## 10. 交接清单

- [x] MVP 代码与测试（448 passed）
- [x] 设计文档、实施计划、Next Round 路线图（commit `5da1862`）
- [x] 公开报告、证据副本、Pages 站点
- [x] 本交接文档
- [ ] Task F → G → H → C → A → B → D → E（见计划）
- [ ] 设备、网关、`OPENAI_API_KEY`、`config/llm.yaml` 访问权限移交
