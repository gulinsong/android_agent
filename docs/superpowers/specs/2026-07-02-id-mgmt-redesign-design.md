# 视频流 tab →「ID 管理」改版设计

> 日期: 2026-07-02
> 目标: 视频 tab 改名「ID 管理」; 进入即实时预览(人脸框 + 状态化圆形头像); 注册基于当前帧; 新增删除注册用户

## 一、背景

**当前实现**（`LiveVideoFaceFragment.kt` / `fragment_live_video_face.xml`）：

- tab 名「视频流」硬编码在 `MainActivity.kt:69` (`5 -> "视频流"`)。
- 注册是**盲注册**：点「📸 注册」(`enrollVoice`) 临时 `pullFrame()` 抓一帧再 `enrollWithName`，**不依赖视频流**，用户看不到自己。
- 实时视频流靠「🎥 识别」按钮 (`btn_select_stream`) 手动开关 (`startOMSStream`)，开了才显示视频 + 人脸框 + 识别。
- 圆形头像预览只在**注册成功后** `drawEnrollPreview` 显示 3 秒；其「边框」是 `Color.argb(40, 88,166,255)` 的淡填充圆，**没有描边线**。
- 「🗑 管理」按钮 (`btn_manage`) 在 XML 里有，但**代码里未绑定任何点击事件**（死按钮）。
- `FaceGallery` 已有 `remove(name)` / `save()` / `names()`，但**无人调用** remove。
- 用户数据：`filesDir/face_gallery.json`（embedding）+ `filesDir/face_avatars/{name}.jpg`（头像）+ `/data/local/tmp/openclaw-home/.openclaw/workspace/memory_faceid_{name}.md`（per-user 记忆）。

**目标**：

1. tab 改名「ID 管理」。
2. 进入 tab 即自动开实时流，叠加人脸框 + 右上角**状态化圆形预览**。
3. 「注册」用当前实时帧 (`latestBitmap`)，保留自动命名 + 切 session + 问候。
4. 圆形预览边框**加粗、状态化**（绿 = 正脸 / 橙虚线 = 无脸或多脸 / 蓝 = 注册确认）。
5. 「管理」→ 底部 BottomSheet 列出注册用户，支持**删除单个用户**（二次确认）。

## 二、设计

### 2.1 关键选择：圆形预览绘制路径（采纳 A）

**方案 A（采纳）**：在 SurfaceView 的 Canvas 上画一切。延续现有 `drawFrame` / `drawEnrollPreview` 单一绘制路径——每帧 `drawFrame` 后调用新增的 `drawLivePreview`，在右上角画圆形预览，边框 `Paint` 按 `recognize` 结果状态化切换。

**不采纳方案 B**（原生 `ImageView` 叠加在 SurfaceView 上）：需要 FrameLayout 包裹 + 每帧跨线程推 bitmap 给上层控件，改动大、有线程同步成本；现有 canvas 画圆框 + clipPath 裁剪头像 (`drawEnrollPreview`) 已验证可行，状态化只是换不同 `Paint`。

### 2.2 改名

- `MainActivity.kt:69` `5 -> "视频流"` → `5 -> "ID管理"`（保持硬编码风格一致）。
- `fragment_live_video_face.xml` 中 `tv_status` 默认文案 `🎥 OMS 实时识别 / 📸 一键注册` → `🎥 实时预览 / 📸 注册 / 🗑 管理`。

### 2.3 实时预览交互（核心）

**布局改动** (`fragment_live_video_face.xml`)：

- 删除 `btn_select_stream`（🎥 识别按钮）。
- 底部按钮行只剩 `btn_enroll`（📸 注册）+ `btn_manage`（🗑 管理）两个，均分宽度。
- `et_name` 保持 `visibility="gone"`（保留 id 兼容，不删）。

**Fragment 改动** (`LiveVideoFaceFragment.kt`)：

