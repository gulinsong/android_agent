# 豆包 Realtime 闲聊 App 设计

- 日期：2026-06-24
- 状态：已通过 brainstorming，待 review
- 参考实现：`workspace/realtime_dialog_ref/java/src/main/java/com/volcengine/realtimedialog/`（火山官方 Java demo）
- API 文档：https://www.volcengine.com/docs/6561/1594356

## 1. 目标与范围

**目标**：在 BYD 车机上做一个**独立的 Android app**，用豆包端到端实时语音大模型（Realtime API）实现纯语音闲聊（陪聊/人设/解闷），与车机主 agent（`agent_front_app`）完全隔离、互不依赖。

**核心交互**：app 打开即 always-on 持续对话，前台独占麦克风，服务端 VAD 自动检测说话开始/结束，用户随时可插话打断。

**非目标（YAGNI）**：
- 不做 function calling / skill 调用（Realtime API 原生不支持；工具型能力仍归 deepseek 主 agent）。
- 不做后台常驻录音（仅前台 Activity 时录音）。
- 不做音色克隆、唱歌、外部 RAG、联网搜索（API 支持但非 MVP 范围）。
- 不集成进 `agent_front_app`，是独立工程。

## 2. 决策摘要

| 维度 | 定案 |
|---|---|
| 形态 | 独立 Android app（Kotlin），工程目录 `doubao_chitchat/`（项目根下，与 `agent_front_app` 平级） |
| 设备 | BYD 车机 |
| 功能 | 纯语音闲聊（豆包 Realtime，不调 skill） |
| 交互 | Always-on，server VAD（`end_smooth_window_ms` 默认 1500ms），前台独占麦克风 |
| 模型版本 | O2.0，`model = "1.2.1.1"` |
| 人设 | 自定义车载语音伙伴（`system_role`），`UpdateConfig(201)` 预留热切接口 |
| 音色 | 默认 `zh_female_vv_jupiter_bigtts`（vv） |
| 音频格式 | 上行 PCM 16kHz/mono/int16 小端；下行请求 `pcm_s16le` 24kHz/mono（免 Opus 解码） |
| WS | OkHttp 4.12.0（主 app 已用），`okhttp3.WebSocket` |
| JSON | Gson（弃 demo 的 jackson） |
| 异步 | Kotlin 协程 + Channel（替 demo 的 Thread/BlockingQueue） |
| UI | 单 Activity + ViewModel + 传统 View（与主 app 一致，不上 Compose） |

## 3. 架构与工程结构

新建独立 Gradle 工程 `doubao_chitchat/`：

```
doubao_chitchat/
├── settings.gradle.kts
├── build.gradle.kts
└── app/
    ├── build.gradle.kts        # minSdk 26, targetSdk 34, OkHttp 4.12, Gson, coroutines
    └── src/main/
        ├── AndroidManifest.xml # RECORD_AUDIO + INTERNET
        └── java/com/openclaw/chitchat/
            ├── Protocol.kt          # 二进制帧（移植自 demo Protocol.java）
            ├── RealtimeClient.kt    # OkHttp WebSocket + 事件分发（替 demo NetClient）
            ├── CallManager.kt       # 会话状态机（移植 + 修正打断/错误/model）
            ├── AudioRecorder.kt     # AudioRecord 16kHz/mono/int16（替 demo AudioCapture）
            ├── AudioPlayer.kt       # AudioTrack 24kHz/mono/s16le + 打断（替 SourceDataLine）
            ├── Config.kt            # 鉴权 + 音频参数 + payload data class
            └── ui/
                ├── ChitchatActivity.kt     # 极简全屏：状态 + 实时字幕 + 录音指示
                └── ChitchatViewModel.kt    # 把 CallManager 状态映射到 UI
```

**demo → Android 模块映射**：

