# 「ID 管理」Tab 改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「视频流」tab 改名为「ID 管理」，进入即显示实时视频 + 人脸框 + 状态化圆形头像预览，注册改用当前实时帧，并新增删除已注册用户的功能。

**Architecture:** 复用 `LiveVideoFaceFragment` 的 SurfaceView+Canvas 单一绘制路径，新增 `drawLivePreview` 在每帧右上角画状态化圆形预览；删除功能用新建的 `FaceManageBottomSheet`（BottomSheetDialogFragment + RecyclerView）；纯逻辑（`SessionKey.hashUserId`、`FaceGallery.remove`）用 JUnit JVM 单测锁死，UI 层靠编译 + 车机装机实测。

**Tech Stack:** Kotlin, Android Material3, OkHttp, Gson, Canvas/SurfaceView, BottomSheetDialogFragment, JUnit 4.13.2（JVM 单测）。

## Global Constraints

- 代码在 submodule `agent_front_app/`（当前分支 `research/tts-deployment`），所有相对路径以此为单位。
- 纯 JVM 单测目录 `app/src/test/java/com/openclaw/car/face/`，测试命令 `./gradlew :app:testDebugUnitTest --tests "<全限定类名>"`（在 `agent_front_app/` 下执行）。
- 项目**无 androidTest 仪器测试基建**——UI/Fragment/Canvas 层验证靠 `./gradlew :app:assembleDebug` 编译 + 车机装机实测。
- `SessionKey.setToUser` 的 hash 实现是**最新正确行为**（为支持中文/emoji 用户名，如「小竹🎋」），不得改回直接拼名字；过时的是旧测试。
- `.openclaw/workspace/` 下文件 owner 必须是 `u10_a150:u10_a150`（gateway 以该用户运行），任何重建 `MEMORY.md` 的 shell 命令必须 `chown u10_a150:u10_a150`。
- 用户名可含中文/emoji，所有按用户名读文件的路径用原样名字（如 `face_avatars/{name}.jpg`）；session key 判断才用 hash。

---

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `app/src/main/java/com/openclaw/car/face/SessionKey.kt` | 全局 session key；提供 `hashUserId(name)` | 修改（Task 1） |
| `app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt` | SessionKey JVM 单测 | 修改（Task 1，修过时测试 + 加新） |
| `app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt` | FaceGallery JVM 单测 | 修改（Task 2，加 remove 覆盖） |
| `app/src/main/java/com/openclaw/car/MainActivity.kt` | tab 标题 | 修改（Task 3，改名） |
| `app/src/main/res/layout/fragment_live_video_face.xml` | 视频 tab 布局 | 修改（Task 3，删识别按钮 + 文案） |
| `app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt` | 主 Fragment | 修改（Task 4、5） |
| `app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt` | 记忆软链切换 | 修改（Task 6，加 `resetToDefault`） |
| `app/src/main/java/com/openclaw/car/fragment/FaceManageBottomSheet.kt` | 删除用户 BottomSheet | 新建（Task 6） |
| `app/src/main/res/layout/dialog_face_manage.xml` | BottomSheet 布局 | 新建（Task 6） |
| `app/src/main/res/layout/item_face_user.xml` | 列表项布局 | 新建（Task 6） |

---

