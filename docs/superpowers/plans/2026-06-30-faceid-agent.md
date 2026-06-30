# FaceID 接入 Agent 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** faceid 识别到注册用户 → 切换 session key + 软链接记忆 → gateway LLM 个性化语音问候，复用 ppt-voice 的 chat/TTS 链路。

**Architecture:** app 后台 FaceIdService 每秒检测(OMS+yunet MDLA) → 连续3帧确认用户变化 → 换 session key(`agent:main:face-{userid}`，不 kill gateway) + MEMORY.md 软链接切 per-user 记忆 → POST gateway 问候 → TTS。FloatingBubbleService 的 session key 改读全局 currentSessionKey（问候+后续对话同 session 连贯）。

**Tech Stack:** Kotlin(Android), FaceEngine(yunet+R50 MDLA), OkHttp, openclaw gateway(`/v1/chat/completions` + `x-openclaw-session-key` header), adb shell(ln -sf 软链接记忆)

**Spec:** `docs/superpowers/specs/2026-06-30-faceid-agent-design.md`

## Global Constraints

- session key 格式: `agent:main:face-{userid}`（userid = gallery 注册名，小写英文/数字）
- gateway auth: `Authorization: Bearer fe3936a8d8dafeec8efb6d801863eb00c4c08298555a4817`
- gateway URL: `http://127.0.0.1:18801/v1/chat/completions`
- 软链接记忆: `workspace/MEMORY.md → memory_faceid_{userid}.md`，必须 `chown u10_a150:u10_a150`（gateway 才读得到，已实测）
- workspace 路径: `/data/local/tmp/openclaw-home/.openclaw/workspace/`
- faceid 检测: centerCrop 主驾(忽略旁边人)，连续3帧同 userid 才确认切换（防抖），cos≥0.5
- 冷却: MVP 关闭（不设时间窗口），防反复靠连续3帧 + 切换开关
- adb 操作需 root（`adb root`），软链接/ln 要 root

## File Structure

- **Create** `app/src/main/java/com/openclaw/car/face/SessionKey.kt` — 全局 currentSessionKey 单例 + 变化监听
- **Create** `app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt` — 软链接切换 per-user 记忆(root shell ln+chown)
- **Create** `app/src/main/java/com/openclaw/car/face/GreetingTrigger.kt` — POST gateway 个性化问候
- **Create** `app/src/main/java/com/openclaw/car/service/FaceIdService.kt` — 后台 Service 检测循环 + 防抖 + 编排切换/问候
- **Modify** `app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt:734` — session key 从固定常量改读 SessionKey
- **Modify** `app/src/main/res/layout/activity_main.xml` — 底部加「切换开关」按钮
- **Modify** `app/src/main/java/com/openclaw/car/MainActivity.kt` — 开关接线（控制 FaceIdService）
- **Modify** `app/src/main/AndroidManifest.xml` — 声明 FaceIdService
- **Test** `app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt` — JVM unit test

---

### Task 1: SessionKey 全局管理

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/SessionKey.kt`
- Test: `app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt`

**Interfaces:**
- Produces: `SessionKey.current: String`（getter）, `SessionKey.setToUser(userid: String)`（切换到 face-{userid}）, `SessionKey.resetToDefault()`（回 ppt-voice）, `SessionKey.listener: ((String)->Unit)?`（变化回调）

- [ ] **Step 1: 写失败测试**

```kotlin
// app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt
package com.openclaw.car.face
import org.junit.Assert.assertEquals
import org.junit.Test