| demo 文件 | Android 对应 | 移植改动 |
|---|---|---|
| `Protocol.java` | `Protocol.kt` | 几乎原样，纯字节操作；kotlin 化 + data class |
| `NetClient.java`（Java-WebSocket） | `RealtimeClient.kt` | WS 引擎换 OkHttp `WebSocketListener`；header 在 `Request.Builder` 加 |
| `CallManager.java` | `CallManager.kt` | 移植 + 修正打断/model/错误；协程化 |
| `AudioCapture.java`（javax.sound） | `AudioRecorder.kt` | `TargetDataLine` → `AudioRecord`，20ms/640B 包 |
| `SourceDataLine` 播放（NetClient 内） | `AudioPlayer.kt` | → `AudioTrack` + 播放队列 + `flush()` 打断 |
| `RequestPayloads.java` | `Config.kt` | data class，`model` 改 `1.2.1.1` |
| `ServerResponseHandler.java` | 并入 `CallManager`/`RealtimeClient` | 事件分发 + 打断 + 重连 |
| `Main.java`（命令行） | `ChitchatActivity` | UI 入口替命令行 |

## 4. 二进制协议层（`Protocol.kt`）

帧 = **4 字节 header + optional 字段 + payload**，全程**大端序**。

header 每字节高低 4 位：

| byte | 高 4 位 | 低 4 位 |
|---|---|---|
| 0 | Version `0b0001` | HeaderSize `0b0001` → `0x11` |
| 1 | MessageType | TypeFlags |
| 2 | Serialization（`RAW=0` / `JSON=1`） | Compression（`NONE=0` / `GZIP=1`） |
| 3 | `0x00` reserved |

- MessageType：`FULL_CLIENT=1` / `AUDIO_ONLY_CLIENT=2` / `FULL_SERVER=9` / `AUDIO_ONLY_SERVER=11` / `ERROR=15`
- TypeFlags：`WITH_EVENT=0b0100`（带 event 时必设）

**optional 字段必须严格按序**（漏/乱会导致服务端解析失败）：

```
event(4B) → sessionId(4B长度+UTF8) → connectId(4B长度+bytes) → sequence(4B) → errorCode(4B) → payload(4B长度+bytes)
```

规则（已在 demo `Protocol.java` 验证）：
- `event`：仅当 TypeFlags 含 `WITH_EVENT`
- `sessionId`：仅当事件 **不是** `1/2/50/51/52`
- `connectId`：仅当事件 **是** `50/51/52`（本项目 Connect 类事件用不到）
- `errorCode`：仅当 `type == ERROR`

两个 marshal 路径：
- 文本事件：`marshal()`，serialization = JSON
- 音频帧：`marshalRawAudio()`，serialization = RAW，event = 200，payload = 原始 PCM 字节

接口（design 层签名，实现细节见后续 plan）：

```kotlin
enum class MsgType(val bits: Int) { FULL_CLIENT(1), AUDIO_ONLY_CLIENT(2),
    FULL_SERVER(9), AUDIO_ONLY_SERVER(11), ERROR(15) }

data class Message(var type: MsgType, var typeFlag: Int, var event: Int,
                   var sessionId: String?, var connectId: String?,
                   var sequence: Int, var errorCode: Long, var payload: ByteArray?)

fun marshal(msg: Message): ByteArray           // 文本事件
fun marshalRawAudio(msg: Message): ByteArray   // 音频帧
fun unmarshal(data: ByteArray): Message

fun startConnection(): ByteArray                       // event=1, payload="{}"
fun startSession(sid: String, json: String): ByteArray // event=100
fun audioFrame(sid: String, pcm: ByteArray): ByteArray // event=200, RAW
fun eventMessage(sid: String, json: String, event: Int): ByteArray // 通用 300/102/201…
fun generateSessionId(): String                        // UUID
```

## 5. 音频管线

```
麦克风 → AudioRecord(16kHz/mono/int16) → 每20ms读640B → audioFrame(sid,pcm) → WS上行(200)
                                                                          ↓
扬声器 ← AudioTrack(24kHz/mono/s16le) ← playbackChannel ← TTSResponse(352) ← WS下行
                    ↑
              [ASRInfo(450)打断: channel清空 + AudioTrack.pause()+flush()]
```