### Task 1: `SessionKey.hashUserId` + 修复过时测试

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/face/SessionKey.kt`
- Test: `app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt`

**Interfaces:**
- Produces: `SessionKey.hashUserId(userid: String): String` —— 返回与 `setToUser(userid)` 写入 `current` 时相同的 hex 后缀（`agent:main:face-` 之后那段）。Task 6 的删除流程用它判断被删用户是否是当前 session 用户。

- [ ] **Step 1: 写失败测试（先加 `hashUserId` 行为 + 修两个过时用例）**

把 `SessionKeyTest.kt` 整体替换为：

```kotlin
package com.openclaw.car.face
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionKeyTest {
    @Test fun default_is_ppt_voice() {
        SessionKey.resetToDefault()
        assertEquals("agent:main:ppt-voice", SessionKey.current)
    }

    // 过时用例已修：setToUser 现在用 hash（中文/emoji 用户名不能直接进 HTTP header）
    @Test fun setToUser_formats_face_key_hashed() {
        SessionKey.setToUser("zhangsan")
        assertEquals("agent:main:face-${SessionKey.hashUserId("zhangsan")}", SessionKey.current)
    }
    @Test fun listener_fires_on_change_hashed() {
        var heard = ""
        SessionKey.listener = { heard = it }
        SessionKey.setToUser("lisi")
        assertEquals("agent:main:face-${SessionKey.hashUserId("lisi")}", heard)
        SessionKey.listener = null
    }

    @Test fun hashUserId_is_ascii_safe_and_stable() {
        val h1 = SessionKey.hashUserId("小竹🎋")
        val h2 = SessionKey.hashUserId("小竹🎋")
        assertEquals(h1, h2)                          // 稳定
        assertTrue("hash must be hex", h1.all { it.isLetterOrDigit() })
        assertTrue("hash <= 6 hex digits", h1.length <= 6)
    }

    @Test fun hashUserId_matches_setToUser_suffix() {
        SessionKey.setToUser("聪明的熊猫")
        val suffix = SessionKey.current.removePrefix("agent:main:face-")
        assertEquals(SessionKey.hashUserId("聪明的熊猫"), suffix)
    }
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SessionKeyTest" 2>&1 | tail -15`
Expected: FAIL —— `hashUserId` 未解析（还不存在）。

- [ ] **Step 3: 实现 `hashUserId` 并让 `setToUser` 复用它（DRY）**

把 `SessionKey.kt` 的 `setToUser` 替换为如下（新增 `hashUserId` 公开方法，`setToUser` 调用它）：

```kotlin
package com.openclaw.car.face

/** 全局当前 openclaw session key。faceid 切换用户时改，ppt-voice 读它保持同 session。 */
object SessionKey {
    private const val DEFAULT = "agent:main:ppt-voice"
    @Volatile private var key: String = DEFAULT
    @Volatile var listener: ((String) -> Unit)? = null

    val current: String get() = key

    /** 把任意 userid（可含中文/emoji）映射成 ASCII hex 后缀，用于 session key 与 HTTP header 安全。 */
    fun hashUserId(userid: String): String =
        userid.toByteArray().fold(0) { acc, b -> (acc * 31 + b) and 0xFFFFFF }.toString(16)

    fun setToUser(userid: String) {
        // session key 只用 ASCII（中文/emoji 在 HTTP header 里会被截断/损坏）
        key = "agent:main:face-${hashUserId(userid)}"
        listener?.invoke(key)
    }

    fun resetToDefault() {
        key = DEFAULT
        listener?.invoke(key)
    }
}
```

- [ ] **Step 4: 跑测试验证通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SessionKeyTest" 2>&1 | tail -15`
Expected: 5 tests passed, 0 failed。

- [ ] **Step 5: Commit**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add app/src/main/java/com/openclaw/car/face/SessionKey.kt app/src/test/java/com/openclaw/car/face/SessionKeyTest.kt
git -C /home/tsm/work/android_agent/agent_front_app commit -m "refactor(face): 抽出 SessionKey.hashUserId + 修过时测试"
```

---

### Task 2: `FaceGallery.remove` 测试覆盖

> 锁死现有 `remove` 行为（实现已存在，`FaceGallery.kt:38`），为 Task 6 删除流程提供回归保护。

**Files:**
- Test: `app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt`

**Interfaces:**
- Consumes: `FaceGallery.enroll/save/load/names/remove/bestMatch`（均已存在）。

- [ ] **Step 1: 在 `FaceGalleryTest.kt` 末尾（最后一个 `}` 之前）追加三个测试**

```kotlin
    @Test
    fun remove_drops_name_from_gallery() {
        val f = File(tmp.root, "g.json")
        val g = FaceGallery(f)
        g.enroll("alice", floatArrayOf(1f, 0f, 0f))
        g.enroll("bob", floatArrayOf(0f, 1f, 0f))
        g.remove("alice")
        assertEquals(setOf("bob"), g.names())
    }

    @Test
    fun remove_persists_after_save_and_reload() {
        val f = File(tmp.root, "g.json")
        val g = FaceGallery(f)
        g.enroll("alice", floatArrayOf(1f, 0f, 0f))
        g.enroll("bob", floatArrayOf(0f, 1f, 0f))
        g.remove("alice")
        g.save()

        val g2 = FaceGallery(f)
        g2.load()
        assertEquals(setOf("bob"), g2.names())
    }

    @Test
    fun bestMatch_does_not_return_removed_user() {
        val f = File(tmp.root, "g.json")
        val g = FaceGallery(f)
        g.enroll("alice", FaceMath.l2normalize(floatArrayOf(1f, 0f, 0f)))
        g.remove("alice")
        assertNull(g.bestMatch(FaceMath.l2normalize(floatArrayOf(1f, 0f, 0f)), 0.5f))
    }