class SessionKeyTest {
    @Test fun default_is_ppt_voice() {
        SessionKey.resetToDefault()
        assertEquals("agent:main:ppt-voice", SessionKey.current)
    }
    @Test fun setToUser_formats_face_key() {
        SessionKey.setToUser("zhangsan")
        assertEquals("agent:main:face-zhangsan", SessionKey.current)
    }
    @Test fun listener_fires_on_change() {
        var heard = ""
        SessionKey.listener = { heard = it }
        SessionKey.setToUser("lisi")
        assertEquals("agent:main:face-lisi", heard)
        SessionKey.listener = null
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd agent_front_app && ./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SessionKeyTest" --no-daemon`
Expected: FAIL（SessionKey 未定义）

- [ ] **Step 3: 实现 SessionKey**

```kotlin
// app/src/main/java/com/openclaw/car/face/SessionKey.kt
package com.openclaw.car.face

/** 全局当前 openclaw session key。faceid 切换用户时改，ppt-voice 读它保持同 session。 */
object SessionKey {
    private const val DEFAULT = "agent:main:ppt-voice"
    @Volatile private var key: String = DEFAULT
    @Volatile var listener: ((String) -> Unit)? = null

    val current: String get() = key

    fun setToUser(userid: String) {
        key = "agent:main:face-$userid"
        listener?.invoke(key)
    }

    fun resetToDefault() {
        key = DEFAULT
        listener?.invoke(key)
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SessionKeyTest" --no-daemon`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/SessionKey.kt app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt
git commit -m "feat(face): add SessionKey global for faceid session switching"
```

---

### Task 2: MemorySwitcher 软链接切换

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt`

**Interfaces:**
- Consumes: userid（String）
- Produces: `MemorySwitcher.switchTo(userid: String): Boolean`（成功返回 true）
- 依赖: adb root（app 内 exec `su -c` 或 Runtime；MVP 用 Runtime.exec 跑 `ln -sf` + `chown`，需设备 root 或 shell 权限）

注意：app 是 u10_a150，`ln -sf` 在 workspace（u10_a150 拥有）可能直接可执行（实测 root 做的，app 内待验证；若 app 无权，降级走 adb shell 或 NodeProcessService 的 root 通道）。

- [ ] **Step 1: 实现 MemorySwitcher**

```kotlin
// app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt
package com.openclaw.car.face

import android.util.Log
import java.io.File

/** 切换 workspace/MEMORY.md 软链接到 per-user memory_faceid_{userid}.md（gateway 跟链接读 per-user 记忆）。 */
object MemorySwitcher {
    private const val TAG = "MemorySwitcher"
    private const val WS = "/data/local/tmp/openclaw-home/.openclaw/workspace"

    fun switchTo(userid: String): Boolean {
        val target = "memory_faceid_$userid.md"
        val targetFile = File("$WS/$target")
        if (!targetFile.exists()) targetFile.writeText("")  // 首次注册用户建空
        // ln -sf 覆盖软链接 + chown（gateway 要求 u10_a150）
        val cmd = "ln -sf $target $WS/MEMORY.md && chown u10_a150:u10_a150 $WS/MEMORY.md $WS/$target"
        return try {
            val proc = Runtime.getRuntime().exec(arrayOf("sh", "-c", cmd))
            val code = proc.waitFor()
            Log.i(TAG, "switchTo($userid) exit=$code")
            code == 0
        } catch (e: Exception) {
            Log.e(TAG, "switchTo failed: ${e.message}")
            false
        }
    }
}
```

- [ ] **Step 2: 设备验证（手动，需 app 装车 + adb root）**

Run（装车后从 FaceIdService 触发，或临时 adb 验证）:
```bash
# 模拟 app 调用：建 test 用户记忆 + 软链接 + 看 gateway 读到
adb shell "echo '称呼:测试' > /data/local/tmp/openclaw-home/.openclaw/workspace/memory_faceid_testuser.md"
adb shell "ln -sf memory_faceid_testuser.md /data/local/tmp/openclaw-home/.openclaw/workspace/MEMORY.md && chown u10_a150:u10_a150 /data/local/tmp/openclaw-home/.openclaw/workspace/MEMORY.md"
adb shell "ls -la /data/local/tmp/openclaw-home/.openclaw/workspace/MEMORY.md"  # 应 -> memory_faceid_testuser.md
# gateway 读验证
curl -s -X POST http://localhost:18801/v1/chat/completions -H "Authorization: Bearer fe3936a8d8dafeec8efb6d801863eb00c4c08298555a4817" -H "x-openclaw-session-key: agent:main:face-testuser" -H "Content-Type: application/json" -d '{"model":"openclaw","messages":[{"role":"user","content":"我的称呼是?"}],"stream":false}' | grep -oE '"content":"[^"]*"'
# Expected: 回答含"测试"（读到 testuser 记忆）
```
Expected: 软链接指向正确，LLM 回答含 testuser 记忆内容。测完恢复 MEMORY.md（见 Task 6 清理）。

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt
git commit -m "feat(face): add MemorySwitcher symlink per-user memory"
```

---

### Task 3: GreetingTrigger 个性化问候

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/GreetingTrigger.kt`

**Interfaces:**
- Consumes: userid（String，当前 session 已切到 face-{userid}）
- Produces: `GreetingTrigger.greet(userid: String)`（异步 POST gateway，触发 LLM 问候 + TTS）
- 依赖: SessionKey.current（header）、gateway URL/token（同 FloatingBubbleService）

- [ ] **Step 1: 实现 GreetingTrigger**

```kotlin
// app/src/main/java/com/openclaw/car/face/GreetingTrigger.kt
package com.openclaw.car.face

import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** POST gateway /v1/chat/completions 触发个性化问候（走当前 session key + per-user 记忆，gateway 生成→TTS）。 */
object GreetingTrigger {
    private const val TAG = "GreetingTrigger"
    private const val URL = "http://127.0.0.1:18801/v1/chat/completions"
    private const val TOKEN = "fe3936a8d8dafeec8efb6d801863eb00c4c08298555a4817"
    private val http = OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()

    fun greet(userid: String) {
        Thread {
            try {
                val body = JSONObject().apply {
                    put("model", "openclaw")
                    put("messages", JSONArray().apply {
                        put(JSONObject().put("role", "system").put("content",
                            "检测到注册用户 $userid 上车，请根据记忆中的称呼/偏好自然问候（一句话）。"))
                        put(JSONObject().put("role", "user").put("content", "(用户上车)"))
                    })
                }
                val req = Request.Builder().url(URL)
                    .addHeader("Authorization", "Bearer $TOKEN")
                    .addHeader("x-openclaw-session-key", SessionKey.current)
                    .addHeader("Content-Type", "application/json")
                    .post(body.toString().toRequestBody("application/json".toMediaType())).build()
                val resp = http.newCall(req).execute()
                Log.i(TAG, "greet($userid) ${resp.code}: ${resp.body?.string()?.take(200)}")
                resp.close()
                // TTS 由 gateway→ppt-voice TTS 链路播报（同 session），或此处触发 TTS
            } catch (e: Exception) {
                Log.e(TAG, "greet failed: ${e.message}")
            }
        }.start()
    }
}
```

- [ ] **Step 2: 设备验证（curl 模拟）**

Run:
```bash
curl -s -X POST http://localhost:18801/v1/chat/completions \
  -H "Authorization: Bearer fe3936a8d8dafeec8efb6d801863eb00c4c08298555a4817" \
  -H "x-openclaw-session-key: agent:main:face-zhangsan" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw","messages":[{"role":"system","content":"检测到注册用户 zhangsan 上车，请根据记忆中的称呼/偏好自然问候（一句话）"},{"role":"user","content":"(用户上车)"}],"stream":false}' | grep -oE '"content":"[^"]*"'
```
Expected: 返回个性化问候（如"哥哥你好，上车啦"）。注意 TTS 播报链路：若 gateway 不自动 TTS，需 GreetingTrigger 拿 reply 文本调 TTS_URL（8091）—— 集成时确认 gateway 是否自动 TTS，否则在 greet() 里加 TTS 调用。

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/GreetingTrigger.kt
git commit -m "feat(face): add GreetingTrigger gateway personalized greeting"
```

---

### Task 4: FaceIdService 后台检测编排

**Files:**
- Create: `app/src/main/java/com/openclaw/car/service/FaceIdService.kt`
- Modify: `app/src/main/AndroidManifest.xml`（声明 Service）

**Interfaces:**
- Consumes: FaceRecognizer（detect+embed+match）、OMS pullFrame（从 LiveVideoFace 抽共享）、SessionKey、MemorySwitcher、GreetingTrigger
- Produces: `FaceIdService`（Android Service，start/stop 控制）、`FaceIdService.enabled`（切换开关）

- [ ] **Step 1: 抽 OMS pullFrame 到共享工具**

把 LiveVideoFaceFragment 的 `pullFrame()`（OkHttp GET /frame）抽到 `app/src/main/java/com/openclaw/car/face/OmsFrameSource.kt`（单例，FaceIdService 和 LiveVideoFace 共用）。

```kotlin
// app/src/main/java/com/openclaw/car/face/OmsFrameSource.kt
package com.openclaw.car.face
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

object OmsFrameSource {
    private const val URL = "http://192.168.195.47:18080/frame"
    private val http = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    fun pull(): Bitmap? = try {
        val r = Request.Builder().url(URL).build()
        http.newCall(r).execute().use { resp ->
            if (!resp.isSuccessful) return null
            val bytes = resp.body?.bytes() ?: return null
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }
    } catch (e: Exception) { Log.w("OmsFrameSource", "pull: ${e.message}"); null }
}
```

- [ ] **Step 2: 实现 FaceIdService**

```kotlin
// app/src/main/java/com/openclaw/car/service/FaceIdService.kt
package com.openclaw.car.service
import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.util.Log
import com.openclaw.car.face.*
import kotlin.concurrent.thread

class FaceIdService : Service() {
    companion object {
        private const val TAG = "FaceIdService"
        @Volatile var enabled = true  // 切换开关（false=只识别不切换/问候）
        private const val CONFIRM_FRAMES = 3  // 连续3帧确认(防抖)
        private const val COS_THR = 0.5f
    }
    private lateinit var recognizer: FaceRecognizer
    @Volatile private var running = false
    @Volatile private var currentUser: String? = null  // null=未锁定任何注册用户

    override fun onCreate() {
        super.onCreate()
        recognizer = FaceRecognizer(this)
        running = true
        thread { detectLoop() }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int) = START_STICKY
    override fun onBind(i: Intent?): IBinder? = null

    private fun detectLoop() {
        var pendingUser: String? = null
        var pendingCount = 0
        while (running) {
            try {
                if (!enabled) { Thread.sleep(1000); continue }  // 开关关=不切换
                val bmp = OmsFrameSource.pull()
                if (bmp != null) {
                    val r = recognizer.recognize(bmp)
                    val matched = if (r.status == Status.RECOGNIZED) r.id else null
                    if (matched != null && (r.score >= COS_THR)) {
                        if (matched == pendingUser) pendingCount++ else { pendingUser = matched; pendingCount = 1 }
                        if (pendingCount >= CONFIRM_FRAMES && matched != currentUser) {
                            switchUser(matched)
                        }
                    } else {
                        pendingUser = null; pendingCount = 0
                    }
                }
            } catch (e: Exception) { Log.e(TAG, "loop: ${e.message}") }
            Thread.sleep(1000)  // 每秒一次
        }
    }

    private fun switchUser(userid: String) {
        Log.i(TAG, "switch -> $userid")
        currentUser = userid
        SessionKey.setToUser(userid)
        MemorySwitcher.switchTo(userid)
        GreetingTrigger.greet(userid)
    }

    override fun onDestroy() { running = false; super.onDestroy() }
}
```

- [ ] **Step 3: AndroidManifest 声明 Service**

在 `<application>` 内加（仿 NodeProcessService）:
```xml
<service android:name=".service.FaceIdService"
         android:foregroundServiceType="specialUse"
         android:exported="false" />
```

- [ ] **Step 4: LiveVideoFaceFragment 改用 OmsFrameSource.pull()（替换内部 pullFrame，去重）**

把 LiveVideoFaceFragment 的 `pullFrame()` 调用改 `OmsFrameSource.pull()`，删 Fragment 内 pullFrame/http 字段。

- [ ] **Step 5: 编译 + 设备启动验证**

Run: `./gradlew assembleDebug && adb install -r app/build/outputs/apk/debug/app-debug.apk`
启动 FaceIdService（Task 5 开关接线后，或临时 adb am startservice）。看 logcat:
```bash
adb logcat -s FaceIdService FaceEngine
```
Expected: 每秒 detect INFER + embed INFER（MDLA），检测到注册用户时 `switch -> xxx` + GreetingTrigger/MemorySwitcher 日志。

- [ ] **Step 6: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/OmsFrameSource.kt app/src/main/java/com/openclaw/car/service/FaceIdService.kt app/src/main/AndroidManifest.xml app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt
git commit -m "feat(face): add FaceIdService background detection+switch+greet"
```

---

### Task 5: FloatingBubbleService 用动态 session key + 切换开关 UI

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt:734`
- Modify: `app/src/main/res/layout/activity_main.xml`
- Modify: `app/src/main/java/com/openclaw/car/MainActivity.kt`

- [ ] **Step 1: FloatingBubbleService session key 改读 SessionKey**

`FloatingBubbleService.kt:734`:
```kotlin
// 旧: .addHeader("x-openclaw-session-key", "agent:main:ppt-voice")
// 新:
.addHeader("x-openclaw-session-key", com.openclaw.car.face.SessionKey.current)
```
（import `com.openclaw.car.face.SessionKey`）

- [ ] **Step 2: activity_main.xml 底部加切换开关**

在主布局底部（status_panel 附近）加:
```xml
<com.google.android.material.materialswitch.MaterialSwitch
    android:id="@+id/switch_faceid"
    android:layout_width="wrap_content"
    android:layout_height="wrap_content"
    android:text="FaceID 切换"
    android:checked="true" />
```

- [ ] **Step 3: MainActivity 接线（开关 + 启动/停 FaceIdService）**

```kotlin
// MainActivity onViewCreated 内
val switchFaceId: com.google.android.material.materialswitch.MaterialSwitch = findViewById(R.id.switch_faceid)
// 启动 FaceIdService
startService(Intent(this, com.openclaw.car.service.FaceIdService::class.java))
com.openclaw.car.service.FaceIdService.enabled = true
switchFaceId.setOnCheckedChangeListener { _, isChecked ->
    com.openclaw.car.service.FaceIdService.enabled = isChecked
    if (!isChecked) com.openclaw.car.face.SessionKey.resetToDefault()
}
```

- [ ] **Step 4: 编译装车 + 验证开关**

Run: `./gradlew assembleDebug && adb install -r app-debug.apk && adb shell am start -n com.openclaw.car/.MainActivity`
- 开关切：FaceIdService.enabled=false，session key 回 ppt-voice（开关 UI 可见，关掉后不切换）
- 开关开：识别到注册用户触发 switch + 问候

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt app/src/main/res/layout/activity_main.xml app/src/main/java/com/openclaw/car/MainActivity.kt
git commit -m "feat(face): dynamic session key + FaceID switch toggle"
```

---

### Task 6: 端到端集成验证 + 清理

- [ ] **Step 1: 端到端测试（注册→切换→问候）**

设备准备：adb root + forward 18801 + yocto oms-grab/oms-http 在跑（见重启清单）+ 注册一个用户（LiveVideoFace 📸注册，如 "zhangsan"）+ MEMORY.md 软链接恢复原状。

操作：用户面对 OMS 镜头，FaceID 开关开。
看 logcat:
```bash
adb logcat -s FaceIdService GreetingTrigger MemorySwitcher SessionKey FaceEngine:* | grep -E "switch|greet|MEMORY|recognize"
```
Expected:
- `FaceIdService: switch -> zhangsan`
- `MemorySwitcher: switchTo(zhangsan) exit=0`
- `SessionKey` current = `agent:main:face-zhangsan`
- `GreetingTrigger: greet(zhangsan) 200`（LLM 个性化问候）
- TTS 播报问候
- 后续说话（ppt-voice）走 face-zhangsan session（连贯）

- [ ] **Step 2: 验证防抖（单人稳定不反复切）**

同一用户持续面对镜头，看 FaceIdService 不反复 switch（连续3帧确认后只切一次，currentUser 锁定）。

- [ ] **Step 3: 验证切换开关（关掉后不切）**

开关关 → 换人/离开 → FaceIdService 不 switch，session key 回 ppt-voice。

- [ ] **Step 4: 恢复 MEMORY.md（测试用软链接清理）**

```bash
WS=/data/local/tmp/openclaw-home/.openclaw/workspace
adb shell "rm $WS/MEMORY.md 2>/dev/null"  # 若是软链接,删链接不删target
# 恢复原 MEMORY.md（从 git 或备份）
```

- [ ] **Step 5: Commit（文档/记忆更新）**

更新 `docs/face-model-deployment.md` 加 faceid-agent 接入章节；记忆加 faceid-agent-design 指针。
```bash
git add docs/face-model-deployment.md
git commit -m "docs: faceid agent integration end-to-end verified"
```

---

## Self-Review

**Spec coverage:** 
- 检测每秒+防抖 → Task 4 FaceIdService ✅
- session key 切换不 kill → Task 1 SessionKey + Task 5 FloatingBubbleService ✅
- 软链接记忆 → Task 2 MemorySwitcher ✅
- 个性化问候 → Task 3 GreetingTrigger ✅
- 切换开关 → Task 5 ✅
- ppt-voice 同 session 连贯 → Task 5（FloatingBubbleService 读 currentSessionKey）✅
- 前端记忆显示自动换 → MEMORY.md 软链接（gateway/app 读跟链接，零改）✅

**Placeholder:** 无 TBD/TODO，代码完整。

**Type 一致:** SessionKey.current/setToUser、MemorySwitcher.switchTo、GreetingTrigger.greet、FaceIdService.enabled —— 各 task 引用一致。

**风险点（集成时确认）:**
1. MemorySwitcher 的 `ln -sf`/`chown` 在 app(u10_a150) 内执行权限——实测 root 可，app 内待验证（Task 2 Step2）；若无权，走 adb shell 或 NodeProcessService root 通道。
2. GreetingTrigger 的 TTS——gateway 是否自动 TTS，否则需手动调 TTS_URL（Task 3 Step2 确认）。
3. FaceRecognizer.recognize 现有返回 UNKNOWN 也带真实 cos（Task 4 用 r.score≥0.5，但 RECOGNIZED 才 r.id 有效，已处理）。
