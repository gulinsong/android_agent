# 车载语音助手 — 架构文档

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         外部服务 / 云端                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│   │ 飞书 API │  │  QQ Bot  │  │ 微信桥接  │  │ OpenAI/ElevenLabs│  │
│   └─────┬────┘  └─────┬────┘  └─────┬────┘  │  (可选云端 TTS)  │  │
└─────────┼─────────────┼─────────────┼────────┴──────────────────┘  │
          │             │             │                               │
══════════╪═════════════╪═════════════╪═══════════ 局域网边界 ═════════
          │             │             │                               │
┌─────────┼─────────────┼─────────────┼──────────────────────────────┐
│         │    开发机 (172.20.10.2)   │                              │
│         │             │             │                              │
│   ┌─────┴─────┐ ┌────┴─────┐ ┌────┴──────┐ ┌───────────────────┐ │
│   │ MiniCPM   │ │   STT    │ │  VoxCPM2  │ │   微信桥接服务    │ │
│   │ (备用LLM) │ │ Service  │ │   TTS     │ │   (wechaty)       │ │
│   │  :8080    │ │  :8090   │ │ :8000/8091│ │                   │ │
│   └───────────┘ └──────────┘ └───────────┘ └───────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                    车机 (172.20.10.3)                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                  OpenClaw Gateway (:18801)                   │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │ │
│  │  │ feishu   │ │ car-     │ │ talk-    │ │  qqbot       │  │ │
│  │  │ (内置)   │ │ control  │ │ voice    │ │  (内置)      │  │ │
│  │  │          │ │ skill    │ │ plugin   │ │              │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │ │
│  └───────────────────────────┬─────────────────────────────────┘ │
│                              │                                   │
│  ┌───────────────────────────┼─────────────────────────────────┐ │
│  │       Voice Agent         │                                 │ │
│  │  ┌──────────┐  ┌─────────┴──────┐  ┌──────────────────┐   │ │
│  │  │ 麦克风    │  │  WebSocket     │  │    扬声器         │   │ │
│  │  │ 录音     │──│  ↔ Gateway     │──│    播放           │   │ │
│  │  │ (ALSA)   │  │                │  │    (ALSA)         │   │ │
│  │  └──────────┘  └────────────────┘  └──────────────────┘   │ │
│  │                                                            │ │
│  │  Phase 4: ┌──────────────────┐                             │ │
│  │           │ 唤醒词检测        │                             │ │
│  │           │ (Porcupine)      │                             │ │
│  │           └──────────────────┘                             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 车机系统                                                     │ │
│  │ (MediaSession / BYD Map Protocol SDK / UI 自动化)            │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ agent_front_app (com.openclaw.car)                           ││
│  │  5 tabs: 主动服务 · 地图 · A2UI卡片 · 音乐 · 设置            ││
│  │  UiHttpServer (:18802) · MapProtocolManager                  ││
│  │  ProactiveFragment (3 scene cards → SCENE.md → 导航+关怀)    ││
│  │  AGenUIFragment (A2UI卡片渲染, SurfaceManager, 多卡片)       ││
│  │  GatewayClient (JSONL poll, A2UI协议解析, 增量行检测)        ││
│  │  UiAutomationService · NodeProcessService · BootReceiver     ││
│  │  FloatingBubbleService (悬浮球+录音交互)                     ││
│  └──────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据流

### 2.1 语音交互数据流

```
用户说话
  │
  ↓
[ALSA 录音] → PCM 16kHz S16LE
  │
  ↓ (200ms 分块，WebSocket)
[OpenClaw Gateway] → speech-core 插件
  │
  ↓ (HTTP POST multipart)
[STT Service :8090] → faster-whisper
  │
  ↓ (文字)
[OpenClaw Gateway] → Agent → SKILL.md 匹配
  │
  ↓ (OpenAI Chat Completions)
[DeepSeek V4 Flash (云端)] → 生成回复/指令
  │
  ├── 指令执行 → [UiHttpServer :18802 / Skills] → 车机系统
  │
  ↓ (回复文字)
[OpenClaw Gateway] → talk-voice 插件
  │
  ↓ (HTTP POST)
[TTS Service :8091] → Edge TTS / CosyVoice
  │
  ↓ (音频流)
[OpenClaw Gateway] → WebSocket 返回
  │
  ↓
[Voice Agent] → ALSA 播放
```