- **录音** `AudioRecorder`：`AudioRecord(MIC, 16000, MONO, PCM_16BIT, bufMin)`，协程循环 `read(buf, 0, 640)` → 经 `Channel<ByteArray>` 喂发送协程；20ms 节流（对齐 demo `AUDIO_SEND_INTERVAL`）。640B = 16000 × 0.02 × 2。
- **播放** `AudioPlayer`：`AudioTrack(24000, MONO, PCM_16BIT, buf, MODE_STREAM)`，从 `playbackChannel` 收 PCM 块 `write()`。输出格式在 StartSession 的 `tts.audio_config` 指定 `pcm_s16le`，**免去 Opus 解码**。
- **打断（关键修正，demo 缺）**：收到 `ASRInfo(450)` = 用户开口 → 关闭并重建 `playbackChannel`（清空排队 TTS）+ `AudioTrack.pause(); flush()` 立即静音。

## 6. 事件状态机（`CallManager.kt`）

**状态枚举**：`IDLE → CONNECTING → SESSION_READY → LISTENING ⇄ USER_SPEAKING ⇄ ASSISTANT_SPEAKING → FINISHING`

**连接阶段**（启动一次性）：

```
connect WS（带 4 个鉴权 header + X-Api-Connect-Id=sessionId）
  → 发 StartConnection(1)        → 等 ConnectionStarted(50)
  → 发 StartSession(100, payload)→ 等 SessionStarted(150)，拿 dialog_id
  → 发 SayHello(300, "你好…")     → 模型主动开口（开场白 TTS 播放）
  → 启动录音上传（200 循环）
```

**对话循环**（always-on 自动往复）：

| 服务端事件 | 含义 | 客户端动作 |
|---|---|---|
| `ASRInfo(450)` | 用户开口（首字） | **打断播放** + 置 USER_SPEAKING |
| `ASRResponse(451)` | 识别文本（流式） | 刷新 UI 字幕 |
| `ASREnded(459)` | 用户说完 | 置 LISTENING，等模型回复 |
| `TTSSentenceStart(350)` | 模型开始回 | （可选）清旧字幕，置 ASSISTANT_SPEAKING |
| `TTSResponse(352)` | 模型音频块 | 入 `playbackChannel` 播放 |
| `TTSEnded(359)` | 一轮回复完 | 回到 LISTENING |

**结束**：Activity onPause → 停录音 → 停播放 → `FinishSession(102)` → 等 `SessionFinished(152)` → close WS。（文档强调：发完 102 收到回复再断，否则 `55000001 ContextCanceled`。）

**StartSession payload 规范（O2.0）**：

```kotlin
dialog {
  bot_name: "<≤20字>",
  system_role: "<车载语音伙伴人设>",
  speaking_style: "<口吻>",
  dialog_id: "",                  // 由 150 返回赋值
  extra {
    model: "1.2.1.1",             // 修正点：demo 写 "O"，改用规范版本号
    input_mod: "audio",           // 沿用 demo 默认麦克风流式值；文档枚举未列但实测有效，报错则改不传走默认
    strict_audit: false
  }
}
tts {
  speaker: "zh_female_vv_jupiter_bigtts",
  audio_config { channel: 1, format: "pcm_s16le", sample_rate: 24000 }
}
asr { extra {} }                  // 用默认 server VAD
```

## 7. 权限 / 音频焦点 / 生命周期

- **权限**：`RECORD_AUDIO` + `INTERNET`。运行时申请 `RECORD_AUDIO`。
- **BYD 多用户录音坑**：车机 `RECORD_AUDIO` 可能因多用户机制不直接生效，装上后需 `adb pm grant` 恢复（沿用 [[car-reinstall-checklist]] 现有命令，列为部署 checklist，不在 app 内硬扛）。
- **不做前台服务**：仅前台 Activity 时录音，`onPause` 即释放麦克风（无需常驻通知，也避免与主 agent 后台冲突）。
- **音频焦点**：`onResume` 时 `AudioManager.requestAudioFocus`(USAGE_ASSISTANT)，`onPause` 时 `abandonAudioFocus`，避免与主 agent 叠音。
- **Activity 生命周期驱动会话**：

