# 实验环境勘察

> 最后更新：2026-11-18。范围：本机资源、LLM 端点、Android 模拟器、构建工具链、已有服务。
> 本文只记录“实际测到的事实”，不替代实施计划。

## 0. 一句话结论

Android 模拟器、宿主侧 SDK、Gradle 和三个 LLM 端点都已跑通，速度足够 4–8 路并行
GUI 实验。最初的三处兼容性里，Qwen 的工具调用与 reasoning 解析已经在本地 vLLM
上解决；剩下的阻塞点是 4555 上的 Owl 仍是 Mobile-Agent-v3（Qwen2.5-VL-7B），
不是 v3.5 的 GUI-Owl-1.5，v3.5 的脚本与 MobileWorld 的 agent 需要对应权重。

## 1. 机器与磁盘

| 项 | 实测 |
|---|---|
| CPU | 128 vCPU，Intel Xeon Gold 6530 |
| 内存 | 125 GiB，勘察时可用约 70 GiB |
| GPU | 4 × RTX 5090 32GB；vLLM 占约 98GB，每卡剩 5–10GB |
| KVM | `/dev/kvm` 可用；`emulator -accel-check` 通过；当前用户在 kvm 组 |
| 16T 数据盘 | `~/hdd` 是 15T SATA 盘上一个目录的 bind mount，剩 13T |
| Docker root | `<docker-root>` |
| 当前负载 | 勘察时 load ≈ 50，主要来自已有模拟器和 vLLM |

## 2. 目录约定

`hdd` 指 `~/hdd`，实际落在 15T SATA 盘上（`<16T-disk>`）。新装的东西都放在
这里，不再放根目录。

| 路径 | 用途 |
|---|---|
| `<hdd>/models/` | vLLM / HF 权重（既有约定） |
| `<hdd>/cache/` | HuggingFace、pip、Gradle 等缓存 |
| `<hdd>/android/sdk/` | 宿主侧 Android SDK |
| `<hdd>/android/avd/` | AVD（`startrek_test`，API 33） |
| `<hdd>/android/gradle/` | Gradle 8.7 发行包 |
| `<hdd>/android/projects/` | 自建 Android app 的预留目录 |
| `<hdd>/android/downloads/` | 安装包 |
| `<docker-root>/` | Docker 镜像与容器层 |

勘察时用量（2026-11-18）：`vibe/` 582G、`models/` 120G、`harmonyos/` 34G、
`opt/` 4.9G、`archive/` 4.8G、`cache/` 2.4G；整盘 1.6T/15T，剩 13T。

## 3. LLM 端点

### 3.1 端点清单

| 端点 | 模型 | 上下文 | 视觉 | OpenAI tools | 备注 |
|---|---|---|---|---|---|
| `http://127.0.0.1:3425/v1` | `auto/deepseek-v4.1-flash` 等 26 个 | 1M | 是 | 是 | Magpie 网关，本地无需鉴权 |
| `http://127.0.0.1:8002/v1` | `Qwen3.8-27B-FP8` | **262144** | 是 | **是**（`qwen3_xml`） | vLLM，GPU 2+3，TP2，模型在 `hdd/models` |
| `http://127.0.0.1:4555/v1` | `GUI_Owl_7B` | 32768 | 是 | **否**（400） | vLLM，GPU 0+1，模型在 `<colleague-model-mount>` |

Magpie 返回 200 不需要 API key；仓库配置里的 `api_key_env` 可以给一个 dummy 值。
Magpie 的 `zed/*` 模型在当前套餐下返回 403，`auto/*` 可用。

### 3.2 实测速度

128 token 文本、单张 1008×2244 截图；Qwen 为 2026-11-18 重启后的 256k 配置：

| 端点 | 文本 TTFT | 文本解码 | 视觉 TTFT | 视觉解码 | 并发聚合 |
|---|---|---|---|---|---|
| Magpie `auto/deepseek-v4.1-flash` | 1.0–1.4s | 138–161 tok/s | 1.6–2.1s | 110–172 tok/s | 4 路 277 tok/s |
| Qwen3.8-27B-FP8（256k） | 0.8–0.9s（工具调用稳态） | 69–78 tok/s | 2.8–3.0s（8 路） | ~70 tok/s | 8 路：文本 380 tok/s / 视觉+工具 334 tok/s |
| GUI_Owl_7B | 0.03–0.06s | 143–157 tok/s | 0.2–1.0s | 157–162 tok/s | 4 路 543 tok/s |