### 2.2 主动关怀数据流

```
用户选择场景卡片 (ProactiveFragment)
  │
  ↓
[写入 SCENE.md] → 场景描述文本（含宝宝状态、位置、乘员信息）
  │
  ↓
[OpenClaw Gateway] → Agent 每轮读取 SCENE.md
  │
  ├── 判断导航意图 → [car-nav skill] → HTTP API :18802
  │     ├── 场景一(小区出发): api /map/navi → 社康中心
  │     ├── 场景二(社康回家): api /map/home
  │     └── 场景三(返程中):   api /map/naviState → 补导回家
  │
  ├── 关怀响应 → [LLM] → 温暖关怀回复 + 具体行动建议
  │
  └── 生成 A2UI 卡片 (模板四：主动关怀卡片)
        ├── 宝宝状态区 (情绪 + 原因 + 看护人)
        ├── 导航信息区 (目的地 + 距离 + 预计时间)
        └── 关怀操作区 (音乐安抚 + 温度调节 + 安抚建议)
  │
  ↓
[GatewayClient] → poll session JSONL → 检测 A2UI 协议 → notifyA2UI
  │
  ↓
[AGenUIFragment] → receiveA2UI → renderCard → SurfaceManager
```

### 2.3 A2UI 卡片数据流

```
Agent 回复（文字 + A2UI JSON）
  │
  ↓ (写入 session JSONL)
[GatewayClient] 每 2s poll session 文件
  │
  ├── 增量行检测: lastLineCounts[file] → 只处理新行
  ├── parseLine: JSON 解析失败(流式写入不完整) → 不推进计数, 下次重试
  ├── role=assistant + isA2UIProtocol → extractA2UILines → notifyA2UI
  │
  ↓
[AGenUIFragment.receiveA2UI]
  ├── 加入 cardJsonHistory (companion object, 跨 View 重建保持)
  ├── renderCard: 创建 SurfaceManager → beginTextStream → receiveTextChunk → endTextStream
  ├── 天气卡片: processWeatherCard → 动态主题(根据天气状况变色)
  └── 多卡片网格: FlowLayout 2列, MaterialCardView 容器, 滑动删除
```

### 2.4 IM 通道数据流

```
飞书/QQ/微信消息
  │
  ↓
[Channel 插件] → 文字 / 语音附件
  │
  ├── 语音附件 → [STT :8090] → 文字
  │
  ↓ (文字)
[OpenClaw Gateway] → Agent → LLM → 回复
  │
  ├── 文字回复 → [Channel 插件] → IM 回复
  │
  └── 语音回复 → [TTS :8091] → 音频 → [Channel 插件] → 语音消息回复
```

---

### 2.5 音色控制数据流（agent_front_app ↔ TTS adapter）

```
车机 App (agent_front_app)
  │
  ├── 预设音色选择（温柔/活泼/沉稳/知性/特朗普/林志玲/雷军）
  │     → POST /v1/voices {ref_audio: "voice_samples/sample_1.wav", dialect: "四川话"}
  │     → adapter 更新 voices.json 的 default 预设
  │     → App 本地播放 WAV 预览（assets）
  │
  ├── 自定义音色（文字描述）
  │     → POST /v1/voices {prompt_text: "(磁性男声)", auto_ref: true, ref_audio: null}
  │     → 首次生成后 adapter 自动保存音频为 ref_audio
  │     → 后续请求自动使用 ref_audio 克隆（prompt_text 清空，dialect 保留）
  │
  ├── 方言选择
  │     → POST /v1/voices {dialect: "四川话"}  （merge 式，不影响 ref_audio）
  │     → 同时更新 SOUL.md 追加 "请用四川话回复"
  │
  └── 启动恢复
        → GET /v1/voices/default 查询 adapter 状态
        → 比对本地配置，不一致则按需更新
```

---

## 3. 进程架构

### 3.1 车机进程

