# 豆包 Realtime 闲聊 App 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 BYD 车机上做一个独立 Android app，用豆包端到端 Realtime API 实现 always-on 纯语音闲聊（含打断）。

**Architecture:** 移植官方 Java demo 的二进制协议层到 Kotlin，传输层用 OkHttp WebSocket，音频层用 Android 原生 AudioRecord/AudioTrack，单 Activity + ViewModel 驱动，独立工程目录 `doubao_chitchat/`。

**Tech Stack:** Kotlin 1.8.22, Gradle 8.2, AGP 8.1.4, minSdk 26 / compileSdk 34, Java 11, OkHttp 4.12.0 (WebSocket), Gson 2.10.1, kotlinx-coroutines 1.7.3, JUnit4。

**参考实现（对照用）:** `workspace/realtime_dialog_ref/java/src/main/java/com/volcengine/realtimedialog/`（火山官方 demo，已解压）。
**Spec:** `docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md`

## Global Constraints

- 包名 `com.openclaw.chitchat`，工程根目录 `doubao_chitchat/`（项目根下，与 `agent_front_app` 平级，独立 Gradle 工程）。
- minSdk 26, compileSdk/targetSdk 34, Java 11 (jvmTarget "11"), Kotlin 1.8.22, Gradle 8.2, AGP 8.1.4。
- WS URL `wss://openspeech.bytedance.com/api/v3/realtime/dialogue`，Resource-Id 固定 `volc.speech.dialog`，App-Key 固定 `PlgvMymc7f3tQnJ6`，App-ID/Access-Key 由用户填（BuildConfig 或本地配置，不硬编码真实值入库）。
- 上行音频 PCM 16kHz / mono / int16 小端；下行请求 `pcm_s16le` 24kHz / mono。20ms 包 = 640 字节。
- 模型 `model = "1.2.1.1"`（O2.0，**不是** demo 的 `"O"`）。音色默认 `zh_female_vv_jupiter_bigtts`。
- 二进制协议全程**大端序**，optional 字段严格按 event→sessionId→connectId→sequence→errorCode→payload 顺序。
- 打断：收到 `ASRInfo(450)` 清播放队列 + `AudioTrack.pause()/flush()`。
- 每个 task 结束 commit；commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。

## File Structure

| 文件 | 职责 |
|---|---|
| `doubao_chitchat/settings.gradle.kts` `build.gradle.kts` `gradle.properties` `gradlew` + `gradle/wrapper/*` | Gradle 工程根 |
| `app/build.gradle.kts` `app/proguard-rules.pro` | app 模块构建（OkHttp/Gson/coroutines/BuildConfig） |
| `app/src/main/AndroidManifest.xml` | RECORD_AUDIO + INTERNET 权限，声明 Activity |
| `app/src/main/java/com/openclaw/chitchat/Protocol.kt` | 二进制帧 marshal/unmarshal（移植自 demo） |
| `app/src/main/java/com/openclaw/chitchat/Config.kt` | 鉴权常量 + payload data class |
| `app/src/main/java/com/openclaw/chitchat/RealtimeClient.kt` | OkHttp WebSocket + 事件分发 |
| `app/src/main/java/com/openclaw/chitchat/AudioRecorder.kt` | AudioRecord 录音 |
| `app/src/main/java/com/openclaw/chitchat/AudioPlayer.kt` | AudioTrack 播放 + 打断 |
| `app/src/main/java/com/openclaw/chitchat/CallManager.kt` | 会话状态机 + 编排 + 重连 |
| `app/src/main/java/com/openclaw/chitchat/ui/ChitchatViewModel.kt` | UI 状态（LiveData） |
| `app/src/main/java/com/openclaw/chitchat/ui/ChitchatActivity.kt` | 极简全屏 UI + 生命周期/权限/音频焦点 |
| `app/src/main/res/layout/activity_chitchat.xml` | 布局：状态 + 字幕 + 录音指示 |
| `app/src/test/java/com/openclaw/chitchat/ProtocolTest.kt` | 协议帧 round-trip 单测 |
| `app/src/test/java/com/openclaw/chitchat/ConfigPayloadTest.kt` | payload 构造单测 |

任务依赖：1 → 2 → 3 → 4/5/6（并行）→ 7 → 8 → 9 → 10。

---

### Task 1: 工程脚手架（能 `assembleDebug`）

**Files:**
- Create: `doubao_chitchat/settings.gradle.kts`
- Create: `doubao_chitchat/build.gradle.kts`
- Create: `doubao_chitchat/gradle.properties`
- Create: `doubao_chitchat/gradle/wrapper/gradle-wrapper.properties`
- Create: `doubao_chitchat/app/build.gradle.kts`
- Create: `doubao_chitchat/app/src/main/AndroidManifest.xml`
- Create: `doubao_chitchat/app/src/main/java/com/openclaw/chitchat/ui/ChitchatActivity.kt`（占位）
- Create: `doubao_chitchat/app/src/main/res/values/strings.xml`
- Copy: `agent_front_app/gradle/wrapper/gradle-wrapper.jar` 和 `gradlew`/`gradlew.bat` → `doubao_chitchat/`

**Interfaces:**
- Produces: 可编译的空 app（`com.openclaw.chitchat`），`./gradlew assembleDebug` 通过。

- [ ] **Step 1: 建 Gradle 根配置**

`doubao_chitchat/settings.gradle.kts`:
```kotlin
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "doubao_chitchat"
include(":app")
```

`doubao_chitchat/build.gradle.kts`:
```kotlin
plugins {
    id("com.android.application") version "8.1.4" apply false
    id("org.jetbrains.kotlin.android") version "1.8.22" apply false
}
```

`doubao_chitchat/gradle.properties`:
```
org.gradle.jvmargs=-Xmx2048m
android.useAndroidX=true
kotlin.code.style=official
```