设备侧观察耗时（uiautomator2 / adb）：UI dump 0.11–0.15s，截图 0.55–0.93s，
`adb exec-out screencap` 0.70–0.78s。

按 20 步任务估算：约 40–60s/任务；4 路并行约 4 个任务/分钟。LLM 不是瓶颈。

Qwen 256 输出 token 的 TPS 测试：单流 **78.5 tok/s**；4 路每请求 63–69、
聚合 233 tok/s；8 路每请求 60–64、聚合 442 tok/s。项目配置已在 2026-11-18
切到 Qwen3.8（cache 见第 10 节）。

### 3.3 能力与限制

- **Magpie**：1M 上下文，视觉和工具调用都可用。带系统提示时
  `auto/deepseek-v4.1-flash` 与 `auto/glm-5.3-flash` 在 `tool_choice=auto` 下
  3/3 次正确调用工具；视觉 + 工具一次约 2.5s（1238 prompt tokens / 48 output）。
- **Qwen3.8（当前 256k 部署）**：原生 262,144 上下文；vLLM TP2（GPU 2+3），
  已启用 `--enable-auto-tool-choice --tool-call-parser qwen3_xml` 和
  `--reasoning-parser qwen3`。文本工具调用、视觉 + 工具、`tool_choice=auto`
  和 `required` 都通过；reasoning 文本在响应的 `reasoning` 字段，
  `content` 是干净的最终 JSON，仓库 planner 可以直接解析。KV 容量
  **372,844 tokens**（256k 请求并发 1.42x）。稳态工具调用
  0.8–0.9s；8 路视觉 + 工具 2.9s wall、8/8 成功。
  冷启动很慢：权重从 SATA 盘读入约 17 分钟、torch.compile 约 4 分钟、
  engine init 合计约 13 分钟，总计约 35–40 分钟；首个请求还会触发约 100s 的
  JIT 预热，实验前应先打几发 warmup。
- **GUI-Owl 7B**：最快，32k 上下文，适合做 executor；模型卡是
  Mobile-Agent-V3（Qwen2.5-VL-7B），不是 GUI-Owl-1.5。服务没有
  `--enable-auto-tool-choice`，所以 OpenAI tools 不可用。

### 3.5 Qwen 256k 部署（2026-11-18）

启动脚本：`<hdd>/models/QWEN38_VLLM.sh`（`start|stop|status|logs|rm`）。

关键参数：

```text
--gpus '"device=2,3"' --tensor-parallel-size 2
--max-model-len 262144 --gpu-memory-utilization 0.90
--quantization fp8 --trust-remote-code
--enable-auto-tool-choice --tool-call-parser qwen3_xml
--reasoning-parser qwen3
--max-num-seqs 32 --enable-prefix-caching
--safetensors-load-strategy=prefetch
```

KV 估算：64 层里 48 层 linear attention、16 层 full attention；4 个 KV head，
head_dim 256，bf16 每 token 约 64KiB。262,144 tokens ≈ 16GiB；实际分配到
11.61GiB/worker，共 372,844 tokens。GPU 0/1 仍由 `gui-owl-7b-4555` 占用，
所以当前是 2 卡；要上 4 卡需要先停 owl 并确认 模型主人确认不再使用。

### 3.4 代理问题

默认 shell 有 `all_proxy=socks5://127.0.0.1:7892`，OpenAI SDK（httpx2）会尝试
走 SOCKS，而 `socksio` 没装，于是连 `127.0.0.1` 都报错。只设 `NO_PROXY` 不够，
需要：

```bash
env -u all_proxy -u ALL_PROXY \
    -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    <command>
```

或者安装 `httpx[socks]`。后者只解决 SDK，前者对所有工具都有效，推荐统一用前者。

## 4. Android 模拟器

### 4.1 已验证

- 现有 `emulator-5554` 上 uiautomator2 正常：`dump_hierarchy` 约 45k 字符、
  截图正常。
- 另起一个 AVD 与 5554 同时运行，`adb devices` 同时看到两个设备，
  uiautomator2 在第二个上也能截图和 dump。
- 宿主侧原生启动 AVD（不经容器）**106 秒**完成启动；API 33、1080×2400、
  density 420。