| 进程 | 启动方式 | PID 管理 | 看门狗 |
|------|---------|---------|--------|
| openclaw gateway | nohup node-termux openclaw.mjs gateway | 进程树 | 内置健康检查 |
| voice-agent | nohup node-termux voice-agent.js | PID 文件 | Phase 3 新增 |

| agent_front_app (com.openclaw.car) | Android App | 4-tab UI (人设/技能/记忆/主动服务)、UiHttpServer (:18802)、MapProtocolManager (BYD Map SDK)、GPS Monitor、音色/方言控制、UI 自动化 (UiAutomationService)、Node.js 进程管理 (NodeProcessService)、开机自启 (BootReceiver) |

注：agent_front_app 整合了原 caragent-app (com.caragent.bootstrap) 的全部功能，包括无障碍 UI 自动化、Node.js 进程管理与看门狗、开机自启。feishu 和 qqbot 通道由 OpenClaw Gateway 内置插件管理，无需独立进程。

### 3.2 开发机进程

| 进程 | 端口 | 说明 |
|------|------|------|
| llama.cpp (MiniCPM) | 8080 | LLM 推理（备用，当前用云端 DeepSeek V4 Flash） |
| faster-whisper-server | 8090 | STT 服务 |
| VoxCPM2 TTS | 8000 | TTS 推理服务（nanovllm-voxcpm） |
| TTS 适配层 | 8091 | OpenAI 兼容 TTS 代理 → VoxCPM2 |
| wechaty (Phase 3) | 8092 | 微信桥接 |

### 3.3 开发机服务启动

**Conda 环境：** `voxcpm`（包含 torch 2.6+cu124、flash-attn、fastapi、faster-whisper 等全部依赖）

**启动顺序：**

```bash
conda activate voxcpm

# 1. VoxCPM2 TTS 推理（加载模型较慢，约 30s）
python3 tts-adapter/voxcpm_server.py \
  --model-path /home/tsm/work/models/VoxCPM2 \
  --port 8000 --host 0.0.0.0 --gpu-memory 0.9 &

# 2. TTS 适配层（依赖 VoxCPM2，等 8000 端口就绪后启动）
sleep 15
python3 tts-adapter/adapter.py \
  --voxcpm-url http://localhost:8000 \
  --port 8091 --host 0.0.0.0 &

# 3. STT 服务（独立，可并行启动）
python3 stt-server.py --host 0.0.0.0 --port 8090 &
```

**验证：**

```bash
ss -tlnp | grep -E '8000|8090|8091'    # 三个端口都在监听
curl http://172.20.10.2:8091/v1/voices/default  # TTS 音色查询
```

**依赖注意事项：**

- `flash-attn` 预编译包与 PyTorch 2.12+ 不兼容，需要 `torch==2.6.0+cu124`
- 安装命令：`pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124`
- `nanovllm_voxcpm` 要求 flash-attn，验证：`python3 -c "import nanovllm_voxcpm"`

---

## 4. Magisk 引导架构

### 4.1 设备信息

| 项目 | 值 |
|------|-----|
| 车型 | BYD Yangwang |
| Android | 14 |
| SoC | MediaTek mt6991 (arm64-v8a) |
| Active slot | `_a` |
| init_boot 分区 | `/dev/block/by-name/init_boot_a` |

### 4.2 Magisk 安装步骤

1. 下载 Magisk v30.7 APK (GitHub)
2. 从 APK 提取二进制 (`lib/arm64-v8a/`)：

| APK 内路径 | 安装为 |
|-----------|--------|
| `libmagiskboot.so` | `magiskboot` |
| `libmagiskinit.so` | `magiskinit` |
| `libmagisk.so` | `magisk32` |
| `libmagiskpolicy.so` | `magiskpolicy` |
| `libinit-ld.so` | `init-ld` |
| `libbusybox.so` | `busybox` |

同时提取 `assets/boot_patch.sh`、`util_functions.sh`、`stub.apk`。

3. Dump 并修补 init_boot：
```bash
dd if=/dev/block/by-name/init_boot_a of=/data/local/tmp/init_boot_a.img bs=4096
KEEPVERITY=true KEEPFORCEENCRYPT=true sh boot_patch.sh /data/local/tmp/init_boot_a.img
dd if=new-boot.img of=/dev/block/by-name/init_boot_a bs=4096
```

