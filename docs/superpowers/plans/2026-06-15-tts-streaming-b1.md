# Phase B1: App 直连 Adapter 流式 TTS 播放 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PPT 录音场景下，用户从说完话到听到首字的时间从 ~2.5s 降到 ~1.5s，通过 OkHttp stream + AudioTrack 边收边播 PCM，绕过 gateway 同步等待。

**Architecture:** 新建 `StreamingTtsPlayer` 单职责类（POST adapter `/v1/audio/speech {"stream":true,"response_format":"pcm"}` + OkHttp 流式读 + AudioTrack MODE_STREAM 边收边播）。FloatingBubbleService 的 `sendAudioToGateway` 加 feature flag 分叉，老路径完全保留。feature flag 由 PersonaFragment 的 SwitchCompat 控制，SharedPreferences key `stream_tts_enabled` 默认 false。

**Tech Stack:** Kotlin, OkHttp (已有依赖), Android AudioTrack (system API), SharedPreferences (已有 PreferenceHelper), Fragment + XML layout (已有)。

**Spec:** `docs/superpowers/specs/2026-06-15-tts-streaming-b1-design.md`

**Phase A 前置（已完成）:** adapter.py 已加流式分支（TTFB 561ms 实测），文档见 `/home/tsm/.claude/projects/-home-tsm-work-android-agent/memory/tts-streaming-plan.md`

**测试策略:** 不写正式单元测试（spec 已确认）。验证方式：(1) `./gradlew assembleDebug` 编译验证；(2) logcat 关键标签验证；(3) 真机 PPT 录音端到端验证。

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `agent_front_app/app/src/main/java/com/openclaw/car/util/PreferenceHelper.kt` | 改（加常量+2方法） | 持久化 stream_tts_enabled |
| `agent_front_app/app/src/main/java/com/openclaw/car/audio/StreamingTtsPlayer.kt` | 新建 | 流式 POST + AudioTrack 播放 PCM |
| `agent_front_app/app/src/main/res/layout/fragment_persona.xml` | 改（加 SwitchCompat） | UI 控件 |
| `agent_front_app/app/src/main/java/com/openclaw/car/fragment/PersonaFragment.kt` | 改（绑定 SwitchCompat） | 读/写 PreferenceHelper |
| `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt` | 改（注入 + 分叉） | 根据 flag 选择流式/老路径 |

---

### Task 1: PreferenceHelper 加 stream_tts_enabled 字段

**Files:**
- Modify: `agent_front_app/app/src/main/java/com/openclaw/car/util/PreferenceHelper.kt`

- [ ] **Step 1: 加常量定义**

打开 `agent_front_app/app/src/main/java/com/openclaw/car/util/PreferenceHelper.kt`，在 `KEY_BYD_VOICE_DISABLED` 那一行下面加：

```kotlin
    private const val KEY_STREAM_TTS_ENABLED = "stream_tts_enabled"
```

最终这块常量区应该是：

```kotlin
    private const val KEY_LAST_PERSONA_INDEX = "last_persona_index"
    private const val KEY_LAST_VOICE_INDEX = "last_voice_index"
    private const val KEY_LAST_DIALECT = "last_dialect"
    private const val KEY_CUSTOM_VOICE_TEXT = "custom_voice_text"
    private const val KEY_VOICE_MODE = "voice_mode" // "preset" or "custom"
    private const val KEY_VOICE_ENABLED = "voice_enabled"
    private const val KEY_BYD_VOICE_DISABLED = "byd_voice_disabled"
    private const val KEY_STREAM_TTS_ENABLED = "stream_tts_enabled"
```

- [ ] **Step 2: 加 saveStreamTtsEnabled 和 getStreamTtsEnabled 方法**

在文件末尾的 `getBydVoiceDisabled` 方法之后、`}` (object 闭合) 之前，加：

```kotlin
    fun saveStreamTtsEnabled(context: Context, enabled: Boolean) {
        getPrefs(context).edit().putBoolean(KEY_STREAM_TTS_ENABLED, enabled).apply()
    }

    fun getStreamTtsEnabled(context: Context): Boolean {
        return getPrefs(context).getBoolean(KEY_STREAM_TTS_ENABLED, false)
    }
```