- 容器内启动同一 AVD 约 **114 秒**。
- 每个模拟器常驻约 2.5–4GB 内存；空闲约 0.25–1 核，启动/软件渲染高峰可到
  3–15 核（`-gpu swiftshader_indirect`）。

### 4.2 容量建议

当前 70GB 可用内存、128 核，建议先稳定跑 **4–6 个**模拟器，压测后再上 8 个。
磁盘不是问题：每个 AVD 首启后约 0.8GB。

### 4.3 端口与 serial

- 模拟器 console 端口 5554、5556、…；adb 端口分别是 5555、5557、…。
- 现有 `emulator-5554` 属于 `aw-eval` 容器（host 网络），不要动。
- 新模拟器建议从 5580 起，避免和现有服务冲突。
- StarTrek 的 `scripts/run_mobileworld_bench.py` 支持 `--serial` /
  `ANDROID_SERIAL`；`specfcg.cli` 只读 `config/llm.yaml` 的 `device.serial`，
  跑模拟器时要改配置。

### 4.4 MobileWorld 多容器

`<hdd>/vibe/MobileWorld` 的 `mw env run --count N` 可一次拉起多个
容器，每个容器自带模拟器。`--dry-run` 实测端口分配：

| 容器 | backend | viewer | VNC | ADB |
|---|---|---|---|---|
| env_1 | 6801 | 7861 | 5801 | 5557 |
| env_2 | 6802 | 7862 | 5802 | 5558 |

注意：容器是 `--privileged`；当前 `env_0` 对外暴露的 5560 是 console 而不是
ADB，`adb connect 127.0.0.1:5560` 是 offline。新起 env 的 ADB 端口是否可直接
连，尚未实测。

## 5. Android 构建工具链

| 组件 | 版本/路径 |
|---|---|
| adb | 37.0.1，`hdd/android/sdk/platform-tools/adb` |
| emulator | 37.2.13，`hdd/android/sdk/emulator/emulator` |
| cmdline-tools | `hdd/android/sdk/cmdline-tools/latest` |
| platform | `android-33` |
| build-tools | `33.0.0` |
| system image | `system-images;android-33;google_apis;x86_64`（system.img 8.6G） |
| Gradle | 8.7，`hdd/android/gradle/gradle-8.7` |
| JDK | Temurin 17.0.21，复用 `hdd/harmonyos/jdk17` |
| AVD | `startrek_test`，API 33、1080×2400、3G RAM、约 837M |

`gradle --version` 已用该 JDK 验证通过。尚未构建任何 APK；`projects/` 是预留目录。

容器 `android_world:latest` 内另有一套 SDK 33 + JDK 18，可作为备选构建环境。

## 6. 已有服务清单

勘察时运行中的容器：

| 容器 | 镜像/用途 | 归属/备注 |
|---|---|---|
| `qwen38-27b-fp8` | vLLM Qwen3.8，端口 8002 | 本项目，模型在 `hdd/models` |
| `gui-owl-7b-4555` | vLLM GUI-Owl，端口 4555 | 模型在 `<colleague-model-mount>`，重启前需协调 |
| `mobile_world_env_0` | MobileWorld 环境 + 模拟器 | `<hdd>/vibe/MobileWorld` |
| `aw-eval` | AndroidWorld 环境 + 模拟器，host 网络 | `<hdd>/vibe/mobile-agent-acceptance` |
| `aw-verify-headed` | AndroidWorld 验证容器 | 网络 none |
| `aw-verify-headless` | AndroidWorld 验证容器 | 网络 none |
| `harmonyos-dev` | 鸿蒙开发环境 | 同事的，忽略 |
| 3 个 HarmonyOS Emulator 进程 | 鸿蒙模拟器 | 同事的，忽略 |

不要停/重启 `gui-owl-7b-4555` 和同事的鸿蒙服务；`aw-*` 若是自己的也先确认用途。

## 7. Owl / Mobile-Agent

- 4555 的 `GUI_Owl_7B` 是 **Mobile-Agent-v3** 系列（Qwen2.5-VL-7B），
  不是 v3.5 的 GUI-Owl-1.5。
- `third_party/MobileAgent` 同时包含 `Mobile-Agent-v3` 和 `Mobile-Agent-v3.5`。
- v3 入口：`third_party/MobileAgent/Mobile-Agent-v3/mobile_v3/run_mobileagentv3.py`，
  参数 `--adb_path --api_key --base_url --model --instruction --coor_type`，
  与当前 7B 模型匹配。
