# SpecFCG

**Function Contract Graph for LLM-based mobile GUI testing.**

从真实执行轨迹里归纳用户级 *function card*（意图、参数、前后置条件、步骤、证据），
组织成可组合的 **Function Contract Graph**，用目标驱动的图遍历合成可执行测试；
执行失败再反过来修补卡片与边。

> 项目主页 / 交互演示：<https://growvv.github.io/StarTrek/>

---

## 为什么

工业界维护大量自然语言测试用例，但把它们变成可执行的 UI 动作仍然靠人。现有 LLM GUI agent 有两条路，各缺一半：

| 现状 | 缺什么 |
|---|---|
| FuncDroid / GraphDroid / ProphetAgent 建功能图 | 节点是行为簇或事件，不是带参数与前后置条件的可调用单元，无法组合出新目标 |
| PropGen 从轨迹归纳 `(P, I, Q)` 属性 | 属性是单功能 oracle，不能拼成多步流程，也判断不了“执行 A 之后 B 是否可执行” |
| 直接让 agent 从目标出发 | 路径依赖当次模型状态，不可复现；失败后无法定位是卡片错、边错还是 UI 变了 |

SpecFCG 把两者统一：**卡片是契约，图负责组合，LLM 只做语义判断**。

## 核心设计

1. **Function card 作为可组合单元** — 一张卡片声明
   `Intent / Inputs / Preconditions / Postconditions / Effects-Outputs / Steps / Evidence`，
   用自然语言写，落盘为 Markdown。步骤是“做什么”，不是写死的坐标。
2. **Function Contract Graph** — 节点是卡片，边是
   `enables`（前置条件被满足）/ `dataflow`（参数供给）/ `sequence`（真实轨迹中相邻）。
   边只用于授权执行，`dataflow` 不单独放行路径。
3. **目标驱动图遍历** — 给定自然语言 goal，Planner 在图上搜索可达路径，再让 LLM 判断
   “当前状态能否执行该卡”“这条路径是否真的达成目标”。搜索是确定性的，判断是语义的。
4. **参数绑定** — goal 里的 “titled Groceries with content Buy milk” 绑定到卡片的
   `note_title` / `note_content`；未绑定的必填参数才触发一次 LLM 补全，绑定结果随计划落盘。
5. **失败驱动修补** — 执行失败先归因（postcondition / 定位 / 前置条件 / 参数），
   再决定改卡片、改边还是加卡；修补记录与改前卡片都保留，可复查。

## 快速开始

需要 Python 3.10+、一台连着 `adb` 的 Android 设备，以及任意 OpenAI 兼容网关。

```bash
pip install -e ".[dev,device]"
cp config/llm.example.yaml config/llm.local.yaml   # 填 base_url / api_key_env / device.serial

# 1. 采集一条真实轨迹（也可以直接用手写的 actions JSON）
python scripts/collect_trace.py --app it.feio.android.omninotes.foss \
    --actions examples/actions_create_note.json --trace-id create-note-1 \
    --out traces/create-note-1.json

# 2. 归纳卡片，再把卡片连成图
python -m specfcg.cli mine --config config/llm.local.yaml --trace traces/create-note-1.json
python -m specfcg.cli build-graph --config config/llm.local.yaml

# 3. 规划：目标 -> 卡片路径 -> 绑定参数 -> 编译成动作
python -m specfcg.cli plan --config config/llm.local.yaml --goal "Create a note titled Trip"

# 4. 在真机上执行；失败就修图再跑
python -m specfcg.cli run --config config/llm.local.yaml --max-rounds 2 \
    --goal "Create a note titled Groceries with content Buy milk, then share it"
```

没有设备也能跑：

```bash
python -m pytest -q                                     # 200 passed
python -m specfcg.cli plan --config config/llm.local.yaml \
    --fake-llm --fake-device --goal "Create a note titled Trip"
```

## 结果（真机）

设备：Pixel 9 Pro XL，Android 16，1008×2244。App：OmniNotes 6.5.1 FOSS。
成功判定 = 每张卡片 postcondition 满足 + 整条路径 goal 达成，只看执行后可观察的 UI。

| 用例 | 卡片路径 | 步数 | 动作成功 | 结果 |
|---|---|---|---|---|
| create + archive | `create_note → archive_note` | 9 | 9/9 | PASS |
| create + share | `create_note → open_note_by_title → invoke_share_chooser_for_note` | 8 | 8/8 | PASS |
| create + search + open + share | `create_note → search_notes_by_keyword → open_note_by_title → invoke_share_chooser_for_note` | 11 | 11/11 | PASS |

第 1 次跑 create + archive 是 **FAIL**（`postcondition_failure`：编辑器没退出，列表里看不到新笔记）。
LLM 判定最小修补是改 `create_note` 本身——Intent 要求保存并回到列表，Steps 写成“按需重复 Back 直到列表出现”——
第 2 次跑通过。原始记录在 [`docs/evidence/`](docs/evidence/)。

## 仓库结构

```
specfcg/
  traces/       轨迹采集与解析（含 ProphetAgent 输出适配）
  cards/        function card 解析与存储
  maintainer/   LLM 归纳卡片、建图、修补
  graph/        图存储与搜索
  planner/      参数绑定、动作编译、规划
  executor/     设备控制、状态摘要、执行
  completion/   缺失能力预测与探针
  benchmark/    用例、目标、指标
scripts/        采集、跑批、报告与站点生成脚本
docs/
  index.html    GitHub Pages 主页
  demo/         交互演示（10 步真实截图）
  evidence/     页面引用的原始结果（runs/ 不入库，这里是对外副本）
  reports/      实验报告
  experiments/  真机实验记录
  superpowers/  设计文档与实施计划
```

## 文档

- [设计文档](docs/superpowers/specs/2026-11-10-spec-fcg-mobile-gui-testing-design.md)
- [真机实验记录（F1–F26）](docs/experiments/2026-11-10-real-device-pilot.md)
- [AgentProg 复现与讲解](https://growvv.github.io/StarTrek/reports/agentprog-explained.html)（页面在 Pages 上可直接看）
- [交互演示](https://growvv.github.io/StarTrek/demo/)

## 引用

```bibtex
@misc{specfcg2026,
  title  = {SpecFCG: Spec-Centric Function Contract Graph for LLM-Based Mobile GUI Testing},
  author = {StarTrek project},
  year   = {2026},
  url    = {https://github.com/growvv/StarTrek}
}
```