注意：默认值 `false`，与 spec 一致——上线后用户不会自动启用。

- [ ] **Step 3: 编译验证**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -20
```

Expected: `BUILD SUCCESSFUL`

- [ ] **Step 4: 真机验证持久化**

不重新装 app 也可以验证：用 `adb shell` 直接跑 Kotlin 不现实，所以延后到 Task 7 装好 app 后整体验证。这步标记 done 即可。

---

### Task 2: 创建 StreamingTtsPlayer.kt 骨架

**Files:**
- Create: `agent_front_app/app/src/main/java/com/openclaw/car/audio/StreamingTtsPlayer.kt`

- [ ] **Step 1: 创建文件，写类骨架（无逻辑）**

完整文件内容：

```kotlin
package com.openclaw.car.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException

/**
 * Streams PCM audio from the adapter `/v1/audio/speech` endpoint and plays it
 * chunk-by-chunk via AudioTrack in MODE_STREAM.
 *
 * Single responsibility: connect to adapter, read PCM chunks, write to AudioTrack.
 * Caller (FloatingBubbleService) decides when to use this vs legacy MediaPlayer path
 * based on PreferenceHelper.getStreamTtsEnabled().
 *
 * Thread model: each playStream() spawns a worker thread; cancel() signals it via
 * Call.cancel() (OkHttp throws IOException on next read).
 */
class StreamingTtsPlayer(
    private val adapterUrl: String,
    private val client: OkHttpClient
) {

    companion object {
        private const val TAG = "StreamingTtsPlayer"
        private const val SAMPLE_RATE = 24000
        private const val READ_BUFFER_BYTES = 8192
        private const val MIN_BUFFER_CHUNKS = 2
        private const val CHUNK_SIZE_BYTES = 15360  // 320ms @ 24kHz mono s16le
    }

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    @Volatile private var currentCall: okhttp3.Call? = null
    @Volatile private var currentThread: Thread? = null

    /**
     * Start streaming TTS for [text]. Returns immediately; audio plays on a worker thread.
     *
     * - [onFirstChunk] fires once on the first PCM write (use to cancel ResponseWatchdog).
     * - [onDone] fires with `true` on normal completion, NOT called on cancel() (caller-initiated).
     *   Called with `false` on adapter/HTTP error before any chunk arrived.
     *
     * If a previous stream is in flight, it is cancelled before starting this one.
     */
    @Synchronized
    fun playStream(
        text: String,
        voice: String,
        onFirstChunk: () -> Unit,
        onDone: (ok: Boolean) -> Unit
    ) {
        cancel()
        val thread = Thread({
            runStream(text, voice, onFirstChunk, onDone)
        }, "StreamingTtsPlayer").also { currentThread = it }
        thread.start()
    }

    /**
     * Cancel any in-flight stream. Safe to call repeatedly; no-op if nothing playing.
     * Does NOT call onDone — caller-initiated cancel is silent.
     */
    @Synchronized
    fun cancel() {
        currentCall?.cancel()
        currentThread?.interrupt()
    }

    private fun runStream(
        text: String,
        voice: String,
        onFirstChunk: () -> Unit,
        onDone: (ok: Boolean) -> Unit
    ) {
        // 实现在 Task 3 写
    }
}
```

- [ ] **Step 2: 编译验证**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -10
```

Expected: `BUILD SUCCESSFUL`（unused param warnings 可接受，Task 3 会用到）

---

### Task 3: StreamingTtsPlayer 核心 streaming 循环

**Files:**
- Modify: `agent_front_app/app/src/main/java/com/openclaw/car/audio/StreamingTtsPlayer.kt` (替换 runStream 函数体)

- [ ] **Step 1: 实现 runStream 完整逻辑**

把 Task 2 中的 `runStream` 占位实现替换为：

