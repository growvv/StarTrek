# SpecFCG 真机 / 真 LLM 实验日志（2026-11-10）

## 环境

- 设备：Pixel 9 Pro XL，Android 16，arm64-v8a，serial `47261FDAS00DTQ`
- 设备桥：`uiautomator2`（直连 adb，无需 Java）
- LLM 网关：本机 magpie `http://127.0.0.1:3425/v1`，Bearer `magpie`
- 模型：`auto/hy4free`（HY4 Free；推理型，短 `max_tokens` 会被推理 token 吃光）
- 首批 app：OmniNotes FOSS 6.5.1（`it.feio.android.omninotes.foss`）、ActivityDiary 1.4.2

## 已完成的第一条真实链路

1. 在真机上脚本化采集 `create_note` trace：
   FAB → 文本注释 → 输入标题 → 输入内容 → Back（键盘）→ Back（返回列表）。
   trace 文件：`runs/real/omninotes-create-note-2.json`。
2. `specfcg mine` 用 HY4 生成 function card。
3. `specfcg build-graph` 建图。
4. `specfcg plan` 规划新目标
   `create a note titled Groceries with content Buy milk`。
5. `specfcg execute` 在真机执行。
6. `specfcg refine` 对 postcondition failure 做失败驱动修补（进行中）。

## 真实反馈与已做修改

