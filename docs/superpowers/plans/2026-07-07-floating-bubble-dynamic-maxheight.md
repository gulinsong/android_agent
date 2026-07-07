# 悬浮窗 AI 回复区动态最大高度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `tv_ai_response` 的高度上限从写死的 `maxLines=3` 改为随悬浮窗 y 位置动态计算的"到屏幕可见底部 - 24dp"的像素值,1 行 48dp 兜底,长内容在框内滚动。

**Architecture:** 抽出一个不依赖 Android Context 的纯计算对象 `BubbleBoundsCalculator`(便于 JVM 单测);`FloatingBubbleService` 在三个钩子(展开、拖拽松手、内容更新)调用它算出 maxHeight 并 `setMaxHeight`,snapshot 图片渲染复用同一上限做 clamp。

**Tech Stack:** Kotlin, Android WindowManager(`TYPE_APPLICATION_OVERLAY`), JUnit4(纯函数单测,不走 Robolectric), Gradle。

**Spec:** `docs/superpowers/specs/2026-07-07-floating-bubble-dynamic-maxheight-design.md`

## Global Constraints

- 底部安全间距 = `24dp`;最小高度兜底 = `48dp`(约 1 行 + padding);header 未 measure 时兜底 = `48dp`。
- 重算时机仅三处:`expand()` addView 后、拖拽 `ACTION_UP` 后、`updateExpandedContent()` 末尾。**不在 `ACTION_MOVE` 每帧重算。**
- `params.y` 为负时按 0 参与运算。
- 保留 `ScrollingMovementMethod`(已存在于 `FloatingBubbleService.kt:479`),超长内容在限高框内可滚动。
- 不改收起态悬浮球,不响应横竖屏旋转。
- 所有 Gradle 命令从仓库根 `/home/tsm/work/android_agent` 运行,形如 `./agent_front_app/gradlew -p agent_front_app <task>`(不要 `cd`)。

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `agent_front_app/app/src/main/java/com/openclaw/car/util/BubbleBoundsCalculator.kt` | 纯函数:由悬浮窗顶部 y / 屏幕高 / 各占位算出 tv_ai_response 的 maxHeight(px) | Create |
| `agent_front_app/app/src/test/java/com/openclaw/car/util/BubbleBoundsCalculatorTest.kt` | JVM 单测(正常/负y/小可用兜底/header未测) | Create |
| `agent_front_app/app/src/main/res/layout/floating_bubble_expanded.xml` | 删 `tv_ai_response` 的 `maxLines`/`ellipsize` | Modify |
| `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt` | 加 `currentMaxHeightPx()`/`recomputeAiResponseBounds()`;三钩子调用;snapshot clamp | Modify |

---

### Task 1: BubbleBoundsCalculator 纯计算 + JVM 单测(TDD)

**Files:**
- Create: `agent_front_app/app/src/main/java/com/openclaw/car/util/BubbleBoundsCalculator.kt`
- Test: `agent_front_app/app/src/test/java/com/openclaw/car/util/BubbleBoundsCalculatorTest.kt`

**Interfaces:**
- Produces: `BubbleBoundsCalculator.computeAiResponseMaxHeightPx(bubbleTopY, screenHeightPx, headerHeightPx, upperExtrasPx, lowerOccupiedPx, density): Int` —— Task 3 依赖此签名。
- Produces 常量: `BOTTOM_MARGIN_DP=24`, `MIN_HEIGHT_DP=48`, `DEFAULT_HEADER_DP=48`。

- [ ] **Step 1: 写失败测试**

Create `agent_front_app/app/src/test/java/com/openclaw/car/util/BubbleBoundsCalculatorTest.kt`:

```kotlin
package com.openclaw.car.util

import org.junit.Assert.assertEquals
import org.junit.Test

class BubbleBoundsCalculatorTest {
    // density=2 → 1dp=2px:BOTTOM_MARGIN=48px, MIN_HEIGHT=96px, DEFAULT_HEADER=96px
    private val d = 2f

    @Test
    fun normalPosition_subtractsAllOccupied() {
        // 1920 - 400(y) - 48(margin) - 100(header) - 8(upper) - 8(lower) = 1356
        val h = BubbleBoundsCalculator.computeAiResponseMaxHeightPx(
            bubbleTopY = 400, screenHeightPx = 1920,
            headerHeightPx = 100, upperExtrasPx = 8, lowerOccupiedPx = 8, density = d
        )
        assertEquals(1356, h)
    }

    @Test
    fun negativeY_clampedToZero() {
        // y=-50 → 0; 1920 - 0 - 48 - 100 - 8 - 8 = 1756
        val h = BubbleBoundsCalculator.computeAiResponseMaxHeightPx(
            bubbleTopY = -50, screenHeightPx = 1920,
            headerHeightPx = 100, upperExtrasPx = 8, lowerOccupiedPx = 8, density = d
        )
        assertEquals(1756, h)
    }

    @Test
    fun smallAvailable_fallsBackToMinHeight() {
        // y=1850, header=0→96(default); 1920-1850-48-96-8-8 = -90 → clamp to MIN(96)
        val h = BubbleBoundsCalculator.computeAiResponseMaxHeightPx(
            bubbleTopY = 1850, screenHeightPx = 1920,
            headerHeightPx = 0, upperExtrasPx = 8, lowerOccupiedPx = 8, density = d
        )
        assertEquals(96, h)
    }

    @Test
    fun headerNotMeasured_usesDefault() {
        // header=0→96; 1920 - 400 - 48 - 96 - 8 - 8 = 1360
        val h = BubbleBoundsCalculator.computeAiResponseMaxHeightPx(
            bubbleTopY = 400, screenHeightPx = 1920,
            headerHeightPx = 0, upperExtrasPx = 8, lowerOccupiedPx = 8, density = d
        )
        assertEquals(1360, h)
    }
}
```

- [ ] **Step 2: 跑测试确认失败(类不存在)**

Run: `./agent_front_app/gradlew -p agent_front_app testDebugUnitTest --tests "com.openclaw.car.util.BubbleBoundsCalculatorTest"`
Expected: 编译失败 / `Unresolved reference: BubbleBoundsCalculator`

- [ ] **Step 3: 写最小实现**

Create `agent_front_app/app/src/main/java/com/openclaw/car/util/BubbleBoundsCalculator.kt`:

```kotlin
package com.openclaw.car.util

/**
 * 悬浮窗展开态尺寸计算(纯函数,不依赖 Android Context,
 * density 作为参数传入,便于 JVM 单测)。
 */
object BubbleBoundsCalculator {

    /** header measure 未就绪时的兜底高度(dp) */
    const val DEFAULT_HEADER_DP = 48

    /** 距屏幕可见底部的安全间距(dp) */
    const val BOTTOM_MARGIN_DP = 24

    /** tv_ai_response 最小高度兜底(dp),约 1 行 + padding */
    const val MIN_HEIGHT_DP = 48

    /**
     * 计算 tv_ai_response 的最大高度(px)。
     *
     * @param bubbleTopY      悬浮窗顶部 y(WindowManager.LayoutParams.y);负数按 0
     * @param screenHeightPx  屏幕可见高度 px(currentWindowMetrics.bounds.height)
     * @param headerHeightPx  header 实测高度 px;<=0 表示未 measure,用 [DEFAULT_HEADER_DP] 兜底
     * @param upperExtrasPx   tv_ai_response 上方额外占位 px(根 paddingTop + tv marginTop)
     * @param lowerOccupiedPx tv_ai_response 下方占位 px(根 paddingBottom + 若 snapshot 可见则其已测高度)
     * @param density         屏幕密度(getResources.displayMetrics.density)
     * @return setMaxHeight 的值(px),不会小于 1 行兜底
     */
    fun computeAiResponseMaxHeightPx(
        bubbleTopY: Int,
        screenHeightPx: Int,
        headerHeightPx: Int,
        upperExtrasPx: Int,
        lowerOccupiedPx: Int,
        density: Float
    ): Int {
        val y = bubbleTopY.coerceAtLeast(0)
        val bottomMargin = (BOTTOM_MARGIN_DP * density).toInt()
        val minHeight = (MIN_HEIGHT_DP * density).toInt()
        val defaultHeader = (DEFAULT_HEADER_DP * density).toInt()
        val header = if (headerHeightPx > 0) headerHeightPx else defaultHeader
        val available = screenHeightPx - y - bottomMargin - header - upperExtrasPx - lowerOccupiedPx
        return available.coerceAtLeast(minHeight)
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./agent_front_app/gradlew -p agent_front_app testDebugUnitTest --tests "com.openclaw.car.util.BubbleBoundsCalculatorTest"`
Expected: `BUILD SUCCESSFUL`,4 个 test 全 PASS

