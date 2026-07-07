# FaceID 头像存储 + 欢迎 A2UI 卡片设计

> 日期: 2026-07-01
> 目标: 注册时存人脸头像图片; 欢迎 GreetingTrigger 改用 A2UI 卡片(头像+问候语) + TTS 播报

## 一、背景

**当前**：FaceGallery 只存 512-d embedding（JSON），不存图片。GreetingTrigger 走 FloatingBubbleService.speakGreeting（streamingTtsPlayer + 悬浮条文字），无头像显示。

**目标**：
1. 注册时 crop 人脸区域存为头像图片
2. faceid 识别到用户 → 问候 → **A2UI 卡片（头像 + 问候语）** + TTS 播报

## 二、设计

### 2.1 头像存储

**注册流程改动**（LiveVideoFaceFragment.enrollFromOMS）：
1. 抓 OMS 帧 → detect → pickCenter（最中央脸）
2. **新增**：根据 face box crop 人脸区域 → Bitmap → 存 `filesDir/face_avatars/{userid}.jpg`
3. embed → gallery.enroll（不变）

**FaceGallery 扩展**：
- 不改 JSON 格式（embedding 还是 Map<String, FloatArray>）
- 头像路径按约定：`filesDir/face_avatars/{userid}.jpg`（注册时存，识别时读）
- 新增 `avatarFile(userid): File` 工具方法

### 2.2 欢迎 A2UI 卡片

**GreetingTrigger 改动**：
1. gateway 生成问候文本（不变）
2. **新增**：构建 A2UI 卡片 JSON（app 本地模板）：
   ```json
   {"type":"Container","direction":"ROW","children":[
     {"type":"Image","styles":{"src":"file:///data/.../face_avatars/{userid}.jpg","width":72,"height":72,"borderRadius":36}},
     {"type":"Text","content":"欢迎回来！{reply}"}
   ]}
   ```
3. **FloatingBubbleService.speakGreeting 改**：
   - 构建 A2UI 卡片 JSON → 显示（InteractiveCardActivity 或 AGenUISurfaceActivity）
   - 同时 streamingTtsPlayer.playStream（TTS 播报）

### 2.3 卡片显示方式

复用现有 **InteractiveCardActivity**（透明 Activity 承载 A2UI，已验证 z-order 穿透）：
- speakGreeting 构建 JSON → LatestCardJson.json = json → startActivity(InteractiveCardActivity)
- InteractiveCardActivity 读 LatestCardJson 渲染
- 同时 TTS 播报

### 2.4 数据流

```
FaceIdService 检测到注册用户 X
  → switch session/记忆
  → GreetingTrigger.greet(X)
    → gateway 生成问候文本
    → 构建卡片 JSON (Image=file://avatar_X.jpg + Text=问候)
    → FloatingBubbleService.speakGreeting(text)
      → LatestCardJson.json = cardJson
      → startActivity(InteractiveCardActivity)  ← A2UI 卡片显示
      → streamingTtsPlayer.playStream(text)     ← TTS 播报
```

## 三、组件改动

| 组件 | 改动 |
|------|------|
| `LiveVideoFaceFragment.enrollFromOMS` | 注册时 crop 人脸 → 存 `face_avatars/{userid}.jpg` |
| `GreetingTrigger.greet` | 拿 reply 后构建卡片 JSON（Image + Text 模板） |
| `FloatingBubbleService.speakGreeting` | 构建 JSON → LatestCardJson + InteractiveCardActivity + TTS |
| `FaceGallery`（可选） | 加 avatarFile(userid) 工具方法 |

## 四、头像 crop 细节

从 detect 返回的 FaceBox（x, y, w, h）crop 原图：
```kotlin
// 扩大 box 20% 避免 太紧
val pad = 0.2f
val x = (face.x - face.w * pad).coerceAtLeast(0f).toInt()
val y = (face.y - face.h * pad).coerceAtLeast(0f).toInt()
val w = (face.w * (1 + 2 * pad)).toInt()
val h = (face.h * (1 + 2 * pad)).toInt()
val avatar = Bitmap.createBitmap(bmp, x, y, w.coerceAtMost(bmp.width - x), h.coerceAtMost(bmp.height - y))
// 存 JPEG
avatar.compress(JPEG, 90, FileOutputStream(avatarFile))
```

## 五、不在范围

- 头像编辑/更换（注册时存一张即可）
- 多张头像（只存最新）
- 卡片交互按钮（纯展示头像+问候）
- gateway 生成 A2UI JSON（用 app 本地模板）