| # | 观察 | 修改 | 验证 |
|---|---|---|---|
| F1 | HY4 是推理模型，`max_tokens=16` 时 `content=null` | 实验调用统一给足输出预算 | 直接调用返回 `OK` |
| F2 | 原始 UI dump 14KB，含桌面/状态栏，目标 app 节点被挤出截断窗口 | 新增 `compact_ui()`，只保留目标包的可操作/有文本节点；`Uiautomator2Device.dump_ui()` 自动使用 | `tests/test_ui_compact.py` |
| F3 | HY4 卡片用独立一行的 `**Intent**`（无冒号），旧解析器直接判非法并回退 | 章节标题冒号可选 | `test_parse_card_accepts_section_headings_without_colon` |
| F4 | HY4 的 Inputs 是 Markdown bullet，旧解析按逗号切碎，binder 读出 `-`、`selected` 等伪参数 | 新增 bullet-aware `_parse_inputs()`；`_param_name()` 去反引号/取首个标识符 | `test_parse_card_accepts_bullet_inputs_with_backticks`、`test_param_name_strips_markdown_and_description` |
| F5 | HY4 卡片把 trace 里的 `Meeting`/`Discuss roadmap` 写死 | 卡片 prompt 要求把具体值泛化为 `{name}` inputs；Evidence 固定格式 | 新卡片变成 `note_title`/`note_content`，步骤含 `{note_title}` |
| F6 | 显式 resource id 的卡片仍要等 LLM 编译，单次 4+ 分钟 | `StepCompiler` 增加显式目标快速路径：能从步骤解析 `resourceId=`/`text=`/`desc=` 时不调 LLM，否则回退 | `test_compile_uses_explicit_targets_without_calling_llm`；带缓存 plan 0.15s |
| F7 | 真机执行 5/5 动作成功，但只按一次 Back 只关闭键盘，仍停在编辑器；postcondition 准确判失败 | 卡片 prompt 要求“一个物理动作一步”，例如 trace 中两次 Back 必须写两步，不能写 “repeat as needed” | prompt 已改，待重采验证 |
| F8 | 失败补丁 prompt 只有卡片名/失败类型，没有卡片步骤和实际执行动作，模型看不到“只按了一次 Back” | 补丁 prompt 加入 plan 路径卡片的完整步骤 + 实际执行动作列表 | `test_failure_patch_prompt_includes_card_steps_and_actions` |
| F9 | 补丁步骤写成 “Press the system Back key”，快速路径只认 `press back`/`back navigation` 等字面，仍回退 LLM | Back 识别改为词边界 `\bback\b`；先解析显式 target，再判断无 target 的 Back；swipe/wait 优先，避免 “swipe back” 被误判 | `test_compile_fast_path_recognizes_press_back_key_wording`；全量 156 passed |
| F10 | OmniNotes 搜索只输入不过滤，必须按 Enter；设备层没有对应动作 | 新增通用 `press` 动作（`args=enter`）；编译器识别 “Press Enter / keyboard Enter” 步骤；LLM 编译 prompt 同步 | `test_uiautomator2_device_presses_named_key`、`test_compile_fast_path_presses_enter_key` |
| F11 | `collect_trace --no-start` 不调用 `start_app`，`_package` 为空，`compact_ui` 不过滤包名；after_state 混入 launcher/systemui 节点并在 80 行截断前挤掉 app 内容 | `Uiautomator2Device.set_app()`；`collect_trace` 在启动/不启动两种模式下都先设包名 | `test_uiautomator2_device_set_app_filters_dump_to_package`；重采 search trace 后 after_state 只含 OmniNotes |
| F12 | 重 mine 的卡片直接包含 6 步（两次 Back），但 HY4 这次把 resource id 写成裸文本，没有反引号，快速路径会整体回退 LLM | `_explicit_target` 增加裸 `package:id/name` 识别 | `test_compile_fast_path_handles_bare_resource_ids`；重 mine 卡片 6 步全部无 LLM 编译 |
| F13 | 单个 bullet 的 Inputs 描述里带逗号（archive_note），旧 `_parse_inputs` 仍按逗号切，把一句描述拆成两个伪输入 | 有 bullet 时整条 bullet 作为一个输入，只在无 bullet 的规范格式里按逗号切 | `test_parse_card_keeps_commas_inside_a_single_bullet_input` |
| F14 | 卡片把 target 写成 `` `TextView resourceId=...` `` 或 `` `desc='更多选项'` ``，旧快速路径要么拼成畸形 `resourceId=TextView ...`，要么匹配不到带引号的值 | `_inline_target()` 用命名组解析 `key=value`，支持单/双引号；描述性反引号里提取真正的 target | `test_compile_fast_path_extracts_target_from_descriptive_backticks`、`..._parses_quoted_desc_target`、`..._parses_quoted_text_target` |
| F15 | 步骤 “Tap the visible label {note_title} on `...:id/note_title`” 语法上能解析，但语义上应点匹配标题的那一行，而不是固定点第一行 | 编译 click 时若步骤/目标暗示 label 且有绑定值，优先编译为 `text=<value>`；同时显式 target 也做绑定替换 | `test_compile_fast_path_prefers_label_for_bound_click`、`..._substitutes_binding_in_text_target`；真实 archive/open_note 卡片均无 LLM 编译为正确动作 |
| F16 | 语义边 prompt 加 `inputs=` 后，HY4 为 5 张卡产出 15 条 enables/dataflow 边（含 create→archive、create→open、open→share），但也产出了 archive→create 等回边，导致 `entry_cards()` 为空，规划直接返回 None | 规划种子不再依赖“无入边”这一静态定义：批量分类后，从“当前状态可执行”的候选卡开始搜索；`search()` 新增 `starts` 列表 | `test_plan_seeds_from_executable_cards_even_with_cycles`、`test_explicit_starts_seed_search_outside_entry_cards` |
| F17 | 逐卡 `is_goal` 无法表达多卡组合目标：`create_note` 单卡不能“完全满足 create+archive”，`archive_note` 单卡也不创建笔记，任何单卡答案都错 | `is_goal` 接收整条路径；单卡用批量分类结果，多卡时把“计划序列 + 每卡 intent/postconditions”交给一次 LLM 判断“整个计划是否完整达成目标” | `test_plan_rejects_multi_card_path_that_does_not_complete_goal`、`test_is_goal_receives_the_planned_path`；离线 CLI fake 同步 |
| F18 | 每个卡一次 `can_execute` + 一次 `is_goal`，5 卡图规划至少 5–10 次 HY4 调用，单次 1–4 分钟 | 规划开始时一次批量分类所有候选卡（can_execute + is_goal），缺失/解析失败才回退逐卡调用 | `test_plan_classifies_all_cards_in_one_llm_call`、`test_batch_classification_falls_back_per_card_on_malformed_output`；全量 185 passed |
| F19 | HY4 自己给 `create_note → invoke_share_chooser_for_note` 的描述是“dataflow，但还需要先打开笔记详情页”，即仅数据流不等于可执行；旧搜索会把它当普通后继，选出缺少 `open_note_by_title` 的短路径 | 搜索只沿 `enables` / `sequence` 扩展；`dataflow` 只用于参数供给，不再授权执行 | `test_dataflow_only_edges_do_not_authorize_execution`；全量 186 passed |
| F20 | 组合执行 6/6 动作成功，但第二次 Back 后立刻 dump 时列表行尚未渲染，postcondition 判失败；随后手动 dump 同一屏幕已能看到 Groceries / Buy milk | 真机动作成功后等待 1.0s 再 dump（`Uiautomator2Device(settle_s=1.0)`）；`wait` 动作不重复等待 | `test_uiautomator2_device_settles_after_actions`；全量 188 passed；重跑结果见下文 |
| F21 | postcondition / goal 检查只看卡片原文和 UI，卡片里的 `{target_note}` 等占位符没有具体值，检查器只能靠猜 | 检查 prompt 加入本卡实际编译步骤（含 `args`），goal 检查加入整条计划的编译步骤 | `test_checks_include_compiled_steps`；全量 190 passed |
| F22 | `compact_ui` 只保留目标 app 包名；分享面板属于 `com.android.intentresolver`，打开后会被整包过滤，postcondition 看不到面板 | `compact_ui(extra_packages=...)`；真机默认保留 Android 分享面板包（`com.android.intentresolver` / `com.google.android.intentresolver`），目标 app 节点仍优先 | `test_compact_ui_includes_overlay_package_nodes`、`test_uiautomator2_device_dump_includes_share_chooser`；全量 192 passed |
| F23 | planner 实例在 pipeline 生命周期内复用；`_plan_goal_cache` 只按路径缓存，换目标后会复用上一个目标的判定（例如 archive 目标下 `create→archive` 为 true，share 目标下会被误用） | 路径级目标缓存键改为 `(path, goal, state)` | `test_plan_goal_cache_is_scoped_to_the_goal`；全量 193 passed |
| F24 | executor 启动时为 trace 元数据调用一次 LLM 做状态摘要，但规划器直接使用 compact UI，摘要纯冗余 | 默认使用确定性 `PlainStateSummarizer`（截断 compact UI，0 次 LLM）；`--no-llm-summary` 保留兼容 | `test_plain_summarizer_uses_no_llm_and_truncates`；每用例少 1 次调用 |
| F25 | 复杂流程中搜索框的查询词和笔记标题都显示 `Groceries`；`open_note_by_title` 编译成 `text=Groceries` 会点中搜索框，笔记打不开。截图复现：`07_note_detail` 实际仍是搜索页 | 编译器对“label {title} on `resourceId=...`”生成复合 target `resourceId=...|text=Groceries`；设备层支持 `|` 分隔的多选择器（uiautomator2 多 kwargs 精确定位） | `test_compile_fast_path_prefers_label_for_bound_click`、`test_uiautomator2_device_combines_target_selectors`；截图脚本 10/10 步骤全部命中 |
| F26 | 4 卡目标下 BFS 会逐条路径做 goal 判定（搜索框场景预计 10+ 次 LLM 调用），复杂任务成本不可接受 | batch 分类同一次调用里让 LLM 提出有序计划（`card` + `subgoal`）；校验卡片名、边、首卡可执行后只做 1 次路径级 goal 判定；失败回退 BFS。允许同一卡片重复出现（多实例），每个实例用不同 subgoal 绑定；`PlanStep.instance` 保证相邻同卡实例分别做 postcondition | `test_llm_proposed_plan_avoids_combinatorial_goal_checks`、`test_proposed_plan_without_graph_edge_falls_back_to_search`、`test_plan_proposal_uses_subgoal_for_each_binding`、`test_proposal_can_repeat_a_card_with_distinct_subgoals`、`test_execute_checks_each_repeated_card_occurrence`；全量 200 passed |