4. 手动安装 Magisk 二进制到 `/data/adb/magisk/`，并创建符号链接 `magisk→magisk32`、`su→magisk32`。

### 4.3 引导流程

```
车机上电
  → Magisk init (patched init_boot_a)
  → post-fs-data: setenforce 0
  → Android 启动
  → BOOT_COMPLETED
  → service.d: openclaw-boot.sh 启动 com.openclaw.car/.MainActivity
  → NodeProcessService → Gateway (:18801)
  → UiHttpServer (:18802) auto-starts
  → QQ Bot / 飞书连接就绪
```

### 4.4 引导脚本

| 脚本 | 阶段 | 功能 |
|------|------|------|
| `/data/adb/post-fs-data.d/setenforce.sh` | post-fs-data | `setenforce 0` 关闭 SELinux |
| `/data/adb/service.d/openclaw-boot.sh` | boot_completed | 启动 `com.openclaw.car/.MainActivity` |

### 4.5 备份与恢复

```bash
# 原始镜像备份位置
/data/adb/init_boot_a.orig.img

# 恢复原厂镜像
dd if=/data/adb/init_boot_a.orig.img of=/dev/block/by-name/init_boot_a bs=4096
```

### 4.6 车机关键文件

| 路径 | 说明 |
|------|------|
| `/data/adb/magisk/` | Magisk 二进制 |
| `/data/adb/post-fs-data.d/` | early-boot 脚本 |
| `/data/adb/service.d/` | boot 完成后脚本 |
| `/data/local/tmp/node-termux` | Node.js 运行时 |
| `/data/local/tmp/openclaw/` | OpenClaw Gateway |
| `/data/local/tmp/node-lib/` | Node.js 依赖 |
| `/data/local/tmp/openclaw-home/.openclaw/workspace/` | SOUL.md, TOOLS.md, AGENTS.md, MEMORY.md |
| `/data/local/tmp/openclaw-home/.openclaw/skills/` | car-nav, car-music, car-poi |
| `/data/local/tmp/gps-monitor.sh` | GPS 坐标解析 (SomeIP logcat → gps.json) |
| `/data/local/tmp/gps.json` | GPS 坐标缓存 (/location endpoint) |

---

## 5. 网络架构

```
          ┌──────────────────────┐
          │   WiFi 局域网         │
          │   172.20.10.0/28     │
          │                      │
    ┌─────┴──────┐    ┌─────────┴──────┐
    │ 车机        │    │ 开发机          │
    │ 172.20.10.3│    │ 172.20.10.2    │
    │            │    │                │
    │ :18801 GW  │←──→│ :8080 MiniCPM  │
    │ :18802 HTTP│    │ :8090 STT      │
    │            │    │ :8000 VoxCPM2  │
    │            │    │ :8091 TTS适配层 │
    └────────────┘    └────────────────┘
          │                    │
          │            ┌───────┴───────┐
          │            │  外网 (NAT)    │
          │            │               │
          │            │ 飞书 API      │
          │            │ QQ Bot API    │
          │            │ DeepSeek API  │
          │            └───────────────┘
```

### 5.1 端口规划

| 端口 | 服务 | 绑定 | 说明 |
|------|------|------|------|
| 18801 | OpenClaw Gateway | LAN | 消息网关 + WebSocket (Token 认证) |
| 18802 | UiHttpServer | localhost | agent_front_app HTTP API (导航/音乐/POI/GPS) |
| 8080 | MiniCPM LLM | LAN | 开发机 LLM（备用，当前用云端 DeepSeek V4 Flash） |
| 8090 | STT Service | LAN | 开发机语音识别 |
| 8000 | VoxCPM2 TTS | LAN | 开发机 TTS 推理 |
| 8091 | TTS 适配层 | LAN | OpenAI 兼容 TTS 代理 → VoxCPM2 |
| 8092 | 微信桥接 | LAN | 开发机微信 (Phase 3) |

---

## 6. 技术选型

### 6.1 LLM