- [ ] **Step 5: Commit**

```bash
git add agent_front_app/app/src/main/java/com/openclaw/car/util/BubbleBoundsCalculator.kt \
        agent_front_app/app/src/test/java/com/openclaw/car/util/BubbleBoundsCalculatorTest.kt
git commit -m "feat(bubble): 抽 BubbleBoundsCalculator 纯函数算动态 maxHeight

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 布局删 maxLines / ellipsize

**Files:**
- Modify: `agent_front_app/app/src/main/res/layout/floating_bubble_expanded.xml:89-102`

**Interfaces:**
- 无对外接口;只是移除 `tv_ai_response` 的行数硬上限,改由代码 `setMaxHeight` 承载。

- [ ] **Step 1: 删除 maxLines 与 ellipsize 属性**

在 `floating_bubble_expanded.xml` 的 `tv_ai_response` 节点(当前 L89-102)中,删掉这两行:

```xml
        android:maxLines="3"
        android:ellipsize="end"
```

保留 `android:scrollbars="none"` 和代码里的 `ScrollingMovementMethod()`(滚动由 setMaxHeight + movement method 承载)。改完后的 `tv_ai_response` 应形如:

```xml
    <!-- AI回复 - 高度由代码 setMaxHeight 动态限高(到屏幕可见底部-24dp),超出在框内滚动 -->
    <TextView
        android:id="@+id/tv_ai_response"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginStart="4dp"
        android:layout_marginEnd="4dp"
        android:layout_marginTop="4dp"
        android:background="@drawable/bubble_ai_box_bg"
        android:padding="8dp"
        android:textColor="#E6FFFFFF"
        android:textSize="14sp"
        android:scrollbars="none" />
```

- [ ] **Step 2: 编译验证资源无错**

Run: `./agent_front_app/gradlew -p agent_front_app assembleDebug`
Expected: `BUILD SUCCESSFUL`(确认没有其它地方依赖被删属性)

- [ ] **Step 3: Commit**

```bash
git add agent_front_app/app/src/main/res/layout/floating_bubble_expanded.xml
git commit -m "feat(bubble): 删 tv_ai_response 的 maxLines=3,改由代码动态限高

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: FloatingBubbleService 集成三钩子 + snapshot clamp

**Files:**
- Modify: `agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt`
  - 顶部 import 区加一行 import
  - 新增两个私有方法 `currentMaxHeightPx()` / `recomputeAiResponseBounds()`
  - 三个钩子点各加一次调用:`expand()`(L513 后)、`updateExpandedContent()`(L589 when 块后)、拖拽 `ACTION_UP`(L861 后)
  - `refreshSnapshotUi()`(L618)`targetHeight` 追加 `.coerceAtMost(currentMaxHeightPx())`

**Interfaces:**
- Consumes: `BubbleBoundsCalculator.computeAiResponseMaxHeightPx(...)`(Task 1 产出)。