- `onViewCreated`：直接 `startOMSStream()`（进入即开流）。删除 `btn_select_stream` 的 listener 与 `updateStreamBtn`。
- `showAndRecognize` 每帧：`drawFrame(bmp, faces)` 之后调用 `drawLivePreview(bmp, recognizeResult)`。
- `enrollVoice`：抓帧从 `pullFrame()` 改为 `latestBitmap`（`showAndRecognize` 已缓存的当前帧）。其余流程不变。`latestBitmap == null`（流未就绪）时回退 `pullFrame()` 或提示「视频未就绪」。
- `stopOMSStream` 保留（供 `onDestroyView` 用），仅去掉与按钮的联动。

**新增 `drawLivePreview(bmp, result)`**：

- 右上角圆形区域（沿用 `drawEnrollPreview` 的几何：`avatarSize = min(240f, canvas.width*0.25f)`）。
- `result.box != null` 且仅 1 张脸：
  - 绿色粗实线边框 `strokeWidth=6f` STROKE + 半透明深色衬底圆（`alpha≈80`）提升可见度。
  - `clipPath` 圆形裁剪 → 画 faceBox 扩 20% 的人脸 crop。
  - 名字：`result.status == RECOGNIZED` 显示 `result.id`，否则「新面孔」。
- 否则（0 张或 >1 张脸）：
  - 橙色虚线边框（`DashPathEffect`）`strokeWidth=6f`。
  - 灰色占位圆（淡填充）。
  - 文字「请正对镜头」。

### 2.4 圆形头像边框加粗（用户明确需求）

替换 `drawEnrollPreview` 中 `alpha=40` 的淡填充圆（实质无描边）为**显式描边**：

| 状态 | 颜色 | 样式 | strokeWidth |
|------|------|------|-------------|
| 正脸（实时预览） | 绿 `#4CAF50` | 实线 STROKE | 6f |
| 无脸/多脸（实时预览） | 橙 `#FF9800` | 虚线 (`DashPathEffect`) | 6f |
| 注册确认（`drawEnrollPreview` 大图） | 蓝 `#58A6FF` | 实线 STROKE | 8f |

每个圆都加一圈半透明深色衬底（先画一个 `alpha≈80` 的黑色填充圆作底），让边框在亮/暗画面上都清晰。

### 2.5 注册流程（微调）

`enrollVoice` 保留：

1. 自动生成「形容词 + 动物」名字（不改名）。
2. `enrollWithName(name, latestBitmap)`（抓帧源从 `pullFrame` 改 `latestBitmap`，回退 `pullFrame`）。
3. crop 头像存 `face_avatars/{name}.jpg`（不变）。
4. `drawEnrollPreview` 大图预览 3 秒（蓝色确认边框）。
5. `SessionKey.setToUser` + `MemorySwitcher.switchTo` + `GreetingTrigger.greetNewUser`（不变）。

> 方法名 `enrollVoice` 历史遗留（与 voice 无关），本次不改名，避免无关重命名。

### 2.6 删除功能（新增）

**新建 `FaceManageBottomSheet`（`BottomSheetDialogFragment`）**：

- 加载：`FaceGallery.load()` → `names()`，逐个配 `face_avatars/{name}.jpg` 头像（`BitmapFactory`，缺失则占位）。
- `RecyclerView` 列表，每行：[圆形头像 `ImageView`] [名字 `TextView`] [🗑 删除 `ImageButton`]。
- 空列表显示「暂无已注册用户」。
- 点 🗑 → `AlertDialog` 二次确认「确认删除 {name}？」→ 确认后：
  1. `FaceGallery.remove(name)` + `save()`。
  2. 删 `face_avatars/{name}.jpg`。
  3. **若删的是当前 session 用户** → `SessionKey.resetToDefault()` + 重置 `MEMORY.md`：`rm` 既有软链（`memory_faceid_{name}.md`）后建空文件并 `chown u10_a150:u10_a150`（与干净状态一致；复用 `MemorySwitcher` 的 exec 模式执行）。
  4. 刷新列表（或列表为空时显示空态后关闭）。
- `btn_manage` 接线：`FaceManageBottomSheet().show(parentFragmentManager, "faceManage")`。

**判断「当前 session 用户」**：`SessionKey.current` 形如 `agent:main:face-{hash}`，`hash` 由 `setToUser` 中 `userid.toByteArray().fold(0){acc,b->(acc*31+b) and 0xFFFFFF}.toString(16)` 生成。在 `SessionKey` 新增公开的 `hashUserId(name): String`（复用同一算法），`FaceManageBottomSheet` 用它和 `current` 后缀比对，避免算法重复。