| 选项 | 型号 | 位置 | 延迟 | 质量 |
|------|------|------|------|------|
| **当前选择** | DeepSeek V4 Flash (deepseek-v4-flash) | 云端 | ~3s | 高 |
| 备选（本地） | MiniCPM-o-4.5 Q4_K_M | 开发机 GPU | ~2s（但 prompt 过大时卡住） | 中 |
| 未来 | 车机端小模型 | 车机 NPU | <1s | 低 |

### 6.2 STT

| 选项 | 位置 | 延迟 | 中文质量 |
|------|------|------|---------|
| **首选** | faster-whisper-server large-v3 (开发机 :8090) | 1-2s | 高 | ~3GB 显存 |
| 轻量 | faster-whisper medium | 0.5-1s | 中 | ~1.5GB 显存 |
| 云端 | OpenAI Whisper API | 2-4s | 高 | 0 |

**当前选择：** faster-whisper-server，兼容 OpenAI `/v1/audio/transcriptions` 接口，GPU 加速。

### 6.3 TTS

| 选项 | 位置 | 延迟 | 中文质量 | 显存 |
|------|------|------|---------|------|
| **当前选择** | VoxCPM2 (开发机 :8000 + 适配层 :8091) | ~1s | 高 | ~8GB |
| 旧方案 | openai-edge-tts (开发机 :8091) | 0.5-1s | 高 | 0 |
| 云端 | ElevenLabs/OpenAI | 1-2s | 高 | 0 |

**当前选择：** VoxCPM2，通过 nanovllm-voxcpm 加速推理，支持声音克隆（参考音频）。适配层兼容 OpenAI `/v1/audio/speech` 接口，OpenClaw 无需修改配置。

### 6.3.1 TTS 音色配置

适配层通过 `tts-adapter/voices.json` 管理音色预设，支持参考音频声音克隆、方言设置和自定义音色自动升级。

**车机 App（agent_front_app）控制音色流程：**

App 通过 HTTP API 动态更新 adapter 的 `"default"` 预设，OpenClaw Gateway 始终发送 `voice="default"`。

```
预设音色：ref_audio（WAV 参考音频克隆）+ dialect（方言提示）
自定义音色：prompt_text → 首次生成后 auto_ref 自动升级为 ref_audio 克隆
方言：独立字段，同时注入 TTS（prompt 前缀）和 LLM（SOUL.md 追加方言指令）
```

**7 个预设音色（WAV 样本同时用于 App 预览 + adapter 声音克隆）：**

| 样本文件 | 音色 | 说明 |
|---------|------|------|
| `voice_samples/sample_1.wav` | 温柔女声 | 8.0s |
| `voice_samples/sample_2.wav` | 活泼女声 | 5.6s |
| `voice_samples/sample_3.wav` | 沉稳男声 | 6.4s |
| `voice_samples/sample_4.wav` | 知性女声 | 6.1s |
| `voice_samples/sample_5.wav` | 特朗普 | 新增 |
| `voice_samples/sample_6.wav` | 林志玲 | 新增 |
| `voice_samples/sample_7.wav` | 雷军 | 新增 |

UI 从 2x2 按钮网格改为可滚动 RecyclerView 列表，以容纳更多预设。

**Adapter API：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/audio/speech` | POST | TTS 合成（OpenAI 兼容） |
| `/v1/voices` | POST | merge 式更新音色预设（只更新发送的字段） |
| `/v1/voices/{id}` | GET | 查询单个音色预设 |
| `/v1/models` | GET | 列出所有音色 |

**API 调用示例：**

```bash
# 查询当前 default 预设
curl http://172.20.10.2:8091/v1/voices/default

# 选择预设音色（温柔女声）+ 方言
curl -X POST http://172.20.10.2:8091/v1/voices \
  -H "Content-Type: application/json" \
  -d '{
    "id": "default",
    "ref_audio": "voice_samples/sample_1.wav",
    "prompt_text": "",
    "dialect": "四川话",
    "cfg_value": 2.0,
    "temperature": 0.9,
    "auto_ref": false
  }'

# 切换方言（merge 模式，不影响 ref_audio）
curl -X POST http://172.20.10.2:8091/v1/voices \
  -H "Content-Type: application/json" \
  -d '{"id": "default", "dialect": "粤语"}'