## 重 mine 验证（F7）

用“一个物理动作一步”的新 prompt 对同一条 `omninotes-create-note-2` trace 重新 mine，卡片直接得到：

```
5. Press system Back to dismiss the on-screen keyboard.
6. Press system Back to leave the note editor and return to the notes list screen labeled "笔记".
```

说明 F7 的 prompt 修改有效，不再依赖 refine 才补出第二次 Back。该卡片（`runs/real/mine_4_direct.md`）在无 LLM 的 `StepCompiler` 下编译出 6 个动作：两次 click、两次 input、两次 back。

## 多卡图进展

- 已采集并按新 prompt mine 出第二张卡 `search_notes_by_keyword`
  （trace `omninotes-search-3`，3/3 动作成功，卡片含 click search → input keyword → press Enter）。
- 规划 `Search notes for Groceries`：路径 `["search_notes_by_keyword"]`，keyword 正确绑定为 `Groceries`，编译 3 步。
- 真机执行：3/3 动作成功（click → input → press Enter），postcondition 与 goal 均通过，`success=true, goal_success=true`。
  结果文件：`runs/real/execute_search_1.json`。这同时验证了 F10 的 `press` 动作端到端可用。
- 已采集 `omninotes-share-1`（打开笔记 → 分享面板）和
  `omninotes-archive-1`（打开笔记 → 更多选项 → 归档），等待 mine。