- v3.5 入口：`third_party/MobileAgent/Mobile-Agent-v3.5/mobile_use/run_gui_owl_1_5_for_mobile.py`，
  需要 GUI-Owl-1.5 权重；HF/ModelScope 均可访问，`GUI-Owl-1.5-8B-Instruct`
  约 16GB。
- MobileWorld 的 `gui_owl_1_5` agent 也是按 1.5 写的；用 `mw eval` 时可以传
  `--agent_type gui_owl_1_5 --llm_base_url ... --model_name ...`，但当前 7B
  存在版本错配。

## 8. 兼容性问题清单

| # | 问题 | 影响 | 可选处理 |
|---|---|---|---|
| 1 | GUI-Owl 不支持 OpenAI tools | 仓库 `mobile_agent` 不能用 4555 | 用 Magpie；或重启 owl 加 tool parser；或改用 MobileAgent 文本协议 |
| 2 | ~~Qwen reasoning 破坏 JSON~~（已解决） | 旧 8192 配置下 planner 失败 | 已用 `--reasoning-parser qwen3`，`content` 干净；planner 实测通过 |
| 3 | `all_proxy` 破坏本地 OpenAI 调用 | 所有本地 LLM 脚本 | 运行时 `env -u ...` 去掉代理 |
| 4 | `config/llm.yaml` 的 serial 是真机 | 模拟器跑不了 | 改成 `emulator-*`；或用 bench 的 `--serial` |
| 5 | Owl 是 v3 不是 v3.5 | v3.5 脚本/agent 不匹配 | 用 v3 脚本；或下载 GUI-Owl-1.5 |
| 6 | MobileWorld env_0 的 ADB 未暴露 | 外部 adb 连不上 | 新 env 用 `--adb-start-port`；或继续用宿主侧模拟器 |
| 7 | 软件渲染 CPU 开销高 | 并行数量受限 | 先 4–6 个；后续试 `-gpu host` 等 |
| 8 | Qwen 只有 2 卡（GPU 0/1 被 owl 占用） | 4 卡吞吐不可用 | 需停 `gui-owl-7b-4555` 并确认 模型主人确认不再使用 |
| 9 | Qwen 冷启动约 35–40 分钟 | 服务重启成本高 | 已加 prefetch；后续挂载 torch.compile 缓存卷 |

## 9. Shell 环境

`~/.zshrc` 新增了 Android 块（约 63–80 行）：

```bash
export ANDROID_HOME="<hdd>/android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export ANDROID_AVD_HOME="<hdd>/android/avd"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-<hdd>/cache/gradle}"
export JAVA_HOME="${JAVA_HOME:-<hdd>/harmonyos/jdk17}"
export GRADLE_HOME="${GRADLE_HOME:-<hdd>/android/gradle/gradle-8.7}"
# PATH 里加入 platform-tools、emulator、cmdline-tools、JDK、Gradle
```

新开 zsh 后 `adb`、`emulator`、`sdkmanager`、`gradle` 均可用；`Gradle 8.7` 的
JVM 是 17.0.21。HarmonyOS 与 `MAGPIE_BASE_URL` / `QWEN_*` / `GUI_OWL_*` 块是
另行加入的，未改动。

## 10. 尚未验证 / 待决策

- 4–8 个模拟器的持续并行压测（目前只验证了 2 个同时运行）。
- 宿主侧模拟器在 `-gpu host` / 不同 API level 下的 CPU 表现。
- 新起 MobileWorld env 的外部 ADB 连通性。
- 自建 Android app 的实际构建与安装（工具链已就绪，尚未写 app）。
- GUI-Owl-1.5 的下载、显存规划与服务重启（涉及另一位同事的容器）。
- Qwen 256k 冷启动约 35–40 分钟；prefetch 和 torch.compile 缓存卷的效果待验证。
- 4 卡（TP4）部署未验证；需要先停 `gui-owl-7b-4555` 并确认 模型主人确认不再使用。
- 仓库 `mobile_agent` 与 Qwen 256k 的视觉 + 工具调用已验证；Magpie 的端到端
  小任务仍未跑。
- 项目配置已于 2026-11-18 切到 Qwen3.8（`config/llm.yaml`、`config/llm.bench.yaml`），
  cache 分别改为 `.cache/llm-qwen38` / `.cache/llm-bench-qwen38`；旧分数记录由
  Magpie 产出，报告要标断点。