# 取消方言
curl -X POST http://172.20.10.2:8091/v1/voices \
  -H "Content-Type: application/json" \
  -d '{"id": "default", "dialect": ""}'

# 自定义音色（第一次用 prompt_text，auto_ref 自动升级为 ref_audio）
curl -X POST http://172.20.10.2:8091/v1/voices \
  -H "Content-Type: application/json" \
  -d '{
    "id": "default",
    "ref_audio": null,
    "prompt_text": "(磁性男声，略带沙哑)",
    "dialect": "",
    "auto_ref": true
  }'

# 用当前音色合成语音（OpenClaw Gateway 调用方式）
curl -X POST http://172.20.10.2:8091/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "你好，今天天气怎么样", "voice": "default"}' \
  -o test.wav
```

**配置参数说明：**
- `prompt_text` — 风格提示词，生成时自动拼接到文本前面
- `cfg_value` — 引导强度（1.0-3.0），越高风格越强，但可能降低自然度
- `temperature` — 采样随机性（0.5-1.5），越低越稳定，越高越多样
- `ref_audio` — 参考音频路径（相对于 adapter.py 所在目录），null 表示不使用
- `dialect` — 方言名称（如"四川话"），独立于 prompt_text，生成时自动添加 `(方言)` 前缀
- `auto_ref` — 自动升级标记，首次生成（>=3s）后自动保存音频并升级为 ref_audio 克隆

**显存分配（RTX 5000 Ada 16GB）：**
| 服务 | 显存 |
|------|------|
| faster-whisper large-v3 (STT) | ~2.1 GB |
| VoxCPM2 (TTS) | ~11 GB |
| 剩余 | ~2.5 GB |

### 6.4 唤醒词 (Phase 4)

| 选项 | CPU 占用 | 自定义 | 许可 |
|------|---------|--------|------|
| **首选** | Porcupine (Picovoice) | <1% | 需要 Access Key |
| 开源 | OpenWakeWord | ~3% | 完全开源 |

---

## 7. 安全设计

### 7.1 认证

- OpenClaw Gateway：Token 认证 (Bearer token, auth token mode)
- UiHttpServer (:18802)：localhost only，无额外认证
- STT/TTS 服务：LAN 限制，可选 API Key
- 飞书/QQ：应用级 AppID/Secret 认证

### 7.2 网络隔离

- 所有服务绑定 LAN 地址，不暴露到外网
- 车机 → 开发机：仅开放必要端口 (8080, 8090, 8091)
- 开发机 → 外网：用于飞书/QQ/DeepSeek API 调用

### 7.3 数据隐私

- 语音数据在局域网内处理，不上传云端（除非选择云端 STT/TTS）
- 对话记录存储在车机本地
- 开发机不持久化语音数据

---

## 8. 部署拓扑演进

### Phase 1（基础）

```
[飞书 (内置插件)] → [车机 OpenClaw] → [开发机 MiniCPM]
```

### Phase 2（语音）

```
[车机麦克风] → [车机 OpenClaw] → [开发机 STT/LLM/TTS] → [车机扬声器]
```

### Phase 3（多通道）

```
[飞书/QQ/微信] ──→ [车机 OpenClaw] ──→ [开发机 STT/LLM/TTS]
[车机麦克风]   ──→                   ──→ [车机扬声器]
```

### Phase 4（声音克隆 + 音色控制）✓ Done

```
[App 音色/方言] → [TTS Adapter] → [VoxCPM2 ref_audio 克隆]
[SOUL.md 方言]  → [LLM 方言回复] → [TTS 方言前缀]
```

### Phase 4.5（主动关怀 + A2UI 卡片）✓ Done

```
[ProactiveFragment 选卡] → [SCENE.md] → [Agent 读场景]
  → [car-nav: 实际导航] + [关怀回复] + [A2UI 关怀卡片]
  → [GatewayClient JSONL poll] → [AGenUIFragment 渲染]