- 真机确认 `menu_share`、`menu_category`、`menu_attachment` 可用；
  `menu_tag` 在 6.5.1 FOSS 上点击无对话框（无报错），标签能力需要单独做 capability completion。

### 五卡图

share trace 被正确切成两个 episode，得到两张卡，并自动生成
`open_note_by_title -> invoke_share_chooser_for_note` 的 sequence 边：

| 卡片 | 来源 trace | 关键输入 | 编译动作（全部 0 次 LLM） |
|---|---|---|---|
| `create_note` | omninotes-create-note-2 | note_title, note_content | click FAB → click note → input title → input content → back → back |
| `search_notes_by_keyword` | omninotes-search-3 | keyword | click search → input keyword → press Enter |
| `open_note_by_title` | omninotes-share-1 | note_title | click `text={note_title}` |
| `invoke_share_chooser_for_note` | omninotes-share-1 | note_title, note_content, share_target_label | click `id/menu_share` |
| `archive_note` | omninotes-archive-1 | target_note | click `text={target_note}` → click overflow → click 归档 |

说明：

- share 卡在打开系统分享面板后停止，不真正选择外部 app，避免实验产生外部副作用。
- archive 卡在修正输入解析后重新 mine，`inputs` 不再被逗号拆成伪参数。
- 五张卡都由显式 target 编译，未调用 LLM；这是当前快速路径覆盖率的实测结果。

### 语义边（build_graph_3）

在逐卡描述里加入 `inputs=` 后重跑 `build-graph`，HY4 一次调用产出 15 条语义边
（`runs/real/build_graph_3.json`）：

| 从 | 到 | 类型 | 依据（模型给出） |
|---|---|---|---|
| create_note | open_note_by_title | enables + dataflow | 创建后列表可见新 note_title 行；标题可供给 open 的输入 |
| create_note | archive_note | enables + dataflow | 创建后列表含目标行；标题可供给 target_note |
| create_note | search_notes_by_keyword | enables + dataflow | 创建后回到列表；标题/内容可作 keyword |
| create_note | invoke_share_chooser_for_note | dataflow | 标题和内容可供给分享卡输入（但还需先打开笔记） |
| open_note_by_title | invoke_share_chooser_for_note | sequence + enables | share trace 中观测到的相邻 episode；详情页提供 menu_share |
| open_note_by_title | archive_note | enables | 详情页提供“更多选项” |
| search_notes_by_keyword | open_note_by_title | enables | 过滤后的列表仍可点标题 |
| search_notes_by_keyword | archive_note | enables | 过滤后的列表可暴露目标行 |
| archive_note | create_note / open_note_by_title / search_notes_by_keyword | enables | 归档后回到活动列表（回边） |

两类问题由这张图直接暴露：

1. 回边让所有卡都有入边，`entry_cards()` 返回空集，旧规划器直接失败（F16）。
2. `create_note → invoke_share_chooser_for_note` 这条 dataflow 边本身不足以执行分享：
   分享卡的前置条件是“详情页已打开”，必须先经过 `open_note_by_title`。规划器的
   “边即契约、后继默认可执行”策略在这里会把一张缺少前置步骤的卡直接放进路径。
   需要在多卡执行后用真实反馈验证，再决定是否让语义边区分“强前置”和“仅数据流”。

## 闭环结果（execute_2）

失败驱动补丁把 `create_note` 的第 5 步拆成两次物理 Back：

```
5. Press the system Back key once to dismiss the on-screen keyboard...
6. Press the system Back key a second time to exit the note editor...
```