```kotlin
    private fun runStream(
        text: String,
        voice: String,
        onFirstChunk: () -> Unit,
        onDone: (ok: Boolean) -> Unit
    ) {
        val t0 = System.currentTimeMillis()
        var audioTrack: AudioTrack? = null
        var firstChunkSent = false
        var anyChunkReceived = false

        try {
            // 1. Build POST request body
            val body = JSONObject().apply {
                put("input", text)
                put("voice", voice)
                put("response_format", "pcm")
                put("stream", true)
            }
            val request = Request.Builder()
                .url("$adapterUrl/v1/audio/speech")
                .post(body.toString().toRequestBody(jsonType))
                .build()

            Log.i(TAG, "Connecting (text=${text.length} chars)")

            // 2. Execute (blocking) — OkHttp auto-decodes chunked transfer
            val call = client.newCall(request)
            currentCall = call
            val response = call.execute()
            if (!response.isSuccessful) {
                Log.e(TAG, "HTTP ${response.code} — aborting")
                response.close()
                onDone(false)
                return
            }

            // 3. Initialize AudioTrack (before first chunk so write() can start immediately)
            val minBuf = AudioTrack.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            val bufferSize = maxOf(minBuf, CHUNK_SIZE_BYTES * MIN_BUFFER_CHUNKS)
            audioTrack = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .build()
                )
                .setBufferSizeInBytes(bufferSize)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
            audioTrack.play()
            Log.i(TAG, "AudioTrack ready (buffer=${bufferSize}B)")

            // 4. Stream loop: read PCM chunk → write to AudioTrack
            val source = response.body?.byteStream() ?: run {
                Log.e(TAG, "Empty response body")
                response.close()
                onDone(false)
                return
            }
            val buffer = ByteArray(READ_BUFFER_BYTES)
            var totalBytes = 0
            while (true) {
                val n = source.read(buffer)
                if (n <= 0) break
                anyChunkReceived = true
                if (!firstChunkSent) {
                    firstChunkSent = true
                    val elapsed = System.currentTimeMillis() - t0
                    Log.i(TAG, "First chunk: ${n}B at ${elapsed}ms")
                    onFirstChunk()
                }
                audioTrack.write(buffer, 0, n, AudioTrack.WRITE_BLOCKING)
                totalBytes += n
            }

            // 5. Normal completion
            val elapsed = System.currentTimeMillis() - t0
            val audioSec = totalBytes / (SAMPLE_RATE * 2.0)
            Log.i(TAG, "Stream done: ${totalBytes}B (${String.format("%.2f", audioSec)}s audio), ${elapsed}ms total")
            response.close()
            onDone(true)

        } catch (e: IOException) {
            // Call.cancel() OR network error
            Log.i(TAG, "Stream cancelled/errored: ${e.javaClass.simpleName}: ${e.message}")
            // If we already started playing, treat as partial-success (don't trigger onDone
            // fallback). If never got a chunk, signal failure so caller can recover.
            if (anyChunkReceived) {
                // Already notified watchdog.cancel via onFirstChunk — don't re-arm
            } else {
                onDone(false)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Unexpected: ${e.javaClass.simpleName}: ${e.message}")
            if (!anyChunkReceived) onDone(false)
        } finally {
            try { audioTrack?.stop() } catch (_: Exception) {}
            try { audioTrack?.release() } catch (_: Exception) {}
            currentCall = null
            currentThread = null
        }
    }
```

