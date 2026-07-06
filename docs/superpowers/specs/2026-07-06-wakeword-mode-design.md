# 唤醒词模式设计（"你好小迪"）

- **日期**：2026-07-06
- **状态**：Draft（待复核）
- **范围**：`agent_front_app` 车机语音 agent
- **关联代码**：`FloatingBubbleService.kt`、`AudioRecorder.kt`、`sendAudioToGateway()`

---

## 1. 背景

现有语音输入为**按键录音（PTT）模式**：单击悬浮球应用图标（`FloatingBubbleService.kt:368-375`）切换 `startRecording()`/`stopRecording()`，整段 m4a POST 到 FunASR(`8090`) → Gateway LLM(`18801`) → TTS(`8091`) → 播放。驾驶场景下需要用户伸手点屏幕，既不安全也不自然。

## 2. 目标

把主交互升级为**唤醒词模式**：

- 用户说**"你好小迪"**即进入对话，支持连续多轮追问（不必重复唤醒）。
- AI 用 TTS 说话时，用户可以插嘴打断（**barge-in**）。
- **按键模式作为 fallback 完整保留**，两种模式可切换，默认唤醒词模式。
- 唤醒词检测**端侧离线**完成（sherpa-onnx），不依赖网络。

## 3. 非目标（YAGNI）

- 不做声纹/说话人识别（已有独立 FaceID 方案）。
- 不做多唤醒词、多用户语音 profile。
- 不做云端唤醒（端侧 KWS 已定）。
- 不做熄屏智能暂停 KWS 的调度（MVP 熄屏继续，后续开关）。
- 不重训 KWS 模型（用预训练 `zh-15M` + open vocabulary 关键词直接指定"你好小迪"）。
- 不做 AEC 之外的专业回声消除硬件适配（单麦 + 软件 AEC 够用）。

## 4. 现状分析（接入点）

| 环节 | 文件:行 | 说明 |
|---|---|---|
| UI 触发 | `FloatingBubbleService.kt:368-375` | `btn_app_icon` 单击切换录音开始/停止 |
| 录音器 | `AudioRecorder.kt:9-92` | `MediaRecorder` 16kHz AAC，整段 m4a 到 `cacheDir` |
| 开始录音 | `FloatingBubbleService.kt:494-523` | 先 `stopTtsAndFiller()` 再 `AudioRecorder.start()` |
| 停止录音 | `FloatingBubbleService.kt:525-549` | `recorder.stop()` → `sendAudioToGateway()` |
| ASR 上行 | `FloatingBubbleService.kt:700-737` | m4a multipart POST FunASR，解析 `text` |
| 打断 TTS | `FloatingBubbleService.kt:558-562` | `stopTtsAndFiller()`：掐 streaming/file/filler，音乐不掐 |
| 状态变量 | `FloatingBubbleService.kt:100` | 仅 `isRecording: Boolean`，无正式状态机 |
| BYD 助手禁用 | `VoiceAssistantManager.kt:8-55` | `am force-stop` 禁用 BYD 自带助手（避免"你好小迪"冲突） |

**关键事实**：`AudioRecorder` 是 `MediaRecorder` 文件式，而 KWS/VAD 需要流式 PCM（`AudioRecord`）——因此新增连续采集器，按键模式的 `AudioRecorder` 链路**保持不动**。`sendAudioToGateway()` 之后的 ASR→LLM→TTS 链路两种模式共用，零改动。已有依赖 `onnxruntime-android:1.18.0` + NeuroPilot APU（人脸识别在用），KWS 可复用同一推理栈。

## 5. 总体设计

### 5.1 端到端数据流

```
【唤醒词模式 · 默认】
ContinuousAudioCapture (AudioRecord 16kHz PCM 流)
   ├─→ WakeWordEngine (KWS) 持续吃 PCM，匹配 "你好小迪"
   │       ↓ 命中
   │   WakeWordController: 进对话窗口 + 播 "叮" 提示音
   │       ↓
   └─→ VoiceActivityDetector (Silero VAD) 切段：说话开始 / 静音结束
           ↓ 一段完整话语 (PCM)
       PcmToM4a.encode() → sendAudioToGateway() → FunASR → Gateway LLM → TTS
           ↓ AI 回复播放中
       VAD 继续跑做 barge-in：用户开口 → stopTtsAndFiller() → 新一段
           ↓ 对话窗口内 10s 无活动
       回 IDLE_LISTENING (待机听唤醒词)

【按键模式 · fallback，完全不动】
单击悬浮球 → AudioRecorder (MediaRecorder m4a) → stop → sendAudioToGateway()
```

