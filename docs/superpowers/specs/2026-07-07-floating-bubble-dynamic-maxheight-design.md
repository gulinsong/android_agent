# 悬浮窗 AI 回复区动态最大高度

## 背景

车机悬浮窗(`FloatingBubbleService`)展开态的宽度固定为屏宽 50%,高度由内容撑开
(`WRAP_CONTENT`)。但 AI 回复区 `tv_ai_response` 在布局里写死了
`maxLines="3" + ellipsize="end"`,导致:

- 回复超过 3 行被截断,悬浮窗**实际高度被封顶**,并非真正的内容自适应;
- 用户体感是"高度不会随内容/位置变",与 `WRAP_CONTENT` 的语义相悖。

需求:`tv_ai_response` 的高度上限改为**动态值**——等于"当前悬浮窗位置到屏幕可见底部
未被遮挡区域的距离",且悬浮窗可随意拖动,上限需随位置变化。

## 方案选择

| 方案 | 思路 | 取舍 |
|---|---|---|
| **A. TextView.setMaxHeight 动态限高(采纳)** | 删 `maxLines=3`,改用代码算出的 `setMaxHeight(px)` | 改动集中在 `tv_ai_response`,保留根布局 `WRAP_CONTENT` 自适应语义;短内容仍小窗,长内容撑到上限后由 `ScrollingMovementMethod` 内部滚动 |
| B. 整窗 WindowManager height 动态算 | `expand()`/拖拽结束时把 `params.height` 从 `WRAP_CONTENT` 换成定值 | `WRAP_CONTENT` 被替成定值后短内容不会自动缩,需主动 measure 取 min;改动大、易回归。否决 |

## 设计

### 数据流

```
触发 recomputeAiResponseBounds()
  ├─ y = expandedParams.y.coerceAtLeast(0)            // 悬浮窗顶部,拖出顶时兜底
  ├─ available = screenHeight - y - BOTTOM_MARGIN(24dp)
  │              - 上方占位(根paddingTop + headerHeight + tv marginTop)
  │              - 下方占位(根paddingBottom + 若snapshot可见则其已测高度)
  ├─ maxHeightPx = available.coerceAtLeast(MIN_HEIGHT(48dp))   // 1 行兜底
  ├─ tv_ai_response.setMaxHeight(maxHeightPx)         // 替代原 maxLines=3
  └─ snapshot 渲染时 targetHeight.coerceAtMost(maxHeightPx)    // 同源 clamp
```

### 重算钩子(对应"松手 + 内容更新"时机)

1. `expand()`:`windowManager.addView(expandedView, params)`(L513)之后,首次定高
2. 拖拽 `ACTION_UP`(L859-863):存完 `lastPosY` 后立即重算
3. `updateExpandedContent()`(L536):每次更新回复文本后重算

**不**在 `ACTION_MOVE` 每帧重算(用户决策:避免闪烁/性能/滚动中高度突变)。

### 公式与边界

- `screenHeight` = `WindowManager.currentWindowMetrics.bounds.height()`(API30+ 已排除
  系统装饰区,车机底部状态栏若存在一般已被排除)。
- `BOTTOM_MARGIN = 24dp`(转 px),用户决策:贴可见底部再留 24dp。
- `headerHeight`:优先取 `bubble_header.measuredHeight`/`height`;measure 未就绪时退化
  兜底 `48dp`。
- **下方占位**:`根paddingBottom(4dp)` 必减;若 `snapshot_card` 当前可见(`visibility != GONE`),
  再减其已测高度。snapshot 不可见时只减 paddingBottom。
  → 当 snapshot 与文字同时显示时,tv_ai_response 上限会自动为图让出空间,二者总高不超屏。
- `MIN_HEIGHT = 48dp`(约 1 行 + padding),用户决策:空间不够时至少保留 1 行,
  允许此时略超出底边。
- `params.y` 为负(拖出屏幕顶):`coerceAtLeast(0)` 后再参与运算。

### 布局改动(`floating_bubble_expanded.xml`)

`tv_ai_response`(L89-102):

- 删除 `android:maxLines="3"`
- 删除 `android:ellipsize="end"`(改为由 `setMaxHeight` + 滚动承载)
- 保留 `android:scrollbars="none"` 与代码中的 `ScrollingMovementMethod()`(L479),
  超长内容在限高框内可滚动

### 顺手做的:`snapshot_image` 同源 clamp

`renderSnapshot`/缩放逻辑(L604-626)算出的 `targetHeight` 追加
`.coerceAtMost(maxHeightPx)`,避免高图撑出底边。共用同一个 `maxHeightPx` 来源。

## 测试

- **单测** `recomputeAiResponseBounds(paramsY, screenHeight, headerHeight)`:
  - 正常位置 → 输出 = screenHeight - y - 24dp - header - margins
  - `params.y < 0` → 按 0 算
  - 可用空间 < 48dp → 输出 48dp(MIN 兜底)
  - 超大屏 / 极小屏不崩溃
- **仪器测(车机)**:
  - `expand` → 拖到屏幕下半部 → 松手 → 截图确认悬浮窗底部 ≤ 屏幕可见底部 - 24dp
  - 长回复文本在限高框内可上下滚动至全文末尾
  - 短回复仍然只占 1~2 行(自适应未破坏)

## 明确不做的事(YAGNI)

- 不响应横竖屏旋转(车机固定横屏)。
- `ACTION_MOVE` 中不实时重算(已决策)。
- 不改收起态悬浮球(`collapsedView` 本就是 wrap_content 小图标)。
- 不引入 `OnLayoutChangeListener` 等监听;只在三个钩子主动重算。

## 关键决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| 重算时机 | 松手(ACTION_UP)+ 内容更新 | 简单稳定,不闪 |
| 底部边界 | 屏幕可见底部 - 24dp | bounds 已排装饰区,再留 24dp 防贴边 |
| 最小兜底 | 48dp(1 行) | 空间极小时仍可见一行,允许略超底边 |
| 实现路径 | 方案 A(TextView.setMaxHeight) | 保留 WRAP_CONTENT 语义,改动面小 |
| snapshot 一并 clamp | 是 | 共用上限,避免高图顶出底部 |