```

- [ ] **Step 2: 跑测试验证通过（实现已存在，应直接绿）**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.FaceGalleryTest" 2>&1 | tail -15`
Expected: 6 tests passed（原 3 + 新 3）, 0 failed。

- [ ] **Step 3: Commit**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt
git -C /home/tsm/work/android_agent/agent_front_app commit -m "test(face): 补 FaceGallery.remove 回归测试"
```

---

### Task 3: 改名 + 布局精简

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/MainActivity.kt:65`
- Modify: `app/src/main/res/layout/fragment_live_video_face.xml`

**Interfaces:** 无（纯 UI 文案/结构）。

- [ ] **Step 1: tab 改名**

把 `MainActivity.kt:65` 的 `5 -> "视频流"` 改为：

```kotlin
                5 -> "ID管理"
```

- [ ] **Step 2: 改 `tv_status` 默认文案**

把 `fragment_live_video_face.xml` 里 `tv_status` 的 `android:text`（约第 29 行）改为：

```xml
            android:text="🎥 实时预览 / 📸 注册 / 🗑 管理"
```

- [ ] **Step 3: 删除「🎥 识别」按钮块**

删除 `fragment_live_video_face.xml` 中整个 `btn_select_stream` 块（id 为 `@+id/btn_select_stream` 的 `MaterialButton`，约第 74-86 行）。删后底部按钮行只剩 `btn_enroll` + `btn_manage`，二者 `layout_weight=1` 自动均分。同时把 `btn_enroll` 上的 `android:layout_marginEnd="6dp"` 保留即可（与 manage 间距）。

- [ ] **Step 4: 编译验证**

Run: `./gradlew :app:assembleDebug 2>&1 | tail -15`
Expected: BUILD SUCCESSFUL。`LiveVideoFaceFragment` 此时仍 `findViewById(btn_select_stream)` 会在运行时返回 null —— 但因为下一步 Task 4 会同步删该引用，**此处先不运行 app**，编译通过即可（编译期 `findViewById` 不校验 id 存在）。

- [ ] **Step 5: Commit**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add app/src/main/java/com/openclaw/car/MainActivity.kt app/src/main/res/layout/fragment_live_video_face.xml
git -C /home/tsm/work/android_agent/agent_front_app commit -m "feat(face): tab改名ID管理 + 删识别按钮 + 文案"
```

---

### Task 4: Fragment 进入即开流 + 注册用当前帧 + 接线管理按钮

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt`

**Interfaces:**
- Produces: 进入即开流；`enrollVoice` 改用 `latestBitmap`。`btn_manage` 故意**不在本 Task 接线**（原 `onViewCreated` 也没碰它），留给 Task 6 —— 避免本 Task 依赖尚未创建的 `FaceManageBottomSheet` 类。本 Task 期间它是死按钮，无害。

- [ ] **Step 1: `onViewCreated` —— 删识别按钮、自动开流**

把 `LiveVideoFaceFragment.kt` 的 `onViewCreated`（约 69-81 行）整体替换为：

```kotlin
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        surfaceView = view.findViewById(R.id.surface_view)
        tvStatus = view.findViewById(R.id.tv_status)
        tvDetection = view.findViewById(R.id.tv_detection)
        etName = view.findViewById(R.id.et_name)

        view.findViewById<MaterialButton>(R.id.btn_enroll).setOnClickListener { enrollVoice() }
        // btn_manage 的 listener 在 Task 6 接入（FaceManageBottomSheet）
        // 进入即开流预览
        startOMSStream()
    }
```

- [ ] **Step 2: 删除 `updateStreamBtn` 及 `btn_select_stream` 相关**

删除 `LiveVideoFaceFragment.kt` 中：
- `updateStreamBtn(on: Boolean)` 整个方法（约 301-305 行）。
- `startOMSStream` 里第一行 `updateStreamBtn(true)`（约 280 行）。
- `stopOMSStream` 里 `updateStreamBtn(false)`（约 297 行）—— `stopOMSStream` 改为：