`doubao_chitchat/gradle/wrapper/gradle-wrapper.properties`:
```
distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\://services.gradle.org/distributions/gradle-8.2-bin.zip
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
```

- [ ] **Step 2: 复制 gradle wrapper 二进制**

Run:
```bash
cd /home/tsm/work/android_agent
cp agent_front_app/gradlew doubao_chitchat/gradlew
cp agent_front_app/gradlew.bat doubao_chitchat/gradlew.bat
mkdir -p doubao_chitchat/gradle/wrapper
cp agent_front_app/gradle/wrapper/gradle-wrapper.jar doubao_chitchat/gradle/wrapper/gradle-wrapper.jar
chmod +x doubao_chitchat/gradlew
```

- [ ] **Step 3: 建 app 模块 build.gradle.kts**

`doubao_chitchat/app/build.gradle.kts`:
```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.openclaw.chitchat"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.openclaw.chitchat"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // 鉴权：从 ~/.gradle/gradle.properties 或环境变量读，不硬编码入库
        buildConfigField("String", "DOUBAO_APP_ID", "\"${project.findProperty("doubaoAppId") ?: ""}\"")
        buildConfigField("String", "DOUBAO_ACCESS_KEY", "\"${project.findProperty("doubaoAccessKey") ?: ""}\"")
    }

    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions { jvmTarget = "11" }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.10.1")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.6.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.6.2")
    implementation("com.google.android.material:material:1.9.0")
    testImplementation("junit:junit:4.13.2")
}
```

- [ ] **Step 4: Manifest + 占位 Activity + strings**

`doubao_chitchat/app/src/main/AndroidManifest.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <application
        android:allowBackup="true"
        android:label="@string/app_name"
        android:theme="@style/Theme.AppCompat.NoActionBar">
        <activity
            android:name=".ui.ChitchatActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

`doubao_chitchat/app/src/main/java/com/openclaw/chitchat/ui/ChitchatActivity.kt`（占位，Task 8 替换）:
```kotlin
package com.openclaw.chitchat.ui

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class ChitchatActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Task 8 替换为真实 UI
    }
}
```

`doubao_chitchat/app/src/main/res/values/strings.xml`:
```xml
<resources>
    <string name="app_name">闲聊</string>
</resources>
```

- [ ] **Step 5: 编译验证**

Run:
```bash
cd /home/tsm/work/android_agent/doubao_chitchat && ./gradlew assembleDebug
```
Expected: BUILD SUCCESSFUL。

- [ ] **Step 6: Commit**

```bash
cd /home/tsm/work/android_agent
git add doubao_chitchat
git commit -m "feat(chitchat): 工程脚手架，可 assembleDebug

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 二进制协议层 `Protocol.kt`（TDD）