| 回调 | 动作 |
|---|---|
| `onCreate` | 初始化组件，检查/申请权限 |
| `onResume` | 建 WS → StartConnection → StartSession → SayHello → 启动录音（前台独占） |
| `onPause` | 停录音 → 停播放 → FinishSession(102) → 收 152 后 close WS → 释放麦克风 |
| `onDestroy` | 释放 AudioRecord/AudioTrack |

## 8. 错误处理 + 重连

| 错误 | 来源 | 处理 |
|---|---|---|
| `ConnectionFailed(51)` / `SessionFailed(153)` | 事件 | UI 提示 + 指数退避重连（1s→2s→4s，上限 3 次） |
| `5xxxxxx`（推理/服务端错） | 事件/错误码 | 文档明确建议重连，同上退避 |
| `45000003` 静音 >10 分钟 | 服务端释放连接 | 视为断连，重新 StartConnection→StartSession |
| `55000001 ContextCanceled` | 未正常 FinishSession | 修正关闭流程：发 102 等 152 再 close |
| `52000042` 静音补包错 | 文档 | `input_mod=audio` 不补静音，理论不触发；触发则降级重连 |
| `42000020` payload 配置错 | 文档 | 检查 StartSession 构造（asr.extra/tts.extra 非空） |
| OkHttp `onFailure`/`onClosing` | WS 层 | 走重连流程 |

重连期间 UI 显示「重连中…」，超上限显示「连接失败，点此重试」。重连**复用 sessionId/dialog_id** 走 StartSession，尽量接续上下文。

## 9. 关键修正点（vs 官方 demo，直接抄会踩坑）

1. **`model` 字段**：demo `CallManager.createExtraMap` 写 `model:"O"`（旧别名），改用文档规范 `"1.2.1.1"`（O2.0）。
2. **打断不完整**：demo `ServerResponseHandler` case 450 只清「保存缓冲」(`audioData`)，没清「播放队列」(`NetClient.audioQueue`) 也没停播放器 → 补：清播放 Channel + `AudioTrack.pause()/flush()`。
3. **错误处理粗暴**：demo `System.exit(1)` → 改优雅降级 + 指数退避重连。
4. **JSON 库**：demo jackson → Gson。
5. **WS 引擎**：demo Java-WebSocket → OkHttp。
6. **音频层**：demo javax.sound（SourceDataLine/TargetDataLine）→ Android AudioTrack/AudioRecord。

## 10. 测试与成功标准

**单元测试**（`Protocol.kt`，用文档/demo 真实字节 fixture）：
- StartConnection 帧 `[17,20,16,0,0,0,0,1,0,0,0,2,123,125]`（末尾 `123,125`=`{}`）
- StartSession 帧（demo 中 sessionId=`75a6126e-...` 的示例数组）
- TTSResponse 帧（文档服务端示例）
- 断言 marshal→unmarshal round-trip 一致；`marshalRawAudio` 字节对齐。

**集成/端到端**（BYD 真机）：
1. 打开 app → 模型开口（SayHello 开场白播放）
2. 用户说话 → 实时字幕（ASRResponse）→ 模型语音回复（TTSResponse）
3. 模型说话时插话 → 立即打断（ASRInfo→flush）
4. 连续 5+ 轮稳定对话
5. 量**首响延迟**（用户说完 → 模型首个 TTSResponse），跟 VoxCPM2 的 561–638ms 横向对比

**MVP 成功标准**：①~⑤ 全通 + 无崩溃跑 10 分钟。

## 11. 部署 checklist（BYD 车机）

1. `adb install` 安装 app
2. `adb pm grant <pkg> android.permission.RECORD_AUDIO`（BYD 多用户权限恢复，参考 [[car-reinstall-checklist]]）
3. 确认车机能访问 `openspeech.bytedance.com`（已验证公网通）
4. 填入 App ID / Access Key（已就绪）

## 12. 后续迭代（非 MVP）

- 音色热切 UI（`UpdateConfig(201)`，全量覆盖）
- 人设多套预设切换（`system_role` 热切）
- `enable_conversation_truncate` + `dialog_id` 长记忆召回
- 录音文件/纯文本输入模式（`input_mod`）
- `enable_loudness_norm` 响度均衡