```kotlin
    private fun stopOMSStream() {
        streamOn = false; omsJob?.cancel(); omsJob = null
        tvStatus.text = "已停止"
    }
```

- [ ] **Step 3: `enrollVoice` 抓帧改用 `latestBitmap`**

把 `enrollVoice` 里的抓帧行（约 99 行）：

```kotlin
            val bmp = pullFrame()
```

改为：

```kotlin
            val bmp = latestBitmap ?: pullFrame()
```

（`latestBitmap` 由 `showAndRecognize` 每帧缓存；为空则回退临时拉帧。）

- [ ] **Step 4: 编译验证**

Run: `./gradlew :app:assembleDebug 2>&1 | tail -15`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 5: Commit**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt
git -C /home/tsm/work/android_agent/agent_front_app commit -m "feat(face): 进入即开流预览 + 注册用当前帧"
```

---

### Task 5: `drawLivePreview` 状态化圆形预览 + 注册确认边框加粗

**Files:**
- Modify: `app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt`

**Interfaces:**
- Consumes: `RecognizeResult(status, id?, box?)`（`com.openclaw.car.face.RecognizeResult`）、`Status`、`FaceBox`。

- [ ] **Step 1: `showAndRecognize` 两个分支都在 `drawFrame` 后调 `drawLivePreview`**

在 `showAndRecognize`（约 318-340 行）：
- 暗画面分支（约 321 行）：

```kotlin
        if (br < DARK_THR) {
            drawFrame(bmp, emptyList())
            drawLivePreview(bmp, com.openclaw.car.face.RecognizeResult(com.openclaw.car.face.Status.NO_FACE))
            view?.post { tvDetection.text = "画面过暗(亮度$br)" }; return
        }
```

- 正常分支末尾（约 330 行 `drawFrame(bmp, faces)` 之后）追加一行：

```kotlin
        drawFrame(bmp, faces)
        drawLivePreview(bmp, r)
```

- [ ] **Step 2: 新增 `drawLivePreview` 方法**

在 `drawFrame` 方法之后（`brightness` 方法之前）新增：

```kotlin
    /** 实时圆形头像预览（右上角）：1 张正脸=绿框+裁剪头像+名字；否则=橙虚线框+占位。 */
    private fun drawLivePreview(bmp: Bitmap, result: com.openclaw.car.face.RecognizeResult) {
        val holder = surfaceView.holder
        if (!holder.surface.isValid) return
        val canvas = holder.surface.lockCanvas(null) ?: return

        val avatarSize = minOf(240f, canvas.width * 0.25f)
        val cx = canvas.width - avatarSize / 2 - 40f
        val cy = avatarSize / 2 + 40f
        val radius = avatarSize / 2
        val circleRect = RectF(cx - radius, cy - radius, cx + radius, cy + radius)

        // 半透明深色衬底，提升边框在亮/暗画面上的可见度
        val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(80, 0, 0, 0) }
        canvas.drawCircle(cx, cy, radius + 8f, bgPaint)

        val box = result.box
        if (box != null) {
            // 绿色粗实线边框
            val border = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.parseColor("#4CAF50"); style = Paint.Style.STROKE; strokeWidth = 6f
            }
            canvas.drawCircle(cx, cy, radius, border)
            // 圆形裁剪画人脸 crop（box 扩 20%）
            val pad = 0.2f
            val x = (box.x - box.w * pad).coerceAtLeast(0f).toInt()
            val y = (box.y - box.h * pad).coerceAtLeast(0f).toInt()
            val w = (box.w * (1 + 2 * pad)).toInt().coerceAtMost(bmp.width - x)
            val h = (box.h * (1 + 2 * pad)).toInt().coerceAtMost(bmp.height - y)
            val avatar = runCatching { Bitmap.createBitmap(bmp, x, y, w, h) }.getOrNull()
            if (avatar != null) {
                canvas.save()
                android.graphics.Path().apply { addCircle(cx, cy, radius - 3f, android.graphics.Path.Direction.CW) }
                    .let { canvas.clipPath(it) }
                canvas.drawBitmap(avatar, null, circleRect, Paint(Paint.FILTER_BITMAP_FLAG))
                canvas.restore()
            }
            val name = if (result.status == com.openclaw.car.face.Status.RECOGNIZED) (result.id ?: "?") else "新面孔"
            val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.WHITE; textSize = 28f; textAlign = Paint.Align.CENTER
            }
            canvas.drawText(name, cx, cy + radius + 32f, text)
        } else {
            // 橙色虚线边框 + 占位
            val border = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.parseColor("#FF9800"); style = Paint.Style.STROKE; strokeWidth = 6f
                pathEffect = android.graphics.DashPathEffect(floatArrayOf(18f, 12f), 0f)
            }
            canvas.drawCircle(cx, cy, radius, border)
            val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(50, 255, 255, 255) }
            canvas.drawCircle(cx, cy, radius - 3f, fill)
            val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.parseColor("#FF9800"); textSize = 24f; textAlign = Paint.Align.CENTER
            }
            canvas.drawText("请正对镜头", cx, cy + 8f, text)
        }
        holder.surface.unlockCanvasAndPost(canvas)
    }