```

**已实现功能：**
- ProactiveFragment: 3 张预设场景卡片（宝宝熟睡/打疫苗后/哭闹），选卡写 SCENE.md
- 主动导航: Agent 必须实际调用 car-nav HTTP API 执行导航，不限于文字回复
- A2UI 关怀卡片(模板四): 宝宝状态 + 导航信息 + 关怀操作，三区域缺一不可
- GatewayClient: 增量 JSONL 行检测，parseLine 返回 boolean，不完整 JSON 不推进
- AGenUIFragment: cardJsonHistory 存 companion object，renderCard 不改 history，删除从 history 移除
- ProactiveFragment: 选卡状态从 SCENE.md 文件恢复（非内存 index）

**Ongoing work:**

- Feishu voice STT → LLM → TTS pipeline (飞书语音管道)
- Agent behavior tuning (SOUL.md / TOOLS.md / AGENTS.md workspace files)

### Phase 5（车机直连语音）

```
[车机麦克风] → [唤醒词] → [Voice Agent] → [OpenClaw] → [STT/LLM/TTS]
                                                          ↓ 流式
                                              [车机扬声器 ← Voice Agent]
```

---

## 9. 当前 TODO

### TODO-1：明确车机语音输入输出接口

**目标：** 确认车机（BYD · MTK 平台）的麦克风/扬声器硬件接口，为 Phase 5 Voice Agent 做准备。

**待确认项：**

| 项目 | 待确认内容 | 说明 |
|------|-----------|------|
| ALSA 设备 | `/dev/snd/` 下有哪些 PCM 设备 | 录音/播放各用哪个设备节点 |
| 音频 HAL | Android Audio HAL 实现方式 | MTK HAL / treble HAL |
| 麦克风 | 输入采样率、通道数、格式 | 预期 16kHz mono S16LE |
| 扬声器 | 输出采样率、路由策略 | 是否独占，与媒体播放冲突时如何处理 |
| 权限 | shell 用户能否访问 ALSA 设备 | 需要确认 `/dev/snd/` 权限 |
| AudioRecord API | 是否可通过 Android API 录音 | 非 ALSA 直连的备选方案 |
| AudioTrack API | 是否可通过 Android API 播放 | 流式播放的备选方案 |

**调研命令：**
```bash
# ALSA 设备列表
adb shell "ls -la /dev/snd/"
adb shell "cat /proc/asound/cards"
adb shell "cat /proc/asound/pcm"

# 平台信息
adb shell "getprop | grep -iE 'mtk|mediatek|platform'"
adb shell "getprop | grep -iE 'audio|media'"

# Audio HAL
adb shell "ls /vendor/lib*/hw/*audio*"