重跑同一目标 `create a note titled Groceries with content Buy milk`：

- plan：6 步，路径 `["create_note"]`
- 真机执行：6/6 动作成功
- postcondition：`satisfied=true`，理由为已回到笔记列表且能看到 Groceries / Buy milk
- goal check：`achieved=true`
- 最终结果：`success=true, goal_success=true`
- 结果文件：`runs/real/execute_2.json`

这是第一条完整的“失败 → 补丁 → 重跑 → 成功”真实闭环。

## 第一条多卡组合（composed-create-and-archive）

目标：`Create a note titled Groceries with content Buy milk, then archive it`
（`benchmark/pilot/composed_archive.yaml`；每例前 `pm clear`）

第一次运行（`runs/real/pilot_composed_archive.jsonl`）：

```json
{"planned": true, "path": ["create_note", "archive_note"],
 "steps": 6, "actions_ok": 6, "success": false,
 "failure_type": "postcondition_failure",
 "llm_calls": 7, "reset_s": 18.9, "plan_s": 277.7, "execute_s": 22.5}
```

- 规划正确：`create_note → archive_note`，说明 F16/F17/F19 的结构调整在真实图上生效。
- 6/6 动作成功；执行在 `create_note` 的 postcondition 处停止，`archive_note` 的 3 步没有执行。
- postcondition 的失败理由是“列表上看不到 note card”，但运行结束后手动 dump 同一屏幕：

```
TextView text='Groceries' id='.../note_title'
TextView text='Buy milk' id='.../note_content'
```

即动作实际成功，失败来自 dump 时机（F20），不是能力或规划错误。
第二次运行用于验证 1s 稳定等待（结果文件 `runs/real/pilot_composed_archive_2.jsonl`）。

另一个观察：规划阶段 5 次 LLM 调用耗时 277.7s，执行阶段 1 次调用 + 6 个设备动作
耗时 22.5s；真机瓶颈仍是 HY4 延迟。多卡绑定的两次调用可以后续合并为一次。

第二次运行（加入 1s 稳定等待；`runs/real/pilot_composed_archive_2.jsonl`）：

```json
{"planned": true, "path": ["create_note", "archive_note"],
 "steps": 9, "actions_ok": 9, "success": true, "goal_success": true,
 "llm_calls": 3, "reset_s": 18.1, "plan_s": 0.049, "execute_s": 147.2}
```

- 规划 0.049s：batch 分类、两次 plan-goal、两次绑定全部命中磁盘缓存。
- 执行 9/9 动作成功：create 6 步 + archive 3 步；2 次 postcondition 和 1 次 goal
  检查共 3 次 HY4 调用，147.2s。
- 运行结束后手动 dump：列表显示 `暂无内容！`（`empty_list`），Groceries 已被归档。
- 这是第一条在真机上端到端成功的多卡组合（create → archive），验证了
  F16 的可执行种子、F17 的路径级目标判定、F19 的 dataflow 规则和 F20 的稳定等待。

## 第一条三卡组合（composed-create-and-share）

目标：`Create a note titled Groceries with content Buy milk, then share it`
（`benchmark/pilot/composed_share.yaml`）

结果（`runs/real/pilot_composed_share.jsonl`）：

```json
{"planned": true,
 "path": ["create_note", "open_note_by_title", "invoke_share_chooser_for_note"],
 "steps": 8, "actions_ok": 8, "success": true, "goal_success": true,
 "llm_calls": 12, "reset_s": 19.5, "plan_s": 931.0, "execute_s": 167.3}
```

实际编译出的 8 个动作（全部来自快速路径，0 次编译 LLM）：

```
create_note:  click fab_expand_menu_button
              click fab_note
              input detail_title  ← Groceries
              input detail_content ← Buy milk
              back
              back
open_note_by_title: click text=Groceries
invoke_share_chooser_for_note: click menu_share
```

最终 UI（`runs/real/details/composed-create-and-share.json` 的最后一步 after_state）
包含：

```
TextView text='分享文本' id='com.android.intentresolver:id/headline'
TextView text='Buy milk' id='android:id/content_preview_text'
FrameLayout id='com.android.intentresolver:id/copy' ...
LinearLayout id='com.android.intentresolver:id/item' ... QQ ...
```

说明：