移植自 `workspace/realtime_dialog_ref/.../Protocol.java`。纯字节操作，无 Android 依赖，可用 JUnit4 严格 TDD。

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/Protocol.kt`
- Test: `app/src/test/java/com/openclaw/chitchat/ProtocolTest.kt`

**Interfaces:**
- Produces: `Protocol.MsgType`, `Protocol.Message`, `Protocol.marshal(Message):ByteArray`, `Protocol.marshalRawAudio(Message):ByteArray`, `Protocol.unmarshal(ByteArray):Message`, `Protocol.startConnection()`, `Protocol.startSession(sid,json)`, `Protocol.audioFrame(sid,pcm)`, `Protocol.eventMessage(sid,json,event)`, `Protocol.generateSessionId()`.

- [ ] **Step 1: 写失败测试（用文档真实字节 fixture）**

`app/src/test/java/com/openclaw/chitchat/ProtocolTest.kt`:
```kotlin
package com.openclaw.chitchat

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class ProtocolTest {
    // 文档示例：StartConnection 帧，payload "{}" = [123,125]
    private val startConnExpected = byteArrayOf(
        17, 20, 16, 0,            // header: 0x11, 0x14, 0x10, 0x00
        0, 0, 0, 1,               // event=1
        0, 0, 0, 2,               // payload size=2
        123, 125                  // "{}"
    )

    @Test fun startConnection_bytes_match_doc() {
        assertArrayEquals(startConnExpected, Protocol.startConnection())
    }

    @Test fun unmarshal_startConnection_reads_event() {
        val msg = Protocol.unmarshal(startConnExpected)
        assertEquals(Protocol.MsgType.FULL_CLIENT, msg.type)
        assertEquals(1, msg.event)
        assertArrayEquals("{}".toByteArray(Charsets.UTF_8), msg.payload)
    }

    @Test fun audio_frame_uses_raw_serialization_and_event_200() {
        val pcm = ByteArray(640) { (it and 0xFF).toByte() }
        val frame = Protocol.audioFrame("sess-id", pcm)
        val msg = Protocol.unmarshal(frame)
        assertEquals(Protocol.MsgType.AUDIO_ONLY_CLIENT, msg.type)
        assertEquals(200, msg.event)
        assertEquals("sess-id", msg.sessionId)
        assertArrayEquals(pcm, msg.payload)
    }

    @Test fun startSession_includes_session_id_and_event_100() {
        val frame = Protocol.startSession("abc", "{}")
        val msg = Protocol.unmarshal(frame)
        assertEquals(Protocol.MsgType.FULL_CLIENT, msg.type)
        assertEquals(100, msg.event)
        assertEquals("abc", msg.sessionId)
    }

    @Test fun round_trip_generic_event_message() {
        val frame = Protocol.eventMessage("sid", "{\"content\":\"hi\"}", 300)
        val msg = Protocol.unmarshal(frame)
        assertEquals(300, msg.event)
        assertEquals("sid", msg.sessionId)
        assertEquals("{\"content\":\"hi\"}", String(msg.payload!!, Charsets.UTF_8))
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd doubao_chitchat && ./gradlew :app:testDebugUnitTest --tests "com.openclaw.chitchat.ProtocolTest"`
Expected: 编译失败（Protocol 未定义）。

- [ ] **Step 3: 实现 `Protocol.kt`**

`app/src/main/java/com/openclaw/chitchat/Protocol.kt`:
```kotlin
package com.openclaw.chitchat

import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object Protocol {
    enum class MsgType(val bits: Int) {
        FULL_CLIENT(1), AUDIO_ONLY_CLIENT(2),
        FULL_SERVER(9), AUDIO_ONLY_SERVER(11), ERROR(15)
    }

    const val FLAG_WITH_EVENT = 0b0100
    private const val VERSION_1 = 0x10
    private const val HEADER_SIZE_4 = 0x1
    private const val SER_JSON = 0b0001 shl 4   // serialization=JSON in high nibble
    private const val SER_RAW = 0b0000           // serialization=RAW
    private const val COMPRESSION_NONE = 0

    // sessionId 写入规则：事件 1/2/50/51/52 不带
    private val NO_SESSION_EVENTS = setOf(1, 2, 50, 51, 52)

    data class Message(
        var type: MsgType = MsgType.FULL_CLIENT,
        var typeFlag: Int = 0,
        var event: Int = 0,
        var sessionId: String? = null,
        var sequence: Int = 0,
        var errorCode: Long = 0,
        var payload: ByteArray? = null
    )

    private fun header(dos: DataOutputStream, type: MsgType, typeFlag: Int, serialization: Int) {
        dos.writeByte(VERSION_1 or HEADER_SIZE_4)                       // 0x11
        dos.writeByte((type.bits shl 4) or (typeFlag and 0x0F))         // type<<4 | flag
        dos.writeByte(serialization or COMPRESSION_NONE)                // ser | comp
        dos.writeByte(0)                                                // reserved
    }

    private fun writeEvent(dos: DataOutputStream, msg: Message) {
        if ((msg.typeFlag and FLAG_WITH_EVENT) != 0) dos.writeInt(msg.event)
    }

    private fun writeSessionId(dos: DataOutputStream, msg: Message) {
        if ((msg.typeFlag and FLAG_WITH_EVENT) == 0) return
        if (msg.event in NO_SESSION_EVENTS) return
        val bytes = (msg.sessionId ?: "").toByteArray(Charsets.UTF_8)
        dos.writeInt(bytes.size)
        dos.write(bytes)
    }

    private fun writePayload(dos: DataOutputStream, msg: Message) {
        val p = msg.payload
        if (p == null) dos.writeInt(0) else { dos.writeInt(p.size); dos.write(p) }
    }

    fun marshal(msg: Message): ByteArray {
        val baos = ByteArrayOutputStream(); val dos = DataOutputStream(baos)
        header(dos, msg.type, msg.typeFlag, SER_JSON)
        writeEvent(dos, msg); writeSessionId(dos, msg); writePayload(dos, msg)
        return baos.toByteArray()
    }

    fun marshalRawAudio(msg: Message): ByteArray {
        val baos = ByteArrayOutputStream(); val dos = DataOutputStream(baos)
        header(dos, msg.type, msg.typeFlag, SER_RAW)
        writeEvent(dos, msg); writeSessionId(dos, msg); writePayload(dos, msg)
        return baos.toByteArray()
    }

    fun unmarshal(data: ByteArray): Message {
        val buf = ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN)
        buf.get() // version|headerSize (0x11)
        val typeAndFlag = buf.get().toInt() and 0xFF
        buf.get() // serialization|compression
        buf.get() // reserved
        val msg = Message()
        msg.type = enumValues<MsgType>().first { it.bits == ((typeAndFlag shr 4) and 0x0F) }
        msg.typeFlag = typeAndFlag and 0x0F
        if ((msg.typeFlag and FLAG_WITH_EVENT) != 0) msg.event = buf.int
        if ((msg.typeFlag and FLAG_WITH_EVENT) != 0 && msg.event !in NO_SESSION_EVENTS) {
            val size = buf.int
            if (size > 0) { val b = ByteArray(size); buf.get(b); msg.sessionId = String(b, Charsets.UTF_8) }
        }
        if (msg.type == MsgType.ERROR) msg.errorCode = buf.int.toLong() and 0xFFFFFFFFL
        val psize = buf.int
        if (psize > 0) { msg.payload = ByteArray(psize); buf.get(msg.payload!!) }
        return msg
    }

    fun startConnection(): ByteArray {
        val m = Message(type = MsgType.FULL_CLIENT, typeFlag = FLAG_WITH_EVENT, event = 1,
            payload = "{}".toByteArray(Charsets.UTF_8))
        return marshal(m)
    }

    fun startSession(sid: String, json: String): ByteArray {
        val m = Message(type = MsgType.FULL_CLIENT, typeFlag = FLAG_WITH_EVENT, event = 100,
            sessionId = sid, payload = json.toByteArray(Charsets.UTF_8))
        return marshal(m)
    }

    fun audioFrame(sid: String, pcm: ByteArray): ByteArray {
        val m = Message(type = MsgType.AUDIO_ONLY_CLIENT, typeFlag = FLAG_WITH_EVENT, event = 200,
            sessionId = sid, payload = pcm)
        return marshalRawAudio(m)
    }

    fun eventMessage(sid: String, json: String, event: Int): ByteArray {
        val m = Message(type = MsgType.FULL_CLIENT, typeFlag = FLAG_WITH_EVENT, event = event,
            sessionId = sid, payload = json.toByteArray(Charsets.UTF_8))
        return marshal(m)
    }

    fun generateSessionId(): String = UUID.randomUUID().toString()
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd doubao_chitchat && ./gradlew :app:testDebugUnitTest --tests "com.openclaw.chitchat.ProtocolTest"`
Expected: 5 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add doubao_chitchat/app/src
git commit -m "feat(chitchat): 二进制协议层 Protocol.kt + 字节 fixture 单测

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `Config.kt` + payload data class（TDD）

封装鉴权常量 + StartSession payload 构造。**修正点**：`model="1.2.1.1"`（非 demo 的 `"O"`）。

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/Config.kt`
- Test: `app/src/test/java/com/openclaw/chitchat/ConfigPayloadTest.kt`

**Interfaces:**
- Consumes: `Protocol`（无）。
- Produces: `Config.WS_URL`, `Config.headers(appId, accessKey, connectId)`, `Config.StartSession`, `Config.toStartSessionJson(systemRole, speaker)`, 常量 `INPUT_SAMPLE_RATE=16000`, `OUTPUT_SAMPLE_RATE=24000`, `AUDIO_CHUNK_BYTES=640`.

- [ ] **Step 1: 写失败测试**

`app/src/test/java/com/openclaw/chitchat/ConfigPayloadTest.kt`:
```kotlin
package com.openclaw.chitchat

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Test

class ConfigPayloadTest {
    @Test fun start_session_json_has_model_1_2_1_1_and_pcm_s16le() {
        val json = Config.toStartSessionJson(systemRole = "你是车载伙伴", speaker = Config.DEFAULT_SPEAKER)
        val root = JsonParser.parseString(json).asJsonObject
        assertEquals("1.2.1.1", root.getAsJsonObject("dialog").getAsJsonObject("extra").get("model").asString)
        assertEquals("audio", root.getAsJsonObject("dialog").getAsJsonObject("extra").get("input_mod").asString)
        val ac = root.getAsJsonObject("tts").getAsJsonObject("audio_config")
        assertEquals("pcm_s16le", ac.get("format").asString)
        assertEquals(24000, ac.get("sample_rate").asInt)
        assertEquals(Config.DEFAULT_SPEAKER, root.getAsJsonObject("tts").get("speaker").asString)
    }

    @Test fun headers_include_auth_keys() {
        val h = Config.headers("APP123", "KEY456", "cid")
        assertEquals("APP123", h["X-Api-App-ID"])
        assertEquals("KEY456", h["X-Api-Access-Key"])
        assertEquals("volc.speech.dialog", h["X-Api-Resource-Id"])
        assertEquals("PlgvMymc7f3tQnJ6", h["X-Api-App-Key"])
        assertEquals("cid", h["X-Api-Connect-Id"])
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.chitchat.ConfigPayloadTest"`
Expected: 编译失败（Config 未定义）。

- [ ] **Step 3: 实现 `Config.kt`**

`app/src/main/java/com/openclaw/chitchat/Config.kt`:
```kotlin
package com.openclaw.chitchat

import com.google.gson.Gson

object Config {
    const val WS_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
    const val RESOURCE_ID = "volc.speech.dialog"
    const val APP_KEY = "PlgvMymc7f3tQnJ6"

    const val INPUT_SAMPLE_RATE = 16000
    const val OUTPUT_SAMPLE_RATE = 24000
    const val CHANNELS = 1
    const val AUDIO_CHUNK_BYTES = 640        // 20ms @ 16kHz int16
    const val SEND_INTERVAL_MS = 20L

    const val DEFAULT_SPEAKER = "zh_female_vv_jupiter_bigtts"
    const val MODEL = "1.2.1.1"              // O2.0（修正：demo 用 "O"）
    const val PCM_FORMAT = "pcm_s16le"

    const val DEFAULT_SYSTEM_ROLE = "你是一个温暖、幽默、知识广博的车载语音伙伴。陪用户聊天解闷，回答简洁自然，像朋友一样。"
    const val DEFAULT_SPEAKING_STYLE = "说话简洁口语化，语气亲切自然。"
    const val DEFAULT_BOT_NAME = "小闲"

    fun headers(appId: String, accessKey: String, connectId: String): Map<String, String> = mapOf(
        "X-Api-App-ID" to appId,
        "X-Api-Access-Key" to accessKey,
        "X-Api-Resource-Id" to RESOURCE_ID,
        "X-Api-App-Key" to APP_KEY,
        "X-Api-Connect-Id" to connectId
    )

    private data class AudioConfig(val channel: Int = CHANNELS, val format: String = PCM_FORMAT, val sample_rate: Int = OUTPUT_SAMPLE_RATE)
    private data class Tts(val speaker: String, val audio_config: AudioConfig = AudioConfig())
    private data class DialogExtra(val model: String = MODEL, val input_mod: String = "audio", val strict_audit: Boolean = false)
    private data class Dialog(val dialog_id: String = "", val bot_name: String = DEFAULT_BOT_NAME,
                              val system_role: String, val speaking_style: String = DEFAULT_SPEAKING_STYLE,
                              val extra: DialogExtra = DialogExtra())
    private data class Asr(val extra: Map<String, Any> = emptyMap())
    private data class StartSession(val asr: Asr = Asr(), val tts: Tts, val dialog: Dialog)

    fun toStartSessionJson(systemRole: String = DEFAULT_SYSTEM_ROLE, speaker: String = DEFAULT_SPEAKER): String {
        val payload = StartSession(tts = Tts(speaker), dialog = Dialog(system_role = systemRole))
        return Gson().toJson(payload)
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.chitchat.ConfigPayloadTest"`
Expected: 2 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add doubao_chitchat/app/src
git commit -m "feat(chitchat): Config 鉴权 + StartSession payload（model=1.2.1.1 修正）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `RealtimeClient.kt`（OkHttp WebSocket + 事件分发）

封装 OkHttp WebSocket：建连（带鉴权 header）、发送字节、把收到的二进制帧 `unmarshal` 后按 type 分发到 listener。

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/RealtimeClient.kt`

**Interfaces:**
- Consumes: `Protocol.marshal/unmarshal/audioFrame/...`, `Config.WS_URL`, `Config.headers`.
- Produces:
  - `interface RealtimeListener { fun onOpen(); fun onEvent(event:Int, sessionId:String?, payload:ByteArray?); fun onAudio(payload:ByteArray); fun onError(code:Int, msg:String); fun onClose(code:Int, reason:String) }`
  - `class RealtimeClient(appId, accessKey, connectId, listener)`：`fun connect()`、`fun send(bytes:ByteArray)`、`fun close()`.

- [ ] **Step 1: 实现 `RealtimeClient.kt`**

`app/src/main/java/com/openclaw/chitchat/RealtimeClient.kt`:
```kotlin
package com.openclaw.chitchat

import okhttp3.*
import okio.ByteString

interface RealtimeListener {
    fun onOpen()
    fun onEvent(event: Int, sessionId: String?, payload: ByteArray?)
    fun onAudio(payload: ByteArray)
    fun onError(code: Int, msg: String)
    fun onClose(code: Int, reason: String)
}

class RealtimeClient(
    private val appId: String,
    private val accessKey: String,
    private val connectId: String,
    private val listener: RealtimeListener
) {
    private val client = OkHttpClient()
    private var ws: WebSocket? = null

    fun connect() {
        val request = Request.Builder().url(Config.WS_URL).apply {
            Config.headers(appId, accessKey, connectId).forEach { (k, v) -> header(k, v) }
        }.build()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = listener.onOpen()
            override fun onMessage(webSocket: WebSocket, text: String) {
                // 服务端主要走二进制，文本兜底忽略
            }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val data = bytes.toByteArray()
                try {
                    val msg = Protocol.unmarshal(data)
                    when (msg.type) {
                        Protocol.MsgType.FULL_SERVER -> listener.onEvent(msg.event, msg.sessionId, msg.payload)
                        Protocol.MsgType.AUDIO_ONLY_SERVER ->
                            if (msg.payload != null) listener.onAudio(msg.payload)
                        Protocol.MsgType.ERROR -> listener.onError(msg.event, msg.payload?.toString(Charsets.UTF_8) ?: "")
                        else -> {}
                    }
                } catch (e: Exception) {
                    listener.onError(-1, "unmarshal failed: ${e.message}")
                }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
                listener.onClose(-1, "failure: ${t.message}")
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = listener.onClose(code, reason)
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
        })
    }

    fun send(bytes: ByteArray): Boolean = ws?.send(ByteString.of(*bytes)) ?: false
    fun close() { ws?.close(1000, null); ws = null }
}
```

- [ ] **Step 2: 编译验证**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: Commit**

```bash
git add doubao_chitchat/app/src/main/java/com/openclaw/chitchat/RealtimeClient.kt
git commit -m "feat(chitchat): RealtimeClient OkHttp WebSocket + 事件分发

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `AudioRecorder.kt`（AudioRecord 录音）