- [ ] **Step 2: 编译验证**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -10
```

Expected: `BUILD SUCCESSFUL`

- [ ] **Step 3: 静态自检 — 关键属性核对**

确认以下要点（直接读代码确认）：
1. `playStream` 入口先调 `cancel()`（保证互斥）
2. `currentCall` 在 `finally` 中清空（防泄漏）
3. `audioTrack.release()` 在 `finally` 中调（防泄漏）
4. `onFirstChunk` 只在第一次 write 前调一次
5. IOException 时只在 `!anyChunkReceived` 才回调 `onDone(false)`（已播部分不触发 fallback）

如果有任何一点不对，先修再继续。

---

### Task 4: fragment_persona.xml 加 SwitchCompat 控件

**Files:**
- Modify: `agent_front_app/app/src/main/res/layout/fragment_persona.xml`

- [ ] **Step 1: 在 ChipGroup 之后、LinearLayout 闭合之前加 SwitchCompat**

打开 `agent_front_app/app/src/main/res/layout/fragment_persona.xml`，找到 ChipGroup 块（约 line 233-239）。在 ChipGroup 闭合 `</com.google.android.material.chip.ChipGroup>` 之后、`</LinearLayout>` (line 241) 之前加：

```xml
        <!-- ========== Stream TTS Toggle ========== -->
        <View
            android:layout_width="match_parent"
            android:layout_height="1dp"
            android:background="@color/divider"
            android:layout_marginTop="28dp"
            android:layout_marginBottom="20dp" />

        <androidx.appcompat.widget.SwitchCompat
            android:id="@+id/switch_stream_tts"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="流式 TTS (实验)"
            android:textColor="@color/text_primary"
            android:textSize="16sp"
            android:padding="4dp" />
```

最终这块结构应该是：

```xml
        <com.google.android.material.chip.ChipGroup
            android:id="@+id/chip_group_dialect"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            app:singleSelection="true"
            app:chipSpacingHorizontal="8dp"
            app:chipSpacingVertical="4dp" />

        <!-- ========== Stream TTS Toggle ========== -->
        <View
            android:layout_width="match_parent"
            android:layout_height="1dp"
            android:background="@color/divider"
            android:layout_marginTop="28dp"
            android:layout_marginBottom="20dp" />

        <androidx.appcompat.widget.SwitchCompat
            android:id="@+id/switch_stream_tts"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="流式 TTS (实验)"
            android:textColor="@color/text_primary"
            android:textSize="16sp"
            android:padding="4dp" />

    </LinearLayout>
</ScrollView>
```

- [ ] **Step 2: 编译验证（XML 解析）**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -10
```

Expected: `BUILD SUCCESSFUL`（如果 `@color/divider` 或 `@color/text_primary` 不存在会报错；这两个 color 在 PersonaFragment 已经在用，应该 OK）

---

### Task 5: PersonaFragment 绑定 SwitchCompat

**Files:**
- Modify: `agent_front_app/app/src/main/java/com/openclaw/car/fragment/PersonaFragment.kt`

- [ ] **Step 1: 加 import**

打开 `agent_front_app/app/src/main/java/com/openclaw/car/fragment/PersonaFragment.kt`。在 import 区（约 line 19）加：

```kotlin
import androidx.appcompat.widget.SwitchCompat
```

放在已有的 `import androidx.appcompat.app.AlertDialog` 之后即可。

- [ ] **Step 2: 在 onViewCreated 末尾绑定 SwitchCompat**

找到 `on onViewCreated(view: View, savedInstanceState: Bundle?)` 方法（line 57 开始）。在该方法的最后（在 `setupDialectChips()` 调用之后或方法的最后一行）加：

```kotlin
        // Stream TTS experimental toggle
        val switchStreamTts = view.findViewById<SwitchCompat>(R.id.switch_stream_tts)
        switchStreamTts.isChecked = PreferenceHelper.getStreamTtsEnabled(context)
        switchStreamTts.setOnCheckedChangeListener { _, checked ->
            PreferenceHelper.saveStreamTtsEnabled(context, checked)
            Log.i(TAG, "Stream TTS ${if (checked) "enabled" else "disabled"}")
        }
```

注意：`context` 变量在该方法已经定义（line 78: `val context = requireContext()`），可直接使用。

- [ ] **Step 3: 编译验证**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -10
```

Expected: `BUILD SUCCESSFUL`

---

### Task 6: FloatingBubbleService 注入 StreamingTtsPlayer

**Files:**
- Modify: `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt`

- [ ] **Step 1: 加 import**

打开 `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt`。在 import 区（约 line 1-42）加：

```kotlin
import com.openclaw.car.audio.StreamingTtsPlayer
import com.openclaw.car.util.PreferenceHelper
```

`PreferenceHelper` 如果已经 import 过就跳过。放在 `import com.openclaw.car.audio.TtsAudioPlayer` 之后。

- [ ] **Step 2: 在字段区注入 StreamingTtsPlayer**

找到字段区（约 line 76）：

```kotlin
    private val ttsPlayer = TtsAudioPlayer()
    private val fillerPlayer = FillerAudioPlayer()
    private val responseWatchdog = ResponseWatchdog(fillerPlayer)