**关键不变量**：`sendAudioToGateway()` 之后的 ASR→LLM→TTS 链路两种模式共用，零改动。

### 5.2 状态机

```
IDLE_LISTENING ──(KWS 命中 "你好小迪")──→ WAKE_CONFIRMED
   ↑                                         │ (播提示音 + grace period 1.5s)
   │                                         ▼
   │ (10s 无活动)                       DIALOG_WINDOW
   │                                         │
   │                                   ┌─────┴─────┐
   │                             RECORDING     AI_SPEAKING
   │                           (VAD 切段→ASR)  (TTS 播放,
   │                               │            VAD 监听 barge-in)
   │                               │            │ 用户开口 → stopTts → RECORDING
   │                               │            │ TTS 结束 → RECORDING (等下一句)
   │                               ▼            │
   │                           (循环追问)       │
   └───────────────────────────────────────────┘
```

**各状态的麦克风/检测器开关**：

| 状态 | KWS | VAD | 麦克风 | TTS |
|---|---|---|---|---|
| `IDLE_LISTENING` | ✅ 跑 | ❌ | 连续采集 | 可播（主动关怀） |
| `WAKE_CONFIRMED` | ⏸ | ⏸（grace 期内监听是否有语音） | 采集 | 提示音 |
| `DIALOG_WINDOW·RECORDING` | ⏸ | ✅ 切段 | 采集 | 停 |
| `DIALOG_WINDOW·AI_SPEAKING` | ⏸ | ✅ barge-in | 采集 | 播放 |

**重要决策**：KWS 只在 `IDLE_LISTENING` 跑，对话窗口内**不再听唤醒词**（避免 TTS/用户说话误触发）。退出对话窗口靠：①静默超时（默认 10s）②用户说"退出/结束对话"（LLM 意图）③悬浮球手动。架构上预留"对话窗口内喊唤醒词=刷新超时"的扩展点，MVP 不做。

### 5.3 模块拆分

**新增**（`com.openclaw.car.wakeword` 包）：

| 类 | 职责 | 关键接口 |
|---|---|---|
| `ContinuousAudioCapture` | `AudioRecord` 16kHz/16bit 单声道 PCM 流，**单例**，多消费者订阅 | `start()` / `stop()` / `subscribe(listener) -> handle` / `unsubscribe(handle)` / `setConsumer(tag)` |
| `WakeWordEngine` | 封装 sherpa-onnx `KeywordSpotter`，加载中文 KWS 模型 | `init(modelPath, keyword)` / `feed(samples: ShortArray): Boolean` |
| `VoiceActivityDetector` | 封装 sherpa-onnx Silero VAD，pre-speech padding 防开头被切 | `feed(samples)` → 回调 `onSpeechStart` / `onSpeechEnd(pcmSegment: ShortArray)`；支持切段/barge-in 两套参数 |
| `WakeWordController` | 状态机持有者，协调上面三者 + 调 `FloatingBubbleService` 走 ASR/LLM/TTS | `onWakeWordHit()` / `onSpeechSegment(pcm)` / `onDialogTimeout()` / `setMode(mode)` |
| `PcmToM4a` | `MediaCodec` AAC 编码，复用现有采样率/码率 | `encode(pcm: ShortArray, sampleRate): ByteArray` |
| `InteractionMode`（enum） | `WAKE_WORD` / `BUTTON`，SharedPreferences 持久化 | `WAKE_WORD` / `BUTTON` / `persist()` / `current()` |

**修改**：

- `FloatingBubbleService.kt`：`btn_app_icon` 单击按 `InteractionMode` 分流——`BUTTON` 走现有 `startRecording/stopRecording`（不动）；`WAKE_WORD` 改为"强制打断 TTS / 收起悬浮栏"（不再触发录音）。启动时按模式初始化 `WakeWordController`。
- `sendAudioToGateway()`：新增重载，接受 `ByteArray`（已是 m4a）直接走原逻辑；VAD 切段路径先 `PcmToM4a.encode()` 再调它。
- `AudioRecorder.kt`：**不动**（按键模式专用）。
- `MainActivity.kt`：首页加一个模式切换按钮（读/写 `InteractionMode`，点击切换并触发 `WakeWordController.setMode()`）。
- `app/build.gradle.kts`：加 sherpa-onnx AAR + 模型 assets 配置。

### 5.4 音频调度与 barge-in