16kHz/mono/int16，每 20ms（640 字节）读一包，通过回调送出。需要在真机验证（权限），逻辑层用回调解耦。

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/AudioRecorder.kt`

**Interfaces:**
- Consumes: `Config.INPUT_SAMPLE_RATE`, `Config.AUDIO_CHUNK_BYTES`, `Config.SEND_INTERVAL_MS`.
- Produces: `class AudioRecorder { fun start(onChunk:(ByteArray)->Unit); fun stop() }`.

- [ ] **Step 1: 实现 `AudioRecorder.kt`**

`app/src/main/java/com/openclaw/chitchat/AudioRecorder.kt`:
```kotlin
package com.openclaw.chitchat

import android.Manifest
import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.annotation.RequiresPermission
import kotlinx.coroutines.*

class AudioRecorder(private val scope: CoroutineScope) {
    private var record: AudioRecord? = null
    private var job: Job? = null
    @Volatile private var running = false

    @SuppressLint("MissingPermission")
    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    fun start(onChunk: (ByteArray) -> Unit) {
        val minBuf = AudioRecord.getMinBufferSize(
            Config.INPUT_SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val bufSize = maxOf(minBuf, Config.AUDIO_CHUNK_BYTES * 4)
        record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            Config.INPUT_SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufSize
        )
        running = true
        record?.startRecording()
        job = scope.launch(Dispatchers.IO) {
            val buf = ByteArray(Config.AUDIO_CHUNK_BYTES)
            while (isActive && running) {
                val n = record?.read(buf, 0, buf.size) ?: -1
                if (n > 0) onChunk(buf.copyOf(n))
                delay(Config.SEND_INTERVAL_MS)
            }
        }
    }