- [ ] **Step 1: 加 import**

在 `FloatingBubbleService.kt` 顶部 import 区(其它 `com.openclaw.car.*` import 附近)加:

```kotlin
import com.openclaw.car.util.BubbleBoundsCalculator
```

- [ ] **Step 2: 加两个私有方法**

在 `FloatingBubbleService.kt` 中,紧挨 `getScreenHeight()`(约 L892-894)之前,插入:

```kotlin
    /** 当前 tv_ai_response 应用的最大高度(px);snapshot 与文字共用此上限。 */
    private fun currentMaxHeightPx(): Int {
        val view = expandedView
        val density = resources.displayMetrics.density
        val minPx = (BubbleBoundsCalculator.MIN_HEIGHT_DP * density).toInt()
        if (view == null) return minPx

        val header = view.findViewById<View>(R.id.bubble_header)
        val headerH = if (header != null && header.height > 0) header.height else 0
        // 上方额外占位:根 paddingTop(4dp) + tv_ai_response marginTop(4dp)
        val upperExtras = (8 * density).toInt()
        // 下方占位:根 paddingBottom(4dp) + 若 snapshot 可见则其已测高度
        val snapshot = view.findViewById<android.widget.FrameLayout>(R.id.snapshot_card)
        val lowerOccupied = (4 * density).toInt() +
            if (snapshot != null && snapshot.visibility != View.GONE && snapshot.height > 0) snapshot.height
            else 0

        return BubbleBoundsCalculator.computeAiResponseMaxHeightPx(
            bubbleTopY = expandedParams?.y ?: 0,
            screenHeightPx = getScreenHeight(),
            headerHeightPx = headerH,
            upperExtrasPx = upperExtras,
            lowerOccupiedPx = lowerOccupied,
            density = density
        )
    }

    /** 根据当前位置重算并应用 tv_ai_response 的最大高度。 */
    private fun recomputeAiResponseBounds() {
        val view = expandedView ?: return
        val tvAiResponse = view.findViewById<TextView>(R.id.tv_ai_response) ?: return
        tvAiResponse.setMaxHeight(currentMaxHeightPx())
    }
```

- [ ] **Step 3: 钩子一 —— expand() 展开后调用**

定位 `expand()` 里的 `windowManager.addView(expandedView, params)`(约 L513),在它**后面**紧接着加一行:

```kotlin
        windowManager.addView(expandedView, params)
        recomputeAiResponseBounds()
```

(此时 header 可能尚未 measure,会走 48dp 兜底;随后内容更新会再算一次。)

- [ ] **Step 4: 钩子二 —— updateExpandedContent() 末尾调用**

在 `updateExpandedContent()` 的 `when { ... }` 块结束 `}`(约 L589)之后、方法结束 `}`(约 L590)之前,加一行:

```kotlin
        }

        recomputeAiResponseBounds()
    }
```

(即 when 块收尾后、方法 return 前调用一次。)

- [ ] **Step 5: 钩子三 —— 拖拽 ACTION_UP 后调用**

在 `setupDrag` 的 `ACTION_UP` 分支(约 L859-863),`lastPosY = params.y` 之后加一行:

```kotlin
                MotionEvent.ACTION_UP -> {
                    lastPosX = params.x
                    lastPosY = params.y
                    recomputeAiResponseBounds()
                    if (!isDragging) view.performClick()
                }
```

- [ ] **Step 6: snapshot 图片 clamp**

在 `refreshSnapshotUi()`(约 L618)把:

```kotlin
        val targetHeight = (raw.height * ratio).toInt().coerceAtLeast(1)
```

改为:

```kotlin
        val targetHeight = (raw.height * ratio).toInt()
            .coerceAtLeast(1)
            .coerceAtMost(currentMaxHeightPx())
```

- [ ] **Step 7: 编译 + 跑全部单测,确认无回归**

