# Phase B1: App 直连 Adapter 流式 TTS 播放

**日期**: 2026-06-15
**前置**: Phase A 完成（adapter.py 加流式分支，TTFB 561ms 实测）
**范围**: 只改 PPT 录音路径，BYD ASR 路径不动

## 目标

让 PPT 录音场景下，用户从说完话到听到首字的时间从 ~2.5s（含 ASR+LLM+TTS 全算完）降到 ~1.5s。利用 Phase A 已打通的 adapter 流式接口（TTFB 561ms），用 AudioTrack 边收边播 PCM。

## 不在范围内

- BYD ASR 路径流式（走 gateway，需 B2）
- gateway TTS pipeline 改造（需 B2）
- 音质优化、声学处理

## 架构

### 当前 PPT TTS 路径

```
PPT 录音
 → sendAudioToGateway(wav)
 → ASR (172.20.10.5:8090)
 → Gateway (127.0.0.1:18801) 拿 LLM reply
 → POST adapter /v1/audio/speech (同步等)
 → 拿完整 audio bytes
 → 写临时 mp3 文件
 → MediaPlayer 播放
```

瓶颈：adapter 同步等完整音频生成 (~1.2s)，MediaPlayer 必须等文件写完。

### Phase B1 新路径（feature flag 开启时）

```
PPT 录音
 → sendAudioToGateway(wav)
 → ASR
 → Gateway 拿 LLM reply
 → if (streamTtsEnabled):
     StreamingTtsPlayer.playStream(replyText)
       → POST adapter /v1/audio/speech {"stream":true, "response_format":"pcm"}
       → OkHttp stream 读 PCM chunk
       → AudioTrack.MODE_STREAM 边收边播
       → 首个 chunk write 时 → responseWatchdog.cancel()
   else:
     老路径不动
```

## 组件

### 新建：`audio/StreamingTtsPlayer.kt`

单一职责：发起 adapter 流式请求 + 用 AudioTrack 边收边播 PCM。

**接口**:
```kotlin
class StreamingTtsPlayer(
    private val adapterUrl: String,   // http://172.20.10.5:8091
    private val client: OkHttpClient
) {
    fun playStream(
        text: String,
        voice: String,
        onFirstChunk: () -> Unit,
        onDone: (ok: Boolean) -> Unit
    )
    fun cancel()
}
```

**核心循环**:
1. 构造 POST `/v1/audio/speech` body `{"input":"<text>","voice":"<voice>","response_format":"pcm","stream":true}`
2. `client.newCall(request).execute()` → 拿 Response
3. 初始化 AudioTrack: 24000Hz, CHANNEL_OUT_MONO, ENCODING_PCM_16BIT, MODE_STREAM, bufferSize = max(minBufferSize, 30720)
4. `audioTrack.play()`
5. 循环: `inputStream.read(buffer)` → 首次触发 `onFirstChunk` → `audioTrack.write(buffer, 0, n, WRITE_BLOCKING)`
6. read 返回 ≤0 时跳出 → `audioTrack.stop()` (flush 剩余) → `audioTrack.release()` → `onDone(true)`
7. IOException（含 Call.cancel()）→ 同样 release + onDone(false 或 不回调)

**关键参数**:
- chunk 大小：vllm-omni 实测 15360B（320ms 音频 @ 24kHz mono s16le）
- AudioTrack bufferSize：30720B（2 chunks = 640ms 缓冲）
- read buffer：8192B（小于 chunk 也 OK，AudioTrack 会等凑齐）

### 改：`service/FloatingBubbleService.kt`

**注入**: `private val streamingTtsPlayer = StreamingTtsPlayer(TTS_URL, gatewayClient)`

**sendAudioToGateway() 改动**（line 537-561 区域）:
```kotlin
Log.i(TAG, "PPT: synthesizing TTS: ${replyText.take(100)}")
if (PreferenceHelper.getStreamTtsEnabled(applicationContext)) {
    streamingTtsPlayer.playStream(
        text = replyText,
        voice = "default",
        onFirstChunk = { responseWatchdog.cancel() },
        onDone = { ok -> Log.i(TAG, "PPT: stream TTS done ok=$ok") }
    )
} else {
    // 老路径完全保留
    val ttsBody = JSONObject().apply { ... }
    val ttsRequest = Request.Builder()...
    val ttsResponse = ...
    val audioBytes = ttsResponse.body?.bytes() ?: ByteArray(0)
    if (audioBytes.isNotEmpty()) playTtsAudio(audioBytes)
}
```