- 规划器没有走 `create_note → invoke_share_chooser_for_note` 的 dataflow 短边，
  而是选择 `create → open → share` 三卡路径，F19 的规则在真实图上生效。
- 12 次 LLM 调用中，规划 8 次（batch + 4 次路径目标判定 + 3 次绑定），
  执行 4 次（3 次 postcondition + 1 次 goal）；规划耗时 931s，执行 167s。
- `compact_ui` 在分享面板为不透明窗口时找不到目标 app 节点，回退为“全部包”，
  因此最终状态里混入了 launcher 任务栏节点；不影响 goal 判定，但后续可以
  把回退策略限制为“当前前台窗口 + 允许的 overlay 包”。

## 四卡复杂任务（complex-four-card-share）

目标：`Create a note titled Groceries with content Buy milk, then search for it,
open the note, and share it`（`benchmark/pilot/complex_flow.yaml`）

结果（`runs/real/pilot_complex_flow.jsonl`）：

```json
{"planned": true,
 "path": ["create_note", "search_notes_by_keyword", "open_note_by_title",
          "invoke_share_chooser_for_note"],
 "steps": 11, "actions_ok": 11, "success": true, "goal_success": true,
 "llm_calls": 11, "reset_s": 18.4, "plan_s": 688.8, "execute_s": 105.7}
```

- 模型在一次 batch 调用里同时完成 5 张卡的 `can_execute`/`is_goal` 分类，并直接提出
  四卡有序计划，每一步带 subgoal；计划级 goal 判定只调用 1 次并通过（F26），
  没有回退 BFS。
- 参数绑定 4 次：create（Groceries / Buy milk）→ search（keyword=Groceries）→
  open（note_title=`$search_notes_by_keyword.output`）→ share。跨卡引用由绑定器解析。
- 11 个动作全部成功（11/11）：
  - create：FAB → 文本笔记 → 标题 → 内容 → Back → Back；
  - search：`menu_search` → `search_src_text` ← Groceries → `press enter`（F10）；
  - open：复合选择器 `resourceId=...:id/note_title|text=Groceries`（F25）；
  - share：`menu_share`。
- 搜索页里 `Groceries` 同时出现在搜索框和笔记标题中；复合选择器把点击限定到
  `note_title`，这是四卡任务相对三卡任务新增的真实歧义场景。
- 执行期调用 5 次（4 次 per-card postcondition + 1 次最终 goal），加规划期 6 次，
  共 11 次。最终 UI 含 `com.android.intentresolver:id/headline`（分享文本）和
  `android:id/content_preview_text` = Buy milk。
- 耗时：规划 688.8s，执行 105.7s。规划比三卡任务（931.0s）更短，因为 create
  绑定等命中磁盘缓存；四卡任务没有出现调用数爆炸。

## 关键数据点

- 5 步版卡片执行：5/5 动作成功，但第一次 Back 只关闭键盘，postcondition 准确判失败。
- 6 步版卡片执行：6/6 动作成功，postcondition 与 goal 均通过。
- 耗时：execute_2 约 3.5 分钟，其中状态摘要、postcondition、goal 各一次 HY4 调用；编译命中缓存，设备动作本身为秒级。
- HY4 Free 单次调用常见 1–4 分钟；60 用例全量前需要缓存/快速路径/更快模型的分层策略。
- 重复执行导致列表里出现多张 Groceries 卡片（至少 2 张）；postcondition 仍通过，但说明 per-case 状态隔离必须进 benchmark harness。
- 四卡任务（create → search → open → share）：11/11 动作成功，共 11 次 LLM 调用
  （规划 6 + 执行 5），规划 688.8s + 执行 105.7s；调用数随卡片数线性增长，没有
  组合爆炸，规划耗时主要仍由 HY4 单次延迟决定。

## 4 用例 pilot（中断）

2026-11-10 13:47 启动的完整 4 用例 pilot（create / search-after-create /
create-and-share / create-and-archive）因宿主系统内存压力被后台执行器终止，
尚未产生任何结果行（`runs/real/pilot_cases_1.jsonl` 为空），设备侧没有留下有效
实验数据。按约定不再重跑；验收以逐条组合实验（单卡、archive、share、四卡）为准。

## 下一步（按优先级）