```

在 `responseWatchdog` 之后加：

```kotlin
    private val streamingTtsPlayer = StreamingTtsPlayer(TTS_URL, gatewayClient)
```

注意：`TTS_URL` 是 companion object 里的常量（line 53），`gatewayClient` 是已有的 OkHttpClient（line 59），都可以在 field initializer 中引用（companion object 常量优先初始化，gatewayClient 用 `by lazy` 不行——必须是 `val` 直接初始化，而它确实是）。

- [ ] **Step 3: 编译验证**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -10
```

Expected: `BUILD SUCCESSFUL`

---

### Task 7: sendAudioToGateway 加流式分叉

**Files:**
- Modify: `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt:537-561`

- [ ] **Step 1: 定位 TTS 步骤的"老路径"代码块**

打开 `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt`，找到约 line 531-561 的 PPT TTS 步骤：

```kotlin
                Log.i(TAG, "PPT: synthesizing TTS: ${replyText.take(100)}")
                val ttsBody = JSONObject().apply {
                    put("model", "tts")
                    put("input", replyText)
                    put("voice", "default")
                }
                val ttsRequest = Request.Builder()
                    .url(TTS_URL)
                    .addHeader("Content-Type", "application/json")
                    .post(ttsBody.toString().toRequestBody("application/json".toMediaType()))
                    .build()

                val ttsResponse = gatewayClient.newBuilder()
                    .readTimeout(120, TimeUnit.SECONDS)
                    .build()
                    .newCall(ttsRequest)
                    .execute()

                if (!ttsResponse.isSuccessful) {
                    Log.e(TAG, "PPT: TTS failed: ${ttsResponse.code}")
                    return@Thread
                }

                val audioBytes = ttsResponse.body?.bytes() ?: ByteArray(0)
                if (audioBytes.isEmpty()) {
                    Log.w(TAG, "PPT: TTS returned empty audio")
                    return@Thread
                }

                Log.i(TAG, "PPT: TTS audio received: ${audioBytes.size} bytes, playing...")
                playTtsAudio(audioBytes)
```

- [ ] **Step 2: 在 TTS 步骤开头加分叉判断**

把上面整块（从 `Log.i(TAG, "PPT: synthesizing TTS...")` 到 `playTtsAudio(audioBytes)`）替换为：

```kotlin
                Log.i(TAG, "PPT: synthesizing TTS: ${replyText.take(100)}")

                if (PreferenceHelper.getStreamTtsEnabled(applicationContext)) {
                    // === Stream path (experimental) ===
                    Log.i(TAG, "PPT: using STREAM TTS path")
                    streamingTtsPlayer.playStream(
                        text = replyText,
                        voice = "default",
                        onFirstChunk = { responseWatchdog.cancel() },
                        onDone = { ok ->
                            Log.i(TAG, "PPT: stream TTS done ok=$ok")
                            // No fallback retry — if stream fails, sync POST likely fails too.
                            // Watchdog still armed if no firstChunk, filler will play.
                        }
                    )
                } else {
                    // === Legacy path (default) ===
                    val ttsBody = JSONObject().apply {
                        put("model", "tts")
                        put("input", replyText)
                        put("voice", "default")
                    }
                    val ttsRequest = Request.Builder()
                        .url(TTS_URL)
                        .addHeader("Content-Type", "application/json")
                        .post(ttsBody.toString().toRequestBody("application/json".toMediaType()))
                        .build()

                    val ttsResponse = gatewayClient.newBuilder()
                        .readTimeout(120, TimeUnit.SECONDS)
                        .build()
                        .newCall(ttsRequest)
                        .execute()

                    if (!ttsResponse.isSuccessful) {
                        Log.e(TAG, "PPT: TTS failed: ${ttsResponse.code}")
                        return@Thread
                    }

                    val audioBytes = ttsResponse.body?.bytes() ?: ByteArray(0)
                    if (audioBytes.isEmpty()) {
                        Log.w(TAG, "PPT: TTS returned empty audio")
                        return@Thread
                    }

                    Log.i(TAG, "PPT: TTS audio received: ${audioBytes.size} bytes, playing...")
                    playTtsAudio(audioBytes)
                }
```