#### 5.4.1 一个采集器，按状态分发

`ContinuousAudioCapture` 单例（避免重复抢麦），内部专用线程循环 `AudioRecord.read()`，每帧 512 samples（16kHz → 32ms）。谁吃这帧由 `WakeWordController` 按当前状态决定：

```
IDLE_LISTENING          → 帧喂 WakeWordEngine.feed()
DIALOG·RECORDING        → 帧喂 VoiceActivityDetector.feed()（切段模式参数）
DIALOG·AI_SPEAKING      → 帧喂 VoiceActivityDetector.feed()（barge-in 模式参数）
```

KWS 和 VAD **绝不同时吃**，状态切换时清空对方的内部 buffer。

#### 5.4.2 barge-in 防误判（三道保险 + 降级开关）

TTS 播放时扬声器声会被麦克风收到，需区分它和真人插话：

| 保险 | 做法 | 收益 |
|---|---|---|
| ① Android AEC | `AudioRecord` 创建后挂 `AcousticEchoCanceler`，能开就开 | 系统级消除直接耦合，车机单麦效果有限但白捡 |
| ② 动态基线 | TTS 播放开始头 300ms 测 TTS 漏音能量基线，barge-in 阈值 = 基线 × 1.5 + margin | 自适应不同音量/车型 |
| ③ 防抖 | Silero VAD 连续 ≥8 帧（~256ms）判定为语音才触发，单帧尖峰忽略 | 过滤 TTS 短促爆破音 |

**降级开关**：`barge_in_mode = AEC_VAD | VAD_ONLY | HALF_DUPLEX`。三道全失效时切 `HALF_DUPLEX`（AI 说话时关 VAD，说完才听）。

#### 5.4.3 VAD 切段 → 复用现有 ASR 链路

`onSpeechEnd(pcmSegment)` 回调：

```
pcmSegment (ShortArray)
  → PcmToM4a.encode()
  → sendAudioToGateway(m4a, durationMs)   // 现有方法，零改动
  → responseWatchdog.arm()                 // 现有 filler 兜底
  → 状态切 AI_SPEAKING
```

pre-speech padding（sherpa-onnx VAD 自带）保证开头字不被切掉。

#### 5.4.4 与现有打断逻辑协调

barge-in 触发 → 调现有 `stopTtsAndFiller()`（掐 streaming/file/filler，音乐不掐）→ 状态切 `RECORDING`。**完全复用，不新写一套**。

#### 5.4.5 关键不变量（验收点）

- 同一时刻只有一个 PCM 消费者（KWS 或 VAD），切换时清 buffer。
- `AudioRecord` 全程单例一份；按键模式的 `MediaRecorder` 是独立链路，用 `AudioFocus` 互斥（按键录音时暂停 KWS 采集）。
- AEC 挂载失败不阻断启动，降级到纯阈值 barge-in。

### 5.5 模式切换与配置

- **`InteractionMode`**：`WAKE_WORD` / `BUTTON`，SharedPreferences 持久化，默认 `WAKE_WORD`。
- **切换入口**：在 **`MainActivity`（app 首页）加一个模式切换按钮**（图标按钮或 `ToggleButton`，显示当前模式，点击切换）。简单直观，MVP 用这一个入口即可。语音命令切换（"切换按键模式"）作为可选增强，非 MVP。
- **切换语义**：停当前模式采集 + 复位状态机 + 按新模式重启 `WakeWordController`；按钮 UI 即时反映新模式。
- **可调配置**（SharedPreferences，均给默认值，开发者调参）：唤醒词文本（"你好小迪"）、对话窗口静默超时（10s）、barge-in 阈值 margin、grace period（1.5s）、提示音开关、`barge_in_mode`。
- **BYD 小迪冲突前置校验**：每次进 `WAKE_WORD` 模式时，`VoiceAssistantManager` 主动 `force-stop` 一次 BYD 助手并 logcat 校验，确保不双触发。

### 5.6 错误处理与边界

| 场景 | 处理 |
|---|---|
| 误唤醒 | `WAKE_CONFIRMED` 后 grace period 1.5s 内 VAD 未检测到人声 → 静默回 `IDLE_LISTENING`（不打扰） |
| ASR 空/失败 | 现有 `sendAudioToGateway` 已 `return@Thread`；对话窗口继续，重置超时计时 |
| KWS 模型加载失败 | 降级到 `BUTTON` 模式 + Toast 提醒 |
| 麦克风被占用（车机通话） | `AudioRecord.start` 失败 → 退 `IDLE_LISTENING` + 指数退避重试 |
| 录音权限缺失 | 启动检查，缺则提示授权（复用现有权限恢复流程） |
| barge-in 误判失控 | 切 `HALF_DUPLEX` 模式 |
| 耗电 | KWS 走 NNAPI EP 上 APU；MVP 熄屏继续，后续可加"熄屏暂停"开关 |
| APK 体积 | zh-15M（~40MB）+ silero_vad（~2MB）打包进 assets，不做首启下载 |