    fun stop() {
        running = false
        job?.cancel()
        record?.stop()
        record?.release()
        record = null
    }
}
```

- [ ] **Step 2: 编译验证**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: Commit**

```bash
git add doubao_chitchat/app/src/main/java/com/openclaw/chitchat/AudioRecorder.kt
git commit -m "feat(chitchat): AudioRecorder 16kHz 录音 + 20ms 分包

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `AudioPlayer.kt`（AudioTrack 播放 + 打断）

24kHz/mono/s16le 流式播放；`interrupt()` 清队列 + flush（修正点：demo 缺）。

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/AudioPlayer.kt`

**Interfaces:**
- Consumes: `Config.OUTPUT_SAMPLE_RATE`, `Config.CHANNELS`.
- Produces: `class AudioPlayer { fun start(); fun feed(pcm:ByteArray); fun interrupt(); fun stop() }`.

- [ ] **Step 1: 实现 `AudioPlayer.kt`**

`app/src/main/java/com/openclaw/chitchat/AudioPlayer.kt`:
```kotlin
package com.openclaw.chitchat

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class AudioPlayer(private val scope: CoroutineScope) {
    private var track: AudioTrack? = null
    private var job: Job? = null
    private val mutex = Mutex()
    @Volatile private var channel: Channel<ByteArray>? = null
    @Volatile private var running = false

    fun start() {
        val sampleRate = Config.OUTPUT_SAMPLE_RATE
        val bufSize = AudioTrack.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        track = AudioTrack(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
            AudioFormat.Builder().setSampleRate(sampleRate)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build(),
            maxOf(bufSize, 8192),
            AudioTrack.MODE_STREAM,
            AudioManager.AUDIO_SESSION_ID_GENERATE
        )
        channel = Channel(capacity = 64)
        running = true
        track?.play()
        job = scope.launch(Dispatchers.IO) {
            val ch = channel!!
            try {
                for (pcm in ch) {
                    if (!running) break
                    if (pcm.size % 2 == 0) track?.write(pcm, 0, pcm.size)
                }
            } catch (_: CancellationException) {}
        }
    }

    fun feed(pcm: ByteArray) {
        channel?.trySend(pcm)
    }

    /** 打断：清空排队音频 + 立即静音。ASRInfo(450) 时调用。 */
    fun interrupt() = runBlocking {
        mutex.withLock {
            val old = channel
            old?.close()
            channel = Channel(capacity = 64)
            track?.pause()
            track?.flush()
            track?.play()
        }
    }

    fun stop() {
        running = false
        channel?.close()
        job?.cancel()
        track?.stop()
        track?.flush()
        track?.release()
        track = null
    }
}
```

- [ ] **Step 2: 编译验证**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: Commit**

```bash
git add doubao_chitchat/app/src/main/java/com/openclaw/chitchat/AudioPlayer.kt
git commit -m "feat(chitchat): AudioTrack 播放 + ASRInfo 打断（清队列+flush）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: `CallManager.kt`（状态机 + 编排 + 重连）