**onDestroy()** 加: `streamingTtsPlayer.cancel()`

**老路径保留**: `playTtsAudio(data: ByteArray)` 函数 + `pptMediaPlayer` 字段完全不动，作为 fallback 路径长期保留。

### 改：`util/PreferenceHelper.kt`

加常量 + 2 个方法（沿用现有 saveX/getX 模式）:
```kotlin
private const val KEY_STREAM_TTS_ENABLED = "stream_tts_enabled"

fun saveStreamTtsEnabled(context: Context, enabled: Boolean) {
    getPrefs(context).edit().putBoolean(KEY_STREAM_TTS_ENABLED, enabled).apply()
}

fun getStreamTtsEnabled(context: Context): Boolean {
    return getPrefs(context).getBoolean(KEY_STREAM_TTS_ENABLED, false)
}
```

### 改：`fragment/PersonaFragment.kt`

在 voice 设置区域加 SwitchCompat:
- id: `switch_stream_tts`
- 文本: "流式 TTS (实验)"
- 初始状态: `PreferenceHelper.getStreamTtsEnabled(requireContext())`
- 监听: `setOnCheckedChangeListener { _, checked -> PreferenceHelper.saveStreamTtsEnabled(requireContext(), checked) }`

### 改：layout XML（PersonaFragment 对应布局）

加 SwitchCompat 控件。

## 数据流细节

### OkHttp 流式读取

OkHttp 自动 decode `Transfer-Encoding: chunked`，`response.body.byteStream()` 返回的 InputStream 直接是裸 PCM bytes，不需要应用层处理 chunked 边界。

```kotlin
val input = response.body!!.byteStream()
val buffer = ByteArray(8192)
while (true) {
    val n = input.read(buffer)
    if (n <= 0) break
    if (!firstChunkSent) {
        firstChunkSent = true
        onFirstChunk()
    }
    audioTrack.write(buffer, 0, n, AudioTrack.WRITE_BLOCKING)
}
```

### AudioTrack 配置

```kotlin
val sampleRate = 24000
val channelConfig = AudioFormat.CHANNEL_OUT_MONO
val audioFormat = AudioFormat.ENCODING_PCM_16BIT
val minBuf = AudioTrack.getMinBufferSize(sampleRate, channelConfig, audioFormat)
val bufferSize = maxOf(minBuf, 30720)  // 至少 2 个 chunk
audioTrack = AudioTrack(
    AudioManager.STREAM_MUSIC,
    sampleRate,
    channelConfig,
    audioFormat,
    bufferSize,
    AudioTrack.MODE_STREAM
)
audioTrack.play()
```

## 取消机制

**触发场景**:
1. 用户在 PPT 播放期间又录了一条 → 新 `playStream()` 调用前先 `cancel()` 旧的
2. Service onDestroy

**实现**:
```kotlin
fun cancel() {
    currentCall?.cancel()       // OkHttp: read 抛 IOException
    currentThread?.interrupt()  // 兜底
}

@Synchronized
fun playStream(...) {
    cancel()  // 先停旧的
    currentThread = Thread { ... }.also { it.start() }
}
```

**循环响应**:
```kotlin
try {
    // read 循环
} catch (e: IOException) {
    // Call.cancel() 或网络断
} finally {
    audioTrack?.stop()
    audioTrack?.release()
    audioTrack = null
    currentCall = null
    currentThread = null
}
```

**边界**:
- `Call.cancel()` 异步——旧线程可能还在 release AudioTrack，新线程已经创建新的
- 各自管理自己的 AudioTrack 实例，互不干扰
- 旧 AudioTrack 残余 100-200ms 播放可接受

## 错误处理

| 场景 | 处理 | 用户感知 |
|---|---|---|
| AudioTrack init 失败 | `onDone(false)` | 静默，watchdog 兜底 filler |
| HTTP 4xx/5xx | `onDone(false)` | 同上 |
| 首字节前网络断 | `onDone(false)` | 同上 |
| 首字节后流中断 | 不回调（已播部分有效） | 部分语音 + 残余丢失 |
| `Call.cancel()` | 不回调 onDone | 旧声音停，新声音起 |

