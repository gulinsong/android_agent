# AGenUI 集成方案 — 车机 App 富卡片 UI 渲染

## Context

当前车机 App（agent_front_app）只通过悬浮球显示纯文本消息。用户希望集成 AGenUI SDK，使 LLM 能够生成结构化 UI（天气卡片、POI 信息、音乐列表、导航路线等），并在新的 Activity 中以原生组件渲染。

后端目前输出纯文本，需要配置 A2UI generation skill 让 LLM 生成 A2UI 协议 JSON。

## 数据流

```
LLM（配置 A2UI skill）→ session JSONL → GatewayClient（轮询 2s）
                                                  │
                                    ┌─────────────┴──────────────┐
                                    ▼                            ▼
                           纯文本消息                     A2UI 协议 JSON
                           FloatingBubbleService         AGenUISurfaceActivity
                           （悬浮球显示文本）              （原生渲染富卡片）
```

## 实现方案

### Phase 1: 构建配置

1. **编译 AGenUI AAR**
   ```bash
   cd /home/tsm/work/android_agent/AGenUI && ./scripts/android/build.sh
   ```
   产出: `dist/android/release/AGenUI-Client-Android-release.aar`

2. **复制到 app/libs/**
   - 路径: `app/libs/AGenUI-Client-Android-release.aar`

3. **修改 `app/build.gradle.kts`**
   - 添加 AAR 文件依赖
   - 添加传递依赖: Picasso 2.8, Gson 2.10.1, CardView 1.0.0
   - 添加 `ndkVersion = "27.3.13750724"`，`abiFilters += "arm64-v8a"`
   - `packagingOptions.pickFirst("lib/arm64-v8a/libc++_shared.so")`

### Phase 2: 引擎初始化

4. **修改 `OpenClawApp.kt`**
   - `onCreate()` 中调用 `AGenUI.getInstance().initialize(this)`
   - 注册 PicassoImageLoader

5. **新建 `agenui/PicassoImageLoader.kt`**
   - 实现 AGenUI 的 `ImageLoader` 接口，基于 Picasso 加载图片

### Phase 3: 数据层改造

6. **修改 `GatewayClient.kt`**

   - 新增 `A2UIMessage` 数据类:
     ```kotlin
     data class A2UIMessage(val role: String, val content: String, val source: String = "")
     ```

   - 新增 `a2uiListener` 和 `setA2UIListener()` 方法

   - 修改 `parseLine()`: 增加 `role == "assistant"` 分支，检测 A2UI 协议

   - 新增 `isA2UIProtocol()` 检测方法:
     - 判断文本是否包含 `"version":"v0.9"` 或 `"createSurface"` / `"updateComponents"` / `"updateDataModel"` / `"deleteSurface"` 等关键词

### Phase 4: 新建 AGenUI Activity

7. **新建 `activity_agenui_surface.xml`**
   ```
   ┌──────────────────────────────────────────┐
   │  标题栏: "AGenUI"              x (关闭) │
   ├──────────────────────────────────────────┤
   │                                          │
   │   AGenUI Surface 渲染容器               │
   │   （FrameLayout, match_parent）          │
   │                                          │
   ├──────────────────────────────────────────┤
   │  纯文本回退区域（可选）                  │
   └──────────────────────────────────────────┘
   ```
   - 横屏优化，FrameLayout 容器占大部分高度

8. **新建 `AGenUISurfaceActivity.kt`**
   - `onCreate()`: 创建 `SurfaceManager`，注册 `ISurfaceManagerListener`
   - `onCreateSurface()`: 将 `surface.getContainer()` 添加到渲染容器
   - `onA2UIMessage()`: 接收 A2UI JSON，调用 `surfaceManager.receiveTextChunk()`
   - `onDestroy()`: 销毁 SurfaceManager

9. **注册 Activity**
   - `AndroidManifest.xml` 添加，`screenOrientation="landscape"`

### Phase 5: 触发与路由

10. **修改 `FloatingBubbleService.kt`**
    - `onCreate()` 注册 A2UI listener
    - 收到 A2UI 消息时自动启动 `AGenUISurfaceActivity`，携带数据
    - Activity 已运行时通过 GatewayClient 直接传递数据

11. **悬浮球增加入口**（可选）
    - 在展开态增加 AGenUI 图标按钮，手动打开 Activity

### Phase 6: 后端配置

12. **安装 A2UI skill**
    ```bash
    adb push /home/tsm/work/android_agent/AGenUI/skills/a2ui-generation \
      /data/local/tmp/openclaw-home/.openclaw/skills/
    ```

13. **修改 `AGENTS.md`**
    - 添加 A2UI 使用指引：适合富卡片场景使用，纯文字无需使用
    - 回复同时包含文字简述（TTS 播报）和 A2UI JSON（卡片渲染）

## 修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `app/build.gradle.kts` | 修改 | AAR 依赖 + NDK 配置 |
| `OpenClawApp.kt` | 修改 | AGenUI 引擎初始化 |
| `GatewayClient.kt` | 修改 | A2UI 消息检测与路由 |
| `FloatingBubbleService.kt` | 修改 | A2UI 触发逻辑 |
| `AndroidManifest.xml` | 修改 | 注册新 Activity |
| `activity_agenui_surface.xml` | 新建 | 渲染页面布局 |
| `AGenUISurfaceActivity.kt` | 新建 | 渲染页面逻辑 |
| `PicassoImageLoader.kt` | 新建 | 图片加载器 |
| AGENTS.md | 修改 | 添加 A2UI 使用指引 |
| A2UI skill | 新建（设备端） | 技能文件 |

## 验证

1. 编译安装 APK，确认悬浮球功能正常（无回归）
2. 手动启动 AGenUI Activity，通过 intent 传入示例 A2UI JSON，确认渲染正常
3. 配置 A2UI skill 后，通过飞书发送适合富卡片的请求，确认 Activity 自动启动并渲染
4. 确认纯文本消息仍然通过悬浮球显示
5. 确认 AGenUI Activity 关闭后，悬浮球仍正常工作