注意：老路径代码一字不改，只是被包在 `else` 分支里。

- [ ] **Step 3: onDestroy 加 streamingTtsPlayer.cancel()**

找到 `onDestroy()` 方法（约 line 104-110）。在 `ttsPlayer.stop()` 之后、`fillerPlayer.stop()` 之前（或任意位置）加：

```kotlin
        streamingTtsPlayer.cancel()
```

最终的 onDestroy 应该长这样（顺序可能略不同）：

```kotlin
    override fun onDestroy() {
        instance = null
        asrMonitor?.stop()
        ttsPlayer.stop()
        streamingTtsPlayer.cancel()
        fillerPlayer.stop()
        handler.removeCallbacks(collapseRunnable)
        ...
    }
```

- [ ] **Step 4: 编译验证**

```bash
cd /home/tsm/work/android_agent/agent_front_app && ./gradlew assembleDebug 2>&1 | tail -15
```

Expected: `BUILD SUCCESSFUL`。如果有 unused import 警告无关紧要。

---

### Task 8: 装车 & 基本功能验证

**Files:** 无修改，纯运行 + 观察。

- [ ] **Step 1: 装新 APK 到车机**

```bash
cd /home/tsm/work/android_agent/agent_front_app
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Expected: `Success`

- [ ] **Step 2: 恢复必要权限（每次重装都要）**

```bash
adb shell appops set com.openclaw.car SYSTEM_ALERT_WINDOW allow
adb shell pm grant com.openclaw.car android.permission.RECORD_AUDIO
# 其他权限按 car-reinstall-checklist memory 走
```

- [ ] **Step 3: 开 logcat 过滤**

```bash
adb logcat -c
adb logcat StreamingTtsPlayer:* OpenClaw.Bubble:* OpenClaw.Watchdog:* *:S
```

留这个 terminal 开着。

- [ ] **Step 4: 默认关闭状态 — 验证老路径无 regression**

不进 PersonaFragment 开 Toggle。按 PPT 录"你好，今天天气真不错"。

Expected logcat:
- `PPT: synthesizing TTS: ...`
- `PPT: TTS audio received: ...`
- `PPT: TTS playback complete`
- 不应该看到 `PPT: using STREAM TTS path`

声音应该在 ~2-3s 后播放（基线）。

- [ ] **Step 5: 打开流式 Toggle**

进 app → 第二个 tab（Persona）→ 滑到底 → 打开"流式 TTS (实验)"SwitchCompat。

Expected logcat:
- `PersonaFragment: Stream TTS enabled`

- [ ] **Step 6: 流式路径 — 验证 TTFB 改善**

按 PPT 录"你好，今天天气真不错"。

Expected logcat 顺序：
- `PPT: synthesizing TTS: ...`
- `PPT: using STREAM TTS path`
- `StreamingTtsPlayer: Connecting (text=14 chars)`
- `StreamingTtsPlayer: AudioTrack ready (buffer=...B)`
- `StreamingTtsPlayer: First chunk: 15360B at 561ms` （时间应该在 500-1000ms）
- `StreamingTtsPlayer: Stream done: 307200B (6.40s audio), 1300ms total`
- `PPT: stream TTS done ok=true`

体感：从说完话到听到第一个字应该 < 1.5s（老路径 ~2.5s）。

如果不出现 `First chunk`：
- 检查 `StreamingTtsPlayer: HTTP ${code}` 错误日志
- 检查 adapter 端 `/tmp/adapter.log`（开发机上）
- 确认 Toggle 真的开（logcat 有 `Stream TTS enabled`）

- [ ] **Step 7: 取消机制验证**

按 PPT 录"你好"→ 等播放开始（听到第一个字）→ 立刻再按 PPT 录"再见"。

Expected logcat:
- 第一条：`First chunk ... at ...ms`
- 然后：`Stream cancelled/errored: IOException: ...`（旧 stream 被 cancel）
- 然后：新请求的 `Connecting ...` → `First chunk ...`

体感：旧的语音立刻停，新的语音起。

- [ ] **Step 8: watchdog 联动验证**

按 PPT 录"你好"（流式 Toggle 开）。观察 watchdog 是否触发 filler。

Expected：流式 TTFB ~600ms << watchdog 4000ms，filler **不应该**触发。
logcat 不应出现 `Watchdog fired after 4000ms`。

如果出现了：
- 说明首字节没及时到 → 检查 `StreamingTtsPlayer: First chunk` 时间
- 如果 First chunk 没出现，说明 adapter 流式没工作，回退到 Task 7 step 6 检查

---

### Task 9: 更新 memory 文档

**Files:**
- Modify: `/home/tsm/.claude/projects/-home-tsm-work-android-agent/memory/tts-streaming-plan.md`
- Modify: `/home/tsm/.claude/projects/-home-tsm-work-android-agent/memory/MEMORY.md`

- [ ] **Step 1: 更新 tts-streaming-plan.md**

把 Phase B1 状态从"待定"改为"完成"，关键文件位置、回退方法、实测 TTFB 数据补全。具体内容根据 Task 8 实测结果填写。

至少更新这些字段：
- 现状：Phase B1 完成 ✅
- 关键代码位置：StreamingTtsPlayer.kt, sendAudioToGateway 分叉位置
- 实测 TTFB：从 Task 8 step 6 取数
- feature flag：stream_tts_enabled
- 回退方法：关 SwitchCompat / git revert

- [ ] **Step 2: 更新 MEMORY.md 索引**

把 `TTS Streaming Plan` 那一行的描述更新为：
```
- [TTS Streaming Plan](tts-streaming-plan.md) — Phase A adapter流式✅ + Phase B1 PPT路径流式✅(TTFB Xms)，BYD ASR路径B2待定
```

X 用 Task 8 step 6 实测值。

---

## Self-Review

### Spec coverage 检查

| Spec 章节 | 对应 Task |
|---|---|
| §1 架构与文件结构 | Task 2 (StreamingTtsPlayer), Task 6/7 (FloatingBubbleService), Task 5 (PersonaFragment) |
| §2 StreamingTtsPlayer 内部数据流 | Task 3 (runStream 实现) |
| §3 取消机制与并发控制 | Task 2 (cancel/playStream 骨架) + Task 3 (IOException 处理) |
| §4 错误处理与降级回退 | Task 3 (anyChunkReceived 分支) — fallback 不重试已在 spec 说明，代码中体现为不调老路径 |
| §5 feature flag 与设置页 | Task 1 (PreferenceHelper) + Task 4 (XML) + Task 5 (PersonaFragment) |
| §6 测试与验证策略 | Task 8 (真机端到端验证矩阵) |

无 spec 要求遗漏。

### Placeholder 扫描

- "TBD/TODO/implement later" → 无
- "Add appropriate error handling" → 无（错误处理代码完整给出）
- "Similar to Task N" → 无（每个 task 自包含）
- 未定义的类型/函数 → 无

### Type/method 一致性

- `playStream(text, voice, onFirstChunk, onDone)` — Task 2 定义、Task 3 实现、Task 7 调用，签名一致
- `cancel()` — Task 2 定义、Task 7 调用（onDestroy），一致
- `onFirstChunk: () -> Unit` 和 `onDone: (ok: Boolean) -> Unit` — 类型一致
- `streamingTtsPlayer` 字段名 — Task 6 定义、Task 7 使用，一致
- `R.id.switch_stream_tts` — Task 4 XML 定义、Task 5 findViewById 使用，一致
- `KEY_STREAM_TTS_ENABLED` — Task 1 定义，唯一引用点
- `PreferenceHelper.getStreamTtsEnabled/saveStreamTtsEnabled` — Task 1 定义、Task 5 和 Task 7 调用，方法名一致

无类型/方法签名不一致。