### 2.7 数据流

```
进入「ID 管理」tab
  → onViewCreated → startOMSStream
    → 循环 pullFrame → showAndRecognize
      → drawFrame(视频帧 + 人脸框)
      → drawLivePreview(状态化圆形头像)        ← 新增
  → [用户点 📸 注册]
    → enrollVoice(latestBitmap)                ← 抓帧源改
      → enrollWithName → 存头像 → drawEnrollPreview(蓝边框 3s)
      → 切 session/记忆 + 问候
  → [用户点 🗑 管理]
    → FaceManageBottomSheet.show               ← 新增
      → 列出 names() + 头像
      → 选删 → 二次确认 → gallery.remove+save + 删头像 + (若当前用户)reset
```

## 三、组件改动

| 组件 | 改动 |
|------|------|
| `MainActivity.kt:69` | tab 名「视频流」→「ID 管理」 |
| `fragment_live_video_face.xml` | 删 `btn_select_stream`；按钮行只剩 注册+管理；`tv_status` 文案 |
| `LiveVideoFaceFragment.kt` | `onViewCreated` 自动开流；新增 `drawLivePreview`；`enrollVoice` 抓帧源改 `latestBitmap`；`btn_manage` 接线 |
| `LiveVideoFaceFragment.drawEnrollPreview` | 边框改显式描边（蓝 8f）+ 深色衬底，去 `alpha=40` 淡填充圆 |
| `SessionKey.kt` | 新增 `hashUserId(name)` 公开方法（复用 `setToUser` 算法） |
| `FaceManageBottomSheet.kt`（新建） | BottomSheet 列表 + 删除 + 二次确认 + session 重置 |
| `FaceGallery.kt` | **不改**（已有 `remove` / `save` / `names`） |

## 四、生命周期

- `onViewCreated` → `startOMSStream`（进入即预览）。
- `onDestroyView` → `stopOMSStream`（沿用现有 `streamOn` / `omsJob` 机制）。
- `onPause`（tab 切走）停流省带宽 / `onResume` 重启——**可选优化，MVP 不做**（`onDestroyView` 级别足够，ViewPager2 切走会触发）。

## 五、边界与错误处理

- OMS 流不可达：保留 `fail>20` → `tv_status`「❌ OMS 流不可达」，圆形预览进「无脸」态。
- 画面过暗（`DARK_THR`）：保留，圆形预览「无脸」态。
- 注册时 `latestBitmap == null`：回退 `pullFrame()`，仍失败则提示「视频未就绪，请稍候」。
- `enrollWithName` 返回 null：提示「未检测到正脸，请正对镜头重试」（沿用现有）。
- 删除列表空：BottomSheet 显示「暂无已注册用户」。
- 删除当前 session 用户：`SessionKey.resetToDefault()` + `MEMORY.md` 重置为空文件（`rm` 软链 + 建空 + `chown u10_a150`）；下次识别无命中即停留在默认 session。

## 六、测试

- **`FaceGallery` 纯 JVM 单测**（已具备，纯 java.io + Gson）：`remove` 后 `names()` 不含；`save()` + `load()` 往返一致；`bestMatch` 不再返回已删用户。
- **`SessionKey` 单测**：`hashUserId(name)` 与 `setToUser(name)` 后 `current` 的后缀一致。
- **Fragment / BottomSheet / Canvas 层**：车机装机实测（项目无 Android UI 测试基建）——验证：进入即预览、状态化边框、注册用当前帧、删除生效且 session 重置正确。

## 七、不在范围

- 头像编辑 / 更换（注册时存一张即可）。
- 语音或手动修改注册名字（仍自动生成「形容词+动物」）。
- 批量删除 / 多选（一次删一个）。
- 删除时清理 `memory_faceid_{name}.md` 记忆文件（MVP 保留，避免 root/shell 写入复杂度；可作后续增强，附带在删除步骤里 `rm` 对应文件）。
- `onPause/onResume` 停流重启优化。