Run: `./agent_front_app/gradlew -p agent_front_app assembleDebug testDebugUnitTest`
Expected: `BUILD SUCCESSFUL`,所有单测(含 Task 1 的 4 个)PASS

- [ ] **Step 8: Commit**

```bash
git add agent_front_app/app/src/main/java/com/openclaw/car/service/FloatingBubbleService.kt
git commit -m "feat(bubble): 集成动态 maxHeight(展开/松手/内容更新三钩子)+ snapshot clamp

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 车机端到端手动验证

**Files:** 无代码改动;装车实测。

> 这一任务无自动化测试(WindowManager 悬浮窗 + 拖拽 + 屏幕底部遮挡需在真实车机上看),按 spec 的"仪器测"清单逐项确认。

- [ ] **Step 1: 装 APK 到车机**

Run(确认设备在线): `adb devices`
Run: `./agent_front_app/gradlew -p agent_front_app installDebug`(或用项目既有装车脚本)
Expected: `Success`

- [ ] **Step 2: 验证四个场景**

触发悬浮窗展开后,逐项核对:

1. **正常位置**:悬浮窗展开在屏幕中部 → AI 回复一条长文本 → 底部不超过屏幕可见底部 - 24dp,且文本可在框内上下滚动至末尾。
2. **拖到屏幕下半**:展开后把悬浮窗拖到接近屏幕底 → 松手 → 回复区高度自动收缩到新上限,仍不超出可见底部。
3. **极靠下兜底**:拖到几乎贴底 → 松手 → 回复区保留约 1 行(48dp),不塌缩为 0。
4. **短回复不撑高**:回复只有一句话 → 悬浮窗仍然小巧(自适应未破坏,不像以前那样永远 3 行高)。
5. **snapshot 图片**(若触发卡片场景):图片高度被同样 clamp,不顶出底部。

- [ ] **Step 3: logcat 抽查(可选)**

Run: `adb logcat -s FloatingBubbleService | grep -i snapshot`
Expected: snapshot 渲染日志里 scaled 高度 ≤ 当前可用上限。

- [ ] **Step 4: 全部通过后,无新增 commit(Task 3 已含全部代码)**

如发现回归,回到 Task 1/3 修正后重测。

---

## Self-Review

**1. Spec coverage:**
- 删 maxLines 改 setMaxHeight → Task 2(删)+ Task 3(setMaxHeight)✓
- 动态公式(屏底-24dp-上方占位-下方占位)→ Task 1 计算函数 + Task 3 装配 ✓
- 重算三钩子(展开/松手/内容更新)→ Task 3 Step 3/4/5 ✓
- 不在 ACTION_MOVE 重算 → plan 明确未在 ACTION_MOVE 加调用 ✓
- 1 行 48dp 兜底 → Task 1 `MIN_HEIGHT_DP` + coerceAtLeast ✓
- params.y 为负按 0 → Task 1 `coerceAtLeast(0)` ✓
- snapshot 同源 clamp → Task 3 Step 6 ✓
- 单测(正常/负y/小可用/header默认)→ Task 1 四个 case ✓
- 仪器测五场景 → Task 4 ✓
- 不改收起态 / 不响应旋转 → 未涉及 collapsedView / 配置变更 ✓

**2. Placeholder scan:** 无 TODO/TBD;所有代码块完整;行号带"约"字因编辑会漂移,但定位锚点(addView、when 块结束、ACTION_UP、targetHeight 行)唯一可识别。✓

**3. Type consistency:** `computeAiResponseMaxHeightPx(bubbleTopY:Int, screenHeightPx:Int, headerHeightPx:Int, upperExtrasPx:Int, lowerOccupiedPx:Int, density:Float): Int` —— Task 1 定义与 Task 3 `currentMaxHeightPx()` 调用参数顺序/类型完全一致;常量 `MIN_HEIGHT_DP` Task 1 定义、Task 3 引用一致。✓