**不做 fallback 重试**: 流式失败说明 adapter/网络问题，同步 POST 大概率也失败。重试浪费用户时间。fallback 是用户手动关 Toggle。

**watchdog 不重新 arm**: 首字节后失败可能短暂静默，避免复杂度。

## feature flag

- SharedPreferences key: `stream_tts_enabled`，默认 `false`
- 文件: `openclaw_car_prefs`
- 读取: 每次 `sendAudioToGateway` 时读一次（内存哈希，纳秒级）
- 切换: PersonaFragment 的 SwitchCompat

**默认 false 的意义**:
- 用户主动开启表示"愿意测试"
- 出问题用户自己关，不需要发版
- 上线后渐进推广

## 回退路径

### 应用层回退（用户操作）
1. 关闭 PersonaFragment 的"流式 TTS"SwitchCompat
2. 立即生效（下次 PPT 录音走老路径）

### 代码层回退（开发操作）
1. git revert 这次改动
2. StreamingTtsPlayer.kt 可单独删除（无侵入）
3. FloatingBubbleService 改动可单独 revert（老路径完全保留）

### Phase A 回退（adapter 层，前置依赖）
- adapter.py 备份: `/tmp/adapter.py.bak.phaseA`
- `cp /tmp/adapter.py.bak.phaseA .../adapter.py && 重启`
- 或 app 不传 `stream:true` 立刻回退（默认就 false）

## 测试策略

### 不写正式单元测试
AudioTrack + OkHttp 涉及 Android 系统组件，单测价值低。直接真机验证。

### 真机端到端验证矩阵

| 场景 | 操作 | 期望 | 失败兜底 |
|---|---|---|---|
| 基本老路径 | 关 Toggle → 录"你好" | ~2.5s 后播 | — |
| 流式开启 | 开 Toggle → 录"你好" | ~1.5s 后开始播 | 关 Toggle |
| 长文本 | 开 Toggle → 录长问题 | 1s 内听到首字 | — |
| 取消 | 开 Toggle → 录"你好"→ 播放中再录 | 旧的立刻停 → 新的开始 | — |
| 网络断 | 开 Toggle → 录期间拔网线 | adapter 失败 → filler 兜底 | 关 Toggle |
| adapter 重启 | 开 Toggle → kill adapter | IOException → log | 重启 adapter |

### 性能基线对比

按 PPT 录"你好，今天天气真不错"（20 字符）:
- 老路径：~2.5s（含 ASR 400ms + LLM 5s + TTS 1.2s + 等）
- 流式目标：< 1.5s（节省 adapter 端 ~700ms+）

### 关键 logcat

```
StreamingTtsPlayer: Connecting to adapter (text=20 chars)
StreamingTtsPlayer: AudioTrack initialized (buffer=30720B)
StreamingTtsPlayer: First chunk: 15360B at 561ms
StreamingTtsPlayer: Stream done: 307200B total, RTF=0.18
StreamingTtsPlayer: Cancelled by new request
StreamingTtsPlayer: IOException: <reason> → onDone(false)
```

## 实现顺序

1. PreferenceHelper 加 stream_tts_enabled 字段（5 行）
2. StreamingTtsPlayer.kt 实现（核心 ~150 行）
3. PersonaFragment layout XML 加 SwitchCompat
4. PersonaFragment.kt 绑定 SwitchCompat 状态
5. FloatingBubbleService sendAudioToGateway 加分叉
6. 真机端到端测试矩阵
7. 写 memory 更新

## 关键文件

| 文件 | 操作 | 估行 |
|---|---|---|
| `audio/StreamingTtsPlayer.kt` | 新建 | ~150 |
| `util/PreferenceHelper.kt` | 加常量 + 2 方法 | +10 |
| `fragment/PersonaFragment.kt` | 加 SwitchCompat 绑定 | +15 |
| `res/layout/fragment_persona.xml` | 加 SwitchCompat | +10 |
| `service/FloatingBubbleService.kt` | 加分叉 + 注入 | +20 |