1. ~~用“物理动作一步”的新 prompt 重采 trace、重新 mine~~ 已完成（见 F7 重 mine 验证）。
2. ~~采集 search / archive / share trace，构建 5 卡图~~ 已完成；语义边见 `build_graph_3`，
   组合规划的结构性问题见 F16–F19。
3. ~~跑通 create → archive 多卡组合~~ 已完成（9/9，`pilot_composed_archive_2.jsonl`）。
4. ~~跑 create → share，以及 create → search~~ 已完成：三卡 share（8/8）与
   四卡 create → search → open → share（11/11，`pilot_complex_flow.jsonl`）。
5. ~~4 例 pilot~~ 宿主内存不足被终止，按约定不重跑。
6. 已去掉每次 execute 开头的 LLM 状态摘要（F24）；待办：把逐卡绑定合并为一次批量绑定
   （四卡任务目前为此付出 4 次 HY4 调用）。
7. 扩到其余 5 个 app（F-Droid APK），并比较 HY4 Free 与更快模型在迭代阶段的速度/质量。
8. 跑一个“两次 create_note + open + share”的多实例任务，验证 subgoal 绑定与
   `PlanStep.instance` 的真机行为（目前只有单测）。

## 验收材料（2026-11-10）

- HTML 报告：`docs/reports/acceptance-report.html`（自包含，含 10 张真机截图、
  分步动作、模型请求/输出样例、F1–F26 修改表）。
- 生成脚本：`scripts/build_acceptance_report.py`。
- 截图采集脚本：`scripts/capture_acceptance_shots.py`；图片在 `docs/reports/assets/`。
- 结果与证据：`runs/real/pilot_complex_flow.jsonl`、
  `runs/real/details/complex-four-card-share.json`、`runs/real/build_graph_3.json`、
  `runs/real/work/cards/*.md`。

## 开源 AppAgent 复验（2026-11-10 下午）