```

- [ ] **Step 3: 改 `drawEnrollPreview` 的圆形头像边框（淡填充 → 蓝色粗描边 + 衬底）**

把 `drawEnrollPreview` 中这段（约 264-270 行）：

```kotlin
        // 圆形头像
        val circlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(40, 88, 166, 255) }
        canvas.drawCircle(avatarCx, avatarCy, avatarSize / 2 + 6f, circlePaint)
        canvas.save()
```

替换为：

```kotlin
        // 半透明深色衬底
        val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(80, 0, 0, 0) }
        canvas.drawCircle(avatarCx, avatarCy, avatarSize / 2 + 10f, bgPaint)
        // 蓝色粗描边（注册确认）
        val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#58A6FF"); style = Paint.Style.STROKE; strokeWidth = 8f
        }
        canvas.drawCircle(avatarCx, avatarCy, avatarSize / 2, borderPaint)
        canvas.save()
```

（其后的 `clipPath` → `drawBitmap` → `restore` 段不变。）

- [ ] **Step 4: 编译验证**

Run: `./gradlew :app:assembleDebug 2>&1 | tail -15`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 5: Commit**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt
git -C /home/tsm/work/android_agent/agent_front_app commit -m "feat(face): 实时状态化圆形预览 + 注册确认蓝边框"
```

---

### Task 6: `FaceManageBottomSheet` 删除用户功能

**Files:**
- Create: `app/src/main/java/com/openclaw/car/fragment/FaceManageBottomSheet.kt`
- Create: `app/src/main/res/layout/dialog_face_manage.xml`
- Create: `app/src/main/res/layout/item_face_user.xml`
- Modify: `app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt`
- Modify: `app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt`（接线 `btn_manage`）

**Interfaces:**
- Consumes: `SessionKey.hashUserId/current/resetToDefault`（Task 1）、`FaceGallery(names/remove/load/save)`、`MemorySwitcher.resetToDefault`（本 Task 新增）。

- [ ] **Step 1: 确认 RecyclerView 依赖**

Run: `grep -n "recyclerview" app/build.gradle.kts`
Expected: 命中 `androidx.recyclerview:recyclerview:...`。若无，在 `dependencies` 块加 `implementation("androidx.recyclerview:recyclerview:1.3.2")`。

- [ ] **Step 2: `MemorySwitcher` 加 `resetToDefault`**

在 `MemorySwitcher.kt` 的 `switchTo` 方法之后追加：

```kotlin
    /** 删除当前用户后重置 MEMORY.md：删软链 → 建空文件 → chown u10_a150（gateway 要求）。 */
    fun resetToDefault(): Boolean {
        val cmd = "rm -f $WS/MEMORY.md && printf '' > $WS/MEMORY.md && chown u10_a150:u10_a150 $WS/MEMORY.md && chmod 644 $WS/MEMORY.md"
        return try {
            val proc = Runtime.getRuntime().exec(arrayOf("sh", "-c", cmd))
            val code = proc.waitFor()
            Log.i(TAG, "resetToDefault exit=$code")
            code == 0
        } catch (e: Exception) {
            Log.e(TAG, "resetToDefault failed: ${e.message}"); false
        }
    }
```