# Android API 测试（需写测试 App）
# AudioRecord(16000, MONO, PCM_16BIT)
# AudioTrack(24000, MONO, PCM_16BIT, STREAM)
```

### TODO-2：MTK 端侧模型部署

**目标：** 利用 MTK NPU 部署端侧小模型，将 LLM 延迟从 ~4.5s 降至 <1s。

**依赖：** 需要 MTK SDK（NeuroPilot / DLA）支持。

**待确认项：**

| 项目 | 待确认内容 | 说明 |
|------|-----------|------|
| NPU 型号 | MTK SoC 具体型号（天玑？） | 决定算力上限 |
| NeuroPilot SDK | 是否可获取 SDK 及文档 | MTK AI 推理框架 |
| 支持模型 | 支持哪些模型格式 | ONNX / TFLite / MTK 自有格式 |
| 算力 | NPU TOPS / 内存 | 决定可部署的模型规模 |
| 量化 | INT8 / INT4 支持 | 影响模型精度和大小 |
| 候选模型 | 可部署的 LLM/SLM | Qwen2-1.5B / MiniCPM 等 |

**预期架构变化：**

```
当前：[车机] → WiFi → [云端 LLM 4.5s]
未来：[车机 NPU 本地推理 <1s] + [云端 LLM 备用]
```

**时延预期：**
- 端侧 SLM（~1.5B 参数，INT4）：首 token <500ms，生成 ~50 token/s
- 结合流式 TTS：端到端有望降至 ~2-3s

---

## 10. App 合并说明

原 `caragent-app` (com.caragent.bootstrap) 已合并入 `agent_front_app` (com.openclaw.car)。所有服务迁移到 `com.openclaw.car.service` 包下：

| 旧路径 (com.caragent.bootstrap) | 新路径 (com.openclaw.car.service) |
|------|------|
| `.UiAutomationService` | `.service.UiAutomationService` |
| `.UiCommandReceiver` | `.service.UiCommandReceiver` |
| `.NodeProcessService` | `.service.NodeProcessService` |
| `.NodeProcessManager` | `.service.NodeProcessManager` |
| `.BootReceiver` | `.service.BootReceiver` |
| `.CommandReceiver` | `.service.CommandReceiver` |

### 广播目标变更

所有通过 `am broadcast` 控制 UI 自动化的 shell 脚本需更新接收器目标：

```bash
# 旧（已废弃）
am broadcast -n com.caragent.bootstrap/.UiCommandReceiver -a com.caragent.UI_CMD ...
# 新
am broadcast -n com.openclaw.car/.service.UiCommandReceiver -a com.caragent.UI_CMD ...
```

保持不变的部分：
- 广播 action: `com.caragent.UI_CMD` -- 不变
- ContentProvider authority: `com.caragent.bootstrap.uiresult` -- 不变
- 启停 action: `com.caragent.START` / `com.caragent.STOP` -- 不变

### 新增功能

- Production 模式下 App 启动自动启动 NodeProcessService
- Debug 模式底部状态栏显示 Gateway / Accessibility / TTS 连接状态
- 音色预设从 4 个扩展到 7 个（新增 特朗普、林志玲、雷军）
- 音色选择 UI 从 2x2 按钮网格改为可滚动 RecyclerView 列表

---

## 11. OpenClaw Workspace 文件

OpenClaw agent 启动时从 `.openclaw/workspace/` 加载配置文件，定义 agent 人格、工具、规则和记忆。

### 11.1 Workspace 文件结构

| 文件 | 用途 | 说明 |
|------|------|------|
| `SOUL.md` | 人格 + 行为规则 | persona 定义、reply rules、memory rules、当前车辆环境上下文 |
| `TOOLS.md` | 工具使用规则 | 车辆环境信息、工具调用规则和约束 |
| `AGENTS.md` | 硬性约束 + A2UI模板 + 主动关怀规则 | 禁止 web_search、禁止捏造命令、4个 A2UI 卡片模板、主动关怀(场景感知+导航+宝宝状态)、主动导航规则(3场景→实际API调用)、记忆持久化 |
| `MEMORY.md` | 用户偏好记忆 | 用户偏好、地址、习惯等持久化信息 |

### 11.2 Skills

| Skill | 用途 | 说明 |
|-------|------|------|
| `car-nav` | 导航控制 | 通过 BYD Map Protocol SDK 直接 binder 调用（非 car-router） |
| `car-music` | 音乐控制 | 通过 AUTOVOICE 广播控制 BYD mediacenter（搜索/播放/暂停/切歌/音量），无需 mediacenter 在前台 |
| `car-poi` | POI 搜索 | 兴趣点搜索，结合地图 SDK |

Social skills (飞书等 IM 交互) 也由 OpenClaw 内置插件管理。

### 11.3 agent_front_app HTTP API (UiHttpServer :18802)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/navigate` | POST | 导航到指定目的地（通过 MapProtocolManager → BYD Map SDK） |
| `/music/play` `/music/pause` `/music/next` `/music/previous` | POST | 音乐传输控制（`MusicController` → `BydMusicController` 广播 `AUTOVOICE_COMMON_CONTROL`） |
| `/music/search` | POST | 搜索并播放（广播 `AUTOVOICE_COMMON_OPERATION` `searchMusic`） |
| `/music/volume` | POST | 音量 up/down/set（`AudioManager`） |
| `/music/state` | POST | 读 `/data/local/tmp/music-state.json`（music-monitor.sh 写入） |
| `/poi/search` | POST | POI 搜索 |
| `/location` | GET | 返回 GPS 坐标（从 /data/local/tmp/gps.json 读取） |

### 11.4 GPS 监控

```
SomeIP logcat → gps-monitor.sh 解析坐标
  → /data/local/tmp/gps.json
  → UiHttpServer /location endpoint
```

`gps-monitor.sh` 持续监听 logcat 中的 SomeIP GPS 消息，解析经纬度写入 `gps.json`，供 `/location` 端点读取。

---

*Last updated: 2026-06-12*