整合 Protocol/RealtimeClient/AudioRecorder/AudioPlayer，实现连接→会话→录音→播放→打断→结束→重连。

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/CallManager.kt`

**Interfaces:**
- Consumes: `Protocol.*`, `Config.*`, `RealtimeClient`+`RealtimeListener`, `AudioRecorder`, `AudioPlayer`.
- Produces:
  - `enum class CallState { IDLE, CONNECTING, READY, LISTENING, USER_SPEAKING, ASSISTANT_SPEAKING, FINISHING, RECONNECTING, ERROR }`
  - `interface CallUi { fun onState(s:CallState); fun onAsrText(text:String, isFinal:Boolean); fun onError(msg:String) }`
  - `class CallManager(scope, appId, accessKey, ui)`：`suspend fun start()`、`suspend fun finish()`.

- [ ] **Step 1: 实现 `CallManager.kt`**

`app/src/main/java/com/openclaw/chitchat/CallManager.kt`:
```kotlin
package com.openclaw.chitchat

import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

enum class CallState { IDLE, CONNECTING, READY, LISTENING, USER_SPEAKING, ASSISTANT_SPEAKING, FINISHING, RECONNECTING, ERROR }

interface CallUi {
    fun onState(s: CallState)
    fun onAsrText(text: String, isFinal: Boolean)
    fun onError(msg: String)
}

class CallManager(
    private val scope: CoroutineScope,
    private val appId: String,
    private val accessKey: String,
    private val ui: CallUi
) : RealtimeListener {
    private val gson = Gson()
    private val stateMutex = Mutex()
    private var client: RealtimeClient? = null
    private var recorder: AudioRecorder? = null
    private var player: AudioPlayer? = null
    private var sessionId: String = Protocol.generateSessionId()
    private var dialogId: String = ""

    @Volatile private var connected = false
    @Volatile private var sessionReady = false
    @Volatile private var finishing = false
    private var reconnectAttempts = 0

    // 等 SessionStarted(150) 的桥
    private var sessionReadySignal: CompletableDeferred<Unit>? = null

    suspend fun start() {
        setState(CallState.CONNECTING)
        player = AudioPlayer(scope).also { it.start() }
        client = RealtimeClient(appId, accessKey, sessionId, this)
        client?.connect()
    }

    // ---- RealtimeListener ----
    override fun onOpen() {
        connected = true
        scope.launch { handshake() }
    }

    private suspend fun handshake() {
        client?.send(Protocol.startConnection())
        val payload = Config.toStartSessionJson()
        sessionReadySignal = CompletableDeferred()
        client?.send(Protocol.startSession(sessionId, payload))
        // 等 SessionStarted(150)
        try { withTimeout(30_000) { sessionReadySignal?.await() } }
        catch (e: Exception) { ui.onError("会话启动超时"); setState(CallState.ERROR); return }
        // 主动开口
        client?.send(Protocol.eventMessage(sessionId, gson.toJson(mapOf("content" to "你好，我是小闲，有什么想聊的吗？")), 300))
        // 开始录音上传
        recorder = AudioRecorder(scope)
        recorder?.start { chunk -> client?.send(Protocol.audioFrame(sessionId, chunk)) }
        setState(CallState.LISTENING)
    }

    override fun onEvent(event: Int, sessionId: String?, payload: ByteArray?) {
        scope.launch {
            when (event) {
                150 -> { // SessionStarted
                    payload?.toString(Charsets.UTF_8)?.let {
                        runCatching { dialogId = gson.fromJson(it, JsonObject::class.java).get("dialog_id")?.asString ?: "" }
                    }
                    sessionReadySignal?.complete(Unit)
                }
                450 -> { // ASRInfo：用户开口 → 打断播放
                    player?.interrupt()
                    setState(CallState.USER_SPEAKING)
                }
                451 -> { // ASRResponse：识别文本
                    payload?.toString(Charsets.UTF_8)?.let { raw ->
                        runCatching {
                            val obj = gson.fromJson(raw, JsonObject::class.java)
                            val arr = obj.getAsJsonArray("results")
                            arr?.forEach { r ->
                                val ro = r.asJsonObject
                                ui.onAsrText(ro.get("text")?.asString ?: "", !(ro.get("is_interim")?.asBoolean ?: true))
                            }
                        }
                    }
                }
                459 -> setState(CallState.LISTENING)        // ASREnded
                350 -> setState(CallState.ASSISTANT_SPEAKING) // TTSSentenceStart
                359 -> setState(CallState.LISTENING)        // TTSEnded
                51, 153 -> reconnect("连接/会话失败 event=$event")
                599 -> payload?.toString(Charsets.UTF_8)?.let { ui.onError("服务端错误: $it") }
            }
        }
    }

    override fun onAudio(payload: ByteArray) {
        player?.feed(payload)
    }

    override fun onError(code: Int, msg: String) {
        ui.onError("错误[$code]: $msg")
        if (code.toString().startsWith("5") || code == -1) reconnect("onError $code")
    }

    override fun onClose(code: Int, reason: String) {
        if (finishing) return
        reconnect("连接关闭: $reason")
    }

    private fun reconnect(reason: String) {
        if (finishing) return
        if (reconnectAttempts >= 3) {
            setState(CallState.ERROR); ui.onError("重连失败：$reason"); return
        }
        reconnectAttempts++
        setState(CallState.RECONNECTING)
        scope.launch {
            delay((1000L shl (reconnectAttempts - 1))) // 1s,2s,4s
            recorder?.stop(); player?.stop(); client?.close()
            connected = false; sessionReady = false
            sessionId = Protocol.generateSessionId()
            start()
        }
    }

    suspend fun finish() {
        finishing = true
        setState(CallState.FINISHING)
        recorder?.stop()
        runCatching { client?.send(Protocol.eventMessage(sessionId, "{}", 102)) } // FinishSession
        delay(200)
        client?.close()
        player?.stop()
        setState(CallState.IDLE)
    }

    private fun setState(s: CallState) = runBlocking { stateMutex.withLock { ui.onState(s) } }
}
```

- [ ] **Step 2: 编译验证**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: Commit**

```bash
git add doubao_chitchat/app/src/main/java/com/openclaw/chitchat/CallManager.kt
git commit -m "feat(chitchat): CallManager 状态机 + 编排 + 指数退避重连

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: UI（ViewModel + Activity + 布局）