- [ ] **Step 3: 新建列表项布局 `item_face_user.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="64dp"
    android:orientation="horizontal"
    android:gravity="center_vertical"
    android:paddingHorizontal="16dp"
    android:background="#0D1117">
    <ImageView
        android:id="@+id/iv_avatar"
        android:layout_width="44dp"
        android:layout_height="44dp"
        android:scaleType="centerCrop"
        android:contentDescription="头像" />
    <TextView
        android:id="@+id/tv_name"
        android:layout_width="0dp"
        android:layout_height="wrap_content"
        android:layout_weight="1"
        android:layout_marginStart="12dp"
        android:textColor="#FFFFFF"
        android:textSize="16sp" />
    <ImageButton
        android:id="@+id/btn_delete"
        android:layout_width="40dp"
        android:layout_height="40dp"
        android:background="?attr/selectableItemBackgroundBorderless"
        android:src="@android:drawable/ic_menu_delete"
        android:contentDescription="删除" />
</LinearLayout>
```

- [ ] **Step 4: 新建 BottomSheet 布局 `dialog_face_manage.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:orientation="vertical"
    android:background="#161B22"
    android:padding="16dp">
    <TextView
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="已注册用户"
        android:textColor="#FFFFFF"
        android:textSize="18sp"
        android:textStyle="bold"
        android:layout_marginBottom="8dp" />
    <TextView
        android:id="@+id/tv_empty"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="暂无已注册用户"
        android:textColor="#8B949E"
        android:textSize="14sp"
        android:gravity="center"
        android:padding="24dp"
        android:visibility="gone" />
    <androidx.recyclerview.widget.RecyclerView
        android:id="@+id/rv_users"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:maxHeight="360dp" />
    <com.google.android.material.button.MaterialButton
        android:id="@+id/btn_close"
        android:layout_width="match_parent"
        android:layout_height="48dp"
        android:layout_marginTop="8dp"
        android:text="关闭"
        android:textColor="#FFFFFF"
        app:cornerRadius="12dp"
        app:backgroundTint="#238636" />
</LinearLayout>
```

- [ ] **Step 5: 新建 `FaceManageBottomSheet.kt`**

```kotlin
package com.openclaw.car.fragment

import android.app.AlertDialog
import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomsheet.BottomSheetDialogFragment
import com.openclaw.car.R
import com.openclaw.car.face.FaceGallery
import com.openclaw.car.face.MemorySwitcher
import com.openclaw.car.face.SessionKey
import java.io.File

class FaceManageBottomSheet : BottomSheetDialogFragment() {

    private lateinit var rv: RecyclerView
    private lateinit var emptyHint: TextView
    private val names = mutableListOf<String>()
    private lateinit var adapter: NamesAdapter

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, s: Bundle?): View {
        val view = inflater.inflate(R.layout.dialog_face_manage, container, false)
        rv = view.findViewById(R.id.rv_users)
        emptyHint = view.findViewById(R.id.tv_empty)
        rv.layoutManager = LinearLayoutManager(requireContext())
        adapter = NamesAdapter(names, ::onDelete)
        rv.adapter = adapter
        view.findViewById<View>(R.id.btn_close).setOnClickListener { dismiss() }
        reload()
        return view
    }

    private fun gallery(): FaceGallery {
        val f = File(requireContext().filesDir, "face_gallery.json")
        val g = FaceGallery(f); g.load(); return g
    }

    private fun reload() {
        val g = gallery()
        names.clear(); names.addAll(g.names()); adapter.notifyDataSetChanged()
        val empty = names.isEmpty()
        emptyHint.visibility = if (empty) View.VISIBLE else View.GONE
        rv.visibility = if (empty) View.GONE else View.VISIBLE
    }

    private fun onDelete(name: String) {
        val ctx = context ?: return
        AlertDialog.Builder(ctx)
            .setTitle("确认删除")
            .setMessage("确认删除 $name ？")
            .setNegativeButton("取消", null)
            .setPositiveButton("删除") { _, _ ->
                val g = gallery()
                g.remove(name); g.save()
                File(ctx.filesDir, "face_avatars/$name.jpg").delete()
                // 删的是当前 session 用户 → 重置 session + 记忆
                val current = SessionKey.current
                if (current.startsWith("agent:main:face-") &&
                    current.removePrefix("agent:main:face-") == SessionKey.hashUserId(name)
                ) {
                    SessionKey.resetToDefault()
                    MemorySwitcher.resetToDefault()
                }
                reload()
            }.show()
    }

    private inner class NamesAdapter(
        private val items: List<String>,
        private val onDelete: (String) -> Unit
    ) : RecyclerView.Adapter<NamesAdapter.VH>() {
        inner class VH(v: View) : RecyclerView.ViewHolder(v) {
            val avatar: ImageView = v.findViewById(R.id.iv_avatar)
            val name: TextView = v.findViewById(R.id.tv_name)
            val del: View = v.findViewById(R.id.btn_delete)
        }
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_face_user, parent, false))
        override fun getItemCount(): Int = items.size
        override fun onBindViewHolder(h: VH, position: Int) {
            val n = items[position]
            h.name.text = n
            val f = File(h.itemView.context.filesDir, "face_avatars/$n.jpg")
            if (f.exists()) h.avatar.setImageBitmap(BitmapFactory.decodeFile(f.absolutePath))
            else h.avatar.setImageResource(android.R.drawable.ic_menu_myplaces)
            h.del.setOnClickListener { onDelete(n) }
        }
    }
}
```