### 5.7 依赖与构建

- `app/build.gradle.kts`：引入 **sherpa-onnx Android AAR**。
- **KWS 模型**：`sherpa-onnx-kws-zipformer-zh-15M-2024-04-09`（纯中文 15M 参数，准确率优先）。具体模型名以实现时官方页面为准。
- **VAD 模型**：`silero_vad.onnx`（~2MB）。
- **模型放置**：`app/src/main/assets/wakeword/`，模型**不入 git**（参考人脸模型策略），README 写明下载源与 `adb push` 路径。
- **ABI**：arm64-v8a（车机匹配）。

## 6. 测试策略

- **单元（JVM）**：`PcmToM4a` 编码正确性、状态机状态转换表（mock KWS/VAD）、`InteractionMode` 持久化 round-trip、VAD 段切割（喂固定 wav fixture 断言切点）。
- **集成（instrumented）**：`WakeWordEngine` 加载真实模型 + 喂含"你好小迪"的 wav fixture → 命中；三道 barge-in 保险各一个用例（AEC 挂载、基线校准、防抖计数）。
- **车机实测**：误唤醒率（静音 + 播音乐各 1 小时）、唤醒命中率（10/10）、barge-in 成功率、熄屏 1 小时功耗、APK 体积增量。
- **BYD 共存实测**：禁用 BYD 助手后喊"你好小迪"只触发本 app，不弹 BYD 界面。

## 7. 验收标准

1. 默认 `WAKE_WORD` 模式下，说"你好小迪"在 1 秒内进入对话窗口并播提示音。
2. 对话窗口内连续追问 3 轮，无需重复唤醒词。
3. AI 说话时用户开口，TTS 在 300ms 内被掐断并进入新一轮录音（barge-in）。
4. 静默 10s 后自动退出对话窗口回待机。
5. 误唤醒率：静音环境 1 小时 ≤ 2 次；播音乐环境 1 小时 ≤ 5 次。
6. 语音命令"切换按键模式"后，单击悬浮球恢复按键录音行为，端到端可用。
7. BYD 助手禁用生效，"你好小迪"不触发 BYD 原生语音界面。
8. KWS 模型加载失败时自动降级按键模式并 Toast 提示，不崩溃。

## 8. 风险与开放问题

| 风险 | 影响 | 缓解 |
|---|---|---|
| **onnxruntime 版本冲突**：sherpa-onnx 内嵌 onnxruntime，与现有 `1.18.0`（人脸识别用）可能冲突 | 高，阻塞集成 | 实现第一周 spike：优先用 sherpa-onnx 预编译 AAR，必要时强制对齐版本或排除其一 |
| **sherpa-onnx Android 分发方式不确定**（maven vs 源码编 AAR） | 中 | spike 阶段确认官方 `android/` 目录或 jitpack，优先预编译 AAR 放 `app/libs/` |
| **BYD 助手禁用不稳定**导致"你好小迪"双触发 | 中 | 每次进唤醒词模式主动 `force-stop` + logcat 校验；长期考虑改唤醒词 |
| **单麦 AEC 效果有限**导致 barge-in 误判 | 中 | 三道保险 + `HALF_DUPLEX` 降级开关 |
| **APK 体积 +40MB** | 低 | 车机存储不紧，可接受；后续可改首启下载 |
| **熄屏持续 KWS 耗电** | 低 | MVP 接受，留"熄屏暂停"开关 |

## 9. 参考资料

- [sherpa-onnx Keyword Spotting 文档](https://k2-fsa.github.io/sherpa/onnx/kws/index.html)
- [sherpa-onnx KWS 预训练模型](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html)
- [sherpa-onnx VAD（Silero）文档](https://k2-fsa.github.io/sherpa/onnx/vad/index.html)
- [sherpa-onnx GitHub](https://github.com/k2-fsa/sherpa-onnx)
- [sherpa-onnx VAD pre-speech padding（issue #3035）](https://github.com/k2-fsa/sherpa-onnx/issues/3035)