**Files:**
- Create: `app/src/main/java/com/openclaw/chitchat/ui/ChitchatViewModel.kt`
- Modify: `app/src/main/java/com/openclaw/chitchat/ui/ChitchatActivity.kt`（替换 Task 1 占位）
- Create: `app/src/main/res/layout/activity_chitchat.xml`

**Interfaces:**
- Consumes: `CallManager`, `CallState`, `CallUi`, `BuildConfig.DOUBAO_APP_ID`/`DOUBAO_ACCESS_KEY`.

- [ ] **Step 1: 实现 ViewModel**

`app/src/main/java/com/openclaw/chitchat/ui/ChitchatViewModel.kt`:
```kotlin
package com.openclaw.chitchat.ui

import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.openclaw.chitchat.CallState
import com.openclaw.chitchat.CallUi

class ChitchatViewModel : ViewModel(), CallUi {
    val state = MutableLiveData(CallState.IDLE)
    val subtitle = MutableLiveData("")
    val errorMsg = MutableLiveData("")

    override fun onState(s: CallState) { state.postValue(s) }
    override fun onAsrText(text: String, isFinal: Boolean) {
        subtitle.postValue(text)
    }
    override fun onError(msg: String) { errorMsg.postValue(msg) }

    fun stateText(s: CallState?): String = when (s) {
        CallState.IDLE -> "空闲"
        CallState.CONNECTING -> "连接中…"
        CallState.READY, CallState.LISTENING -> "聆听中"
        CallState.USER_SPEAKING -> "你说话中"
        CallState.ASSISTANT_SPEAKING -> "回复中"
        CallState.RECONNECTING -> "重连中…"
        CallState.FINISHING -> "结束中…"
        CallState.ERROR -> "出错"
        null -> ""
    }
}
```

- [ ] **Step 2: 布局**

`app/src/main/res/layout/activity_chitchat.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:gravity="center"
    android:background="#111418"
    android:padding="32dp">

    <TextView
        android:id="@+id/stateText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:textColor="#8AB4F8"
        android:textSize="20sp"
        android:text="空闲" />

    <TextView
        android:id="@+id/subtitleText"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="24dp"
        android:gravity="center"
        android:textColor="#FFFFFF"
        android:textSize="22sp"
        android:text="" />

    <TextView
        android:id="@+id/errorText"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:layout_marginTop="24dp"
        android:textColor="#F28B82"
        android:textSize="14sp" />
</LinearLayout>
```

- [ ] **Step 3: 实现 Activity（含 lifecycle/权限/音频焦点接线）**