- [ ] **Step 6: 给 `LiveVideoFaceFragment` 的管理按钮接线**

在 `onViewCreated` 里 `btn_enroll` 的 listener 之后、`startOMSStream()` 之前，新增：

```kotlin
        view.findViewById<MaterialButton>(R.id.btn_manage).setOnClickListener {
            FaceManageBottomSheet().show(parentFragmentManager, "faceManage")
        }
```

- [ ] **Step 7: 编译验证**

Run: `./gradlew :app:assembleDebug 2>&1 | tail -15`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 8: Commit**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add app/src/main/java/com/openclaw/car/fragment/FaceManageBottomSheet.kt app/src/main/res/layout/dialog_face_manage.xml app/src/main/res/layout/item_face_user.xml app/src/main/java/com/openclaw/car/face/MemorySwitcher.kt app/src/main/java/com/openclaw/car/fragment/LiveVideoFaceFragment.kt
git -C /home/tsm/work/android_agent/agent_front_app commit -m "feat(face): 新增删除注册用户(底部列表+二次确认+session重置)"
```

---

### Task 7: 车机装机端到端验证

> 项目无 UI 仪器测试，验收靠装机实测。设备 `LZBYDUMNB6RW7X5P`（Android IVI 侧）。

**Files:** 无（验证 only）。

- [ ] **Step 1: 跑全部 JVM 单测**

Run: `./gradlew :app:testDebugUnitTest 2>&1 | tail -20`
Expected: 全部通过（SessionKey 5 + FaceGallery 6 + 其他既有）。

- [ ] **Step 2: 部署到车机**

Run:
```bash
./gradlew :app:installDebug
adb -s LZBYDUMNB6RW7X5P shell am start -n com.openclaw.car/.MainActivity
```
Expected: 安装成功，app 启动。

- [ ] **Step 3: 手动验证清单**

切到第 5 个 tab，逐项确认：

- [ ] tab 标题显示「ID 管理」。
- [ ] 进入即自动看到实时视频画面（无需点任何按钮）。
- [ ] 无人正对时：右上角圆形预览为**橙色虚线框** + 「请正对镜头」。
- [ ] 一人正对时：右上角为**绿色粗实线框** + 实时人脸裁剪 + 名字（已注册显示名字，未注册显示「新面孔」）；视频画面叠加绿色人脸框。
- [ ] 画面叠加的人脸框仍正常（绿色矩形 + 红色 landmarks）。
- [ ] 点「📸 注册」→ 用当前帧注册成功 → 大图预览（**蓝色粗边框**）3 秒 → 状态栏「✅ 注册成功: XXX」→ 问候触发。
- [ ] 点「🗑 管理」→ 底部弹出列表，列出已注册用户（含头像 + 名字）。
- [ ] 点某用户🗑 → 弹「确认删除 XXX？」→ 取消可撤销 → 确认后该用户从列表消失。
- [ ] 删除后再点注册/识别：已删用户不再被识别（用同名嵌入重测应判 UNKNOWN）。
- [ ] 删除当前登录用户后：session 应回默认（gateway 下次对话用 `agent:main:ppt-voice`），`MEMORY.md` 为空文件 owner `u10_a150`（`adb -s LZBYDUMNB6RW7X5P shell ls -l /data/local/tmp/openclaw-home/.openclaw/workspace/MEMORY.md`）。

- [ ] **Step 4: 收尾 commit（如有验证中暴露的小修）**

```bash
git -C /home/tsm/work/android_agent/agent_front_app add -A
git -C /home/tsm/work/android_agent/agent_front_app commit -m "fix(face): 装机验证小修"
```
（无修改则跳过。）
