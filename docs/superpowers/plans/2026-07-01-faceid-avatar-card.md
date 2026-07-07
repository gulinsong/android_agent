# FaceID 头像 + 欢迎 A2UI 卡片 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 注册时存人脸头像图片; 欢迎 GreetingTrigger 改用 A2UI 卡片(头像+问候) + TTS

**Architecture:** enrollFromOMS 时 crop 人脸→存 face_avatars/{userid}.jpg; GreetingTrigger 拿 reply 后构建 A2UI 卡片 JSON(Image+Text 模板), FloatingBubbleService.speakGreeting 显示卡片(InteractiveCardActivity) + TTS 播报。

**Tech Stack:** Kotlin, A2UI SDK(PicassoImageLoader file://), InteractiveCardActivity, streamingTtsPlayer

**Spec:** `docs/superpowers/specs/2026-07-01-faceid-avatar-card-design.md`

## Global Constraints

- 头像路径约定: `filesDir/face_avatars/{userid}.jpg`（注册时存）
- A2UI Image src 格式: `file:///data/user/10/com.openclaw.car/files/face_avatars/{userid}.jpg`
- 卡片 JSON 用 app 本地模板构建（不走 gateway A2UI 插件）
- InteractiveCardActivity 读 LatestCardJson.json 渲染
- 头像 crop: face box 扩大 20%
- 复用 FaceIdService.instance?.recognizer（避免 OOM）

---

### Task 1: 注册时 crop 人脸 + 存头像

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt` (enrollFromOMS)
- Modify: `app/src/main/java/com/openclaw/car/face/FaceRecognizer.kt` (enroll 返回 face box)

**Interfaces:**
- Consumes: FaceBox(x, y, w, h) from detect
- Produces: `filesDir/face_avatars/{userid}.jpg` 头像文件

- [ ] **Step 1: FaceRecognizer.enroll 返回 face box（当前只返回 Boolean）**

`FaceRecognizer.kt` enroll 方法改为返回 `FaceBox?`（成功时返回最中央脸 box，用于 crop；失败返回 null）：

```kotlin
// 旧: fun enroll(name: String, bitmap: Bitmap): Boolean
// 新:
fun enrollWithName(name: String, bitmap: Bitmap): com.openclaw.car.face.FaceBox? {
    val boxes = engine.detect(bitmap)
    val center = YuNetDecode.pickCenter(boxes, bitmap.width, bitmap.height) ?: return null
    val emb = engine.embed(alignTo(bitmap, center.landmarks))
    val existing = gallery.all()[name]
    val template = if (existing != null) FaceMath.l2normalize(FaceMath.mean(listOf(existing, emb)))
                   else emb
    gallery.enroll(name, template)
    gallery.save()
    return center  // 返回 face box 用于 crop
}
```

保留旧 `enroll(name, bitmap): Boolean` 调用 `enrollWithName` 避免 break 其他调用方。

- [ ] **Step 2: LiveVideoFaceFragment.enrollFromOMS crop + 存头像**

```kotlin
private fun enrollFromOMS() {
    val name = etName.text?.toString()?.trim().orEmpty()
    if (name.isEmpty()) { tvStatus.text = "❌ 请输入姓名"; return }
    tvStatus.text = "📸 抓取 OMS 帧注册 [$name]..."
    lifecycleScope.launch(Dispatchers.IO) {
        val bmp = OmsFrameSource.pull()
        if (bmp == null) { withContext(Dispatchers.Main) { tvStatus.text = "❌ 拉帧失败" } ; return@launch }
        val rec = recognizer
        if (rec == null) { withContext(Dispatchers.Main) { tvStatus.text = "❌ recognizer 未就绪" }; return@launch }
        val faceBox = rec.enrollWithName(name, bmp)
        if (faceBox == null) {
            withContext(Dispatchers.Main) { tvStatus.text = "❌ 未检测到正脸，请正对 OMS 镜头重试" }
            return@launch
        }
        // crop 人脸区域(box 扩大 20%) → 存头像
        val pad = 0.2f
        val x = (faceBox.x - faceBox.w * pad).coerceAtLeast(0f).toInt()
        val y = (faceBox.y - faceBox.h * pad).coerceAtLeast(0f).toInt()
        val w = (faceBox.w * (1 + 2 * pad)).toInt().coerceAtMost(bmp.width - x)
        val h = (faceBox.h * (1 + 2 * pad)).toInt().coerceAtMost(bmp.height - y)
        val avatar = Bitmap.createBitmap(bmp, x, y, w, h)
        val avatarDir = java.io.File(requireContext().filesDir, "face_avatars")
        avatarDir.mkdirs()
        val avatarFile = java.io.File(avatarDir, "$name.jpg")
        avatarFile.outputStream().use { avatar.compress(android.graphics.Bitmap.CompressFormat.JPEG, 90, it) }
        Log.i(TAG, "头像已存: ${avatarFile.absolutePath} (${w}x${h})")

        withContext(Dispatchers.Main) {
            tvStatus.text = "✅ 注册成功: $name (头像已存)\n点「OMS实时识别」正对镜头即可认出"
        }
    }
}
```

- [ ] **Step 3: 编译验证**

Run: `cd agent_front_app && ./gradlew :app:compileDebugKotlin --no-daemon`
Expected: BUILD SUCCESSFUL

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/FaceRecognizer.kt app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt
git commit -m "feat(face): crop avatar on enroll + save face_avatars/{userid}.jpg"
```

---

### Task 2: GreetingTrigger 构建 A2UI 卡片 JSON

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/face/GreetingTrigger.kt`

**Interfaces:**
- Consumes: userid, gateway reply text, avatar file path
- Produces: A2UI card JSON string (Image + Text container)

- [ ] **Step 1: GreetingTrigger.greet 构建卡片 JSON 并调 speakGreeting**

```kotlin
fun greet(userid: String) {
    Thread {
        try {
            val reply = gatewayGreet(userid) ?: return@Thread
            Log.i(TAG, "greet($userid) reply: $reply")

            // 构建头像路径
            val avatarPath = "/data/user/10/com.openclaw.car/files/face_avatars/$userid.jpg"
            val avatarFile = java.io.File(avatarPath)
            val avatarSrc = if (avatarFile.exists()) "file://$avatarPath" else null

            // 构建 A2UI 卡片 JSON
            val cardJson = buildGreetingCardJson(reply, avatarSrc)

            // 调 FloatingBubbleService 显示卡片 + TTS
            val svc = com.openclaw.car.service.FloatingBubbleService.instance
            if (svc != null) svc.speakGreeting(reply, cardJson)
            else Log.w(TAG, "FloatingBubbleService not running")
        } catch (e: Exception) {
            Log.e(TAG, "greet failed: ${e.message}")
        }
    }.start()
}

/** 构建欢迎卡片 A2UI JSON: 头像(圆形) + 问候语 */
private fun buildGreetingCardJson(reply: String, avatarSrc: String?): String {
    val children = org.json.JSONArray()
    // 头像 Image（如果存在）
    if (avatarSrc != null) {
        children.put(org.json.JSONObject().apply {
            put("type", "Image")
            put("styles", org.json.JSONObject().apply {
                put("src", avatarSrc)
                put("width", 72)
                put("height", 72)
                put("borderRadius", 36)
            })
        })
    }
    // 问候语 Text
    children.put(org.json.JSONObject().apply {
        put("type", "Text")
        put("content", reply)
        put("styles", org.json.JSONObject().apply {
            put("fontSize", 16)
            put("color", "#333333")
        })
    })
    // Container
    val card = org.json.JSONObject().apply {
        put("type", "Container")
        put("direction", "ROW")
        put("styles", org.json.JSONObject().apply {
            put("padding", 16)
            put("backgroundColor", "#FFFFFF")
            put("borderRadius", 12)
        })
        put("children", children)
    }
    return card.toString()
}
```

- [ ] **Step 2: 编译验证**

Run: `./gradlew :app:compileDebugKotlin --no-daemon`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/GreetingTrigger.kt
git commit -m "feat(face): GreetingTrigger builds A2UI card JSON (avatar+greeting)"
```

---

### Task 3: FloatingBubbleService.speakGreeting 显示卡片 + TTS

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt` (speakGreeting)

**Interfaces:**
- Consumes: text (TTS), cardJson (A2UI 卡片, nullable)
- Produces: InteractiveCardActivity 显示卡片 + streamingTtsPlayer 播报

- [ ] **Step 1: speakGreeting 加 cardJson 参数 + 显示卡片**

```kotlin
// 旧签名: fun speakGreeting(text: String)
// 新签名:
fun speakGreeting(text: String, cardJson: String? = null) {
    Log.i(TAG, "speakGreeting: ${text.take(80)} card=${cardJson != null}")

    // 如果有卡片 JSON, 显示 A2UI 卡片
    if (cardJson != null) {
        com.openclaw.car.agenui.LatestCardJson.json = cardJson
        val intent = android.content.Intent(this, com.openclaw.car.agenui.InteractiveCardActivity::class.java)
        intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
    }

    // TTS 播报（不变）
    currentTurn = ConversationTurn(userInput = "(用户上车)", aiResponse = text)
    handler.post { updateExpandedContent() }
    stopTtsAndFiller()
    streamingTtsPlayer.playStream(text, "default",
        onFirstChunk = { responseWatchdog.cancel() },
        onDone = { ok -> Log.i(TAG, "greeting TTS done ok=$ok") })
}
```

- [ ] **Step 2: 确认 InteractiveCardActivity 存在 + 能读 LatestCardJson**

```bash
grep -n "LatestCardJson" app/src/main/java/com/openclaw/car/agenui/InteractiveCardActivity.kt 2>/dev/null || \
grep -rn "InteractiveCardActivity" app/src/main/java --include="*.kt" | head -3
```

如果 InteractiveCardActivity 不存在或不能读 LatestCardJson，用 AGenUISurfaceActivity 替代（已有）。

- [ ] **Step 3: 编译 + 装车验证**

Run: `./gradlew assembleDebug && adb install -r app-debug.apk`
验证: 注册用户(存头像) → FaceIdService 检测到 → GreetingTrigger → 卡片显示(头像+问候) + TTS 播报

- [ ] **Step 4: Commit**

```bash
git add app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt
git commit -m "feat(face): speakGreeting shows A2UI card (avatar+greeting) + TTS"
```

---

## Self-Review

**Spec coverage:**
- 注册时 crop 人脸存头像 → Task 1 ✅
- GreetingTrigger 构建卡片 JSON → Task 2 ✅
- speakGreeting 显示卡片 + TTS → Task 3 ✅

**Placeholder:** 无 TBD，每步有完整代码。

**类型一致:** `enrollWithName(name, bitmap): FaceBox?` / `speakGreeting(text, cardJson?)` / `buildGreetingCardJson(reply, avatarSrc): String` — 跨 task 一致。

**风险:**
1. InteractiveCardActivity 可能不存在或不读 LatestCardJson → Task 3 Step 2 验证, 备选 AGenUISurfaceActivity
2. A2UI Image 组件 `borderRadius` 不一定支持圆形 → 记忆 [[a2ui-image-size-bug]] 有 patchUnknownIcons 等 patch, 可能需要加 Image size patch
3. PicassoImageLoader 的 `file://` 加载需要文件权限（filesDir app 可读, 应该 OK）