按“不要自研 agent、用开源实现、只做最小改动”的要求，后续验收改用
[AppAgent](https://github.com/TencentQQGYLab/AppAgent)（MIT，CHI 2025）：
- Agent 本体直接使用 `third_party/AppAgent/scripts/task_executor.py`，没有重写
  planner / executor / 动作空间。
- 仅改 `config.yaml`（magpie 地址、`auto/gpt-6-luna`、`MAX_TOKENS=800`、
  `MAX_ROUNDS=40`、`REQUEST_INTERVAL=1`），并加两处兼容性补丁：
  `uiautomator dump` 非零重试、`Action` 反引号/粗体清洗。
- `scripts/run_appagent_tasks.py` 是薄封装：重置/启动 app、喂任务、归档真实 labeled
  截图与日志、用外部 Verifier + 文本检查做最终评测；不参与 agent 决策。
- 任务集：`benchmark/agent_tasks.yaml`（8 个长程任务，OmniNotes 6 + ActivityDiary +
  Tasks.org）。
- 报告：`docs/reports/appagent-report.html`；证据：`runs/appagent/<task>/`。
- 说明：本轮为 AppAgent 的 no-doc 部署模式；它的 exploration → `auto_docs` 知识库
  尚未运行，留作后续对比/经验积累实验。

### 已完成任务的结果（严格口径）

严格成功 = 外部 VLM 判定成功 **且** 终屏文本检查通过。8 个任务全部跑完：
**严格 2/8，文本检查通过 6/8，VLM 认可 2/8**。

| 任务 | 轮数 | 文本检查 | VLM | 结果 | 现场观察 |
|---|---:|---|---|---|---|
| omni_four_card_share | 11 | 通过 | 通过 | 成功 | 分享选择器打开，Buy milk 可见 |
| omni_three_notes_edit_archive | 40 | 失败 | 失败 | 失败 | 第 20 轮起抽屉内重复 tap(7)，Travel 从未创建 |
| omni_two_notes_pin_delete | 21 | 通过 | 失败 | 失败 | Alpha 在、Beta 已删；VLM 无法从终屏确认“置顶” |
| omni_checklist_archive | 40 | 通过 | 失败 | 失败 | 已创建并归档（第 18 轮截图可见 Tasks/Buy milk），之后卡抽屉；终屏“暂无内容”无法证明过程 |
| omni_same_title_delete_one | 27 | 通过 | 失败 | 失败 | 自报 FINISH；终屏一条 Meeting/Agenda A；VLM 要求“两条都创建过”的过程证据 |
| omni_tag_search | 40 | 通过 | 失败 | 失败 | Urgent + `#urgent` 已在层级中；最后卡抽屉，搜索页未出现 |
| diary_officework_session | 4 | 通过 | 通过 | 成功 | 启动/停止 Officework，Cinema 成为当前活动 |
| tasks_buy_milk | 40 | 失败 | 失败 | 失败 | 子任务/列表选择器反复切换，40 轮未完成；终屏仍在编辑器，Buy milk 不在可见文本 |

观察到的三类失败模式：
1. **抽屉死循环**：OmniNotes 抽屉打开后，模型反复 `tap(7)`（已选中的“笔记”项），
   界面不变；AppAgent 没有 back 动作、没有 stall 检测，直到 `MAX_ROUNDS=40`。
   任务 1/3/5 都中招。
2. **终屏证据不足**：任务 2/3/4/5 的文本检查通过，但 VLM 无法从终屏确认置顶、优先级、
   “两条笔记都创建过”等过程/隐藏状态，严格口径判失败。逐轮真实截图可以人工确认，
   说明长程任务需要 trace 级证据，而不能只看终态。
3. **列表选择器 / 子任务循环**：Tasks.org 在添加 Check fridge 子任务时反复打开、关闭
   默认清单选择器（tap(4)/tap(6)/tap(10)），40 轮仍未完成；终屏停在任务编辑器，
   Buy milk 标题已滚出可见区域，文本检查也失败。

## 开源 AgentProg baseline（2026-11-10 晚）

### 为什么换成 AgentProg

要求是“学术界论文里用的、代码开源的 Agent，后续可以改、可以看实现”。
最终选择 **AgentProg**（Tsinghua AIR，arXiv 2512.10371，2025-12，
`github.com/MobileLLM/AgentProg`）：它面向长程 GUI 任务，用 Semantic Task
Program（STP）把执行过程表示成带变量和控制流的程序，正好对应我们要做的
“探索 + 功能地图 + 长程任务”方向。

排除项：mobile-use（Minitap）是商业产品，不符合要求；Mobile-Agent-v3 / V-Droid
依赖 GUI-Owl / V-Droid-8B 专用模型，本地 magpie 没有对应权重，未运行。
AppAgent（CHI 2025）保留为旧对照；它没有 Back/Wait/planner，长任务弱。

### 运行方式（不重写 Agent）

- 代码：`third_party/AgentProg`，Python 3.12 venv；litellm 指向本地 magpie。
- 主模型：`openai/auto/gpt-6.1-sol`；UI-TARS grounding 同模型
  （`UITARS_MODEL` 环境变量覆盖，默认仍是 doubao）。
- runner：`scripts/run_agentprog_tasks.py`。只做 App 重置/启动、调用
  `agentprog_pipeline`、记录模型 I/O、抓最终截图/UI、跑 `final_state_v1`
  判定；STP、prompt、执行器、belief state、上下文管理均未改。
- 兼容性最小改动：
  1. `ui_tars_utils.py` 的 API prompt 增加一行“坐标归一化到 0–1000”；
  2. `mobile_utils.py` 支持 `UITARS_MODEL` 环境变量，并补充三个测试 App 的
     activity 映射；
  3. `generate_workflow.py` / `workflow_query_llm.py` 的 `workflow.ap` 与统计文件
     显式 UTF-8（Windows 默认 GBK 会写入失败）。
- 环境 setup：每个任务前 `pm clear` + 启动；OmniNotes 的 6 页首启引导和
  Android 13+ 通知权限由 runner 预处理（`dismiss_known_intro` /
  `pm grant POST_NOTIFICATIONS`），不计入任务步骤。

### 判定口径

只判 Agent 停止后的最终可观察状态（`final_state_v1`）：不要求中间步骤、
不要求导航路径、不读隐藏数据库；如果目标结束在临时界面（如 Android 分享
选择器），就判那个界面。最终截图 + final UI 文本交给 `auto/gpt-6.1-sol`，
输出 3 字段 JSON（`success` / `reason` / `evidence`）；final UI 出现 forbidden
文本直接判失败。确定性 required/forbidden 文本检查只作为辅助信号。

### 结果

（跑完后填入：每任务 success / model calls / agent 耗时 / 失败模式。）