`app/src/main/java/com/openclaw/chitchat/ui/ChitchatActivity.kt`（替换占位）:
```kotlin
package com.openclaw.chitchat.ui

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.Observer
import com.openclaw.chitchat.BuildConfig
import com.openclaw.chitchat.CallManager
import com.openclaw.chitchat.CallState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class ChitchatActivity : AppCompatActivity() {
    private val vm = ChitchatViewModel()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var manager: CallManager? = null
    private lateinit var audioManager: AudioManager
    private var focusRequest: AudioFocusRequest? = null

    private val requestMic = registerForActivityResult(
        ActivityResultContracts.RequestPermission()) { granted -> if (granted) beginSession() else vm.onError("需要麦克风权限") }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_chitchat)
        audioManager = getSystemService(AUDIO_SERVICE) as AudioManager

        findViewById<TextView>(R.id.stateText).apply {
            vm.state.observe(this@ChitchatActivity) { text = vm.stateText(it) }
        }
        vm.subtitle.observe(this) { findViewById<TextView>(R.id.subtitleText).text = it }
        vm.errorMsg.observe(this) { findViewById<TextView>(R.id.errorText).text = it }
    }

    override fun onResume() {
        super.onResume()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED) beginSession()
        else requestMic.launch(Manifest.permission.RECORD_AUDIO)
    }

    override fun onPause() {
        super.onPause()
        scope.launch { manager?.finish() }
        abandonFocus()
    }

    private fun beginSession() {
        if (manager != null) return
        if (BuildConfig.DOUBAO_APP_ID.isBlank() || BuildConfig.DOUBAO_ACCESS_KEY.isBlank()) {
            vm.onError("未配置 DOUBAO_APP_ID/ACCESS_KEY（~/.gradle/gradle.properties）"); return
        }
        requestFocus()
        manager = CallManager(scope, BuildConfig.DOUBAO_APP_ID, BuildConfig.DOUBAO_ACCESS_KEY, vm)
        scope.launch { manager?.start() }
    }

    private fun requestFocus() {
        val attrs = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).build()
        focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attrs).build()
        audioManager.requestAudioFocus(focusRequest!!)
    }

    private fun abandonFocus() { focusRequest?.let { audioManager.abandonAudioFocusRequest(it) } }

    override fun onDestroy() { super.onDestroy(); scope.coroutineContext.cancel() }
}
```

- [ ] **Step 4: 编译验证**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 5: Commit**

```bash
git add doubao_chitchat/app/src
git commit -m "feat(chitchat): UI + 生命周期/权限/音频焦点接线

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 单测全量回归 + 配置接入文档

**Files:**
- Modify: `doubao_chitchat/README.md`（新建，说明鉴权配置）

- [ ] **Step 1: 跑全部单测**

Run: `cd doubao_chitchat && ./gradlew :app:testDebugUnitTest`
Expected: ProtocolTest(5) + ConfigPayloadTest(2) 全 PASS。

- [ ] **Step 2: 写配置说明 README**

`doubao_chitchat/README.md`:
```markdown
# 豆包 Realtime 闲聊 App

独立 Android app，豆包端到端 Realtime API 纯语音闲聊。

## 配置鉴权
在 `~/.gradle/gradle.properties` 加（不入库）：
```
doubaoAppId=你的AppID
doubaoAccessKey=你的AccessKey
```

## 构建/安装
```
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell pm grant com.openclaw.chitchat android.permission.RECORD_AUDIO
```
```

- [ ] **Step 3: Commit**

```bash
git add doubao_chitchat/README.md
git commit -m "docs(chitchat): 鉴权配置与构建说明

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: BYD 真机端到端验证

无代码改动，按 spec §10 成功标准在车机上验证。

**Files:** 无（验证 task）

- [ ] **Step 1: 构建并安装到车机**

Run:
```bash
cd /home/tsm/work/android_agent/doubao_chitchat
./gradlew assembleDebug
adb -s <车机serial> install -r app/build/outputs/apk/debug/app-debug.apk
adb -s <车机serial> shell pm grant com.openclaw.chitchat android.permission.RECORD_AUDIO
```

- [ ] **Step 2: 抓 logcat 看连接**

Run: `adb -s <车机serial> logcat | grep -i "chitchat\|realtime\|X-Tt-Logid"`
Expected: 看到 WebSocket 连接建立、StartSession、SessionStarted(150)。

- [ ] **Step 3: 逐项验证成功标准**

人工验证：
1. 打开 app → 模型开口播开场白（"你好，我是小闲…"）→ **PASS/FAIL**
2. 用户说话 → 字幕（subtitleText）刷新 → 模型语音回复 → **PASS/FAIL**
3. 模型说话时插话 → 立即停止（打断生效）→ **PASS/FAIL**
4. 连续 5+ 轮稳定对话 → **PASS/FAIL**
5. 无崩溃跑 10 分钟 → **PASS/FAIL**

- [ ] **Step 4: 记录首响延迟**

在 CallManager 的 459(用户说完) 与首个 352(音频) 之间打时间戳（临时日志），对比 VoxCPM2 的 561–638ms。记录到 `docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md` 末尾"实测"小节。

- [ ] **Step 5: 验证失败则回到对应 Task 修复**

常见问题排查：
- 连接失败 → 查鉴权 header、App ID/Key 是否注入（BuildConfig）
- 无声 → 查 RECORD_AUDIO 权限（`adb pm grant`）、AudioRecord/AudioTrack 初始化
- 打断无效 → 查 AudioPlayer.interrupt() 是否在 450 时调用、Channel 是否重建
- `55000001 ContextCanceled` → finish() 是否等了 152（当前实现 delay 200ms，必要时改等事件）

- [ ] **Step 6: 验证通过后 Commit 验证记录**

```bash
git add docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md
git commit -m "test(chitchat): BYD 真机端到端验证记录

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review（已执行）

- **Spec 覆盖**：§3 架构→T1；§4 协议→T2；§5 音频→T5/T6；§6 状态机→T7；§3 RealtimeClient→T4；payload/model 修正→T3；§7 权限/生命周期/音频焦点→T8；§8 错误重连→T7；§9 六修正点→散布各 T（model=T3、打断=T6、错误重连=T7、json/ws/音频层=T2-T6）；§10 测试→T2/T3 单测+T10 端到端；§11 部署→T9/T10。全覆盖。
- **Placeholder 扫描**：无 TBD/TODO；每个代码 step 均含完整代码。
- **类型一致**：`CallState`、`CallUi`、`RealtimeListener`、`Protocol.Message` 等签名在各 Task 间一致；打断方法统一为 `AudioPlayer.interrupt()`。
