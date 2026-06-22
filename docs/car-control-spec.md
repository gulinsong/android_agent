# 车机控制场景 — 音乐控制 & 导航控制

> ⚠️ **本文档为早期设计草案（2026-05），实现已大幅演进**：
> - **音乐控制**已废弃 `cmd media_session dispatch` 和 AccessibilityService 操控方案，改用 **AUTOVOICE 广播**直发到 BYD mediacenter。实际方案见 `kaka_skills/car-music/SKILL.md` 和 `agent_front_app/.../music/BydMusicController.kt`。
> - **导航控制**已废弃 `input tap` 坐标点击和 `car-cmd.sh` 脚本，改用 **BYD Map Protocol SDK + 高德 API**。实际方案见 `kaka_skills/car-nav/SKILL.md` 和 `agent_front_app/.../service/MapProtocolManager.kt`。
> - **HTTP 端口**已从 18800 改为 **18802**，端点路径也调整（`/music/play` 保留，新增 `/music/search` `/music/volume` `/music/state` 等）。
> - **包名**已从 `com.caragent.bootstrap` 改为 `com.openclaw.car`。
>
> 保留此文档作为历史参考，**不要按此实现新功能**。

## 1. 概述

两个核心车机控制场景，通过 AccessibilityService 操控 BYD 原生 App：
- **音乐控制**：播放/暂停/切歌 + 搜索播放指定歌曲
- **导航控制**：搜索目的地 → 展示结果列表 → 选择并开始导航

控制链路：

```
用户指令 → OpenClaw (LLM) → car-router API → AccessibilityService → BYD App
```

---

## 2. 车机 App 信息

| App | 包名 | Activity | 用途 |
|-----|------|----------|------|
| BYD 媒体中心 | `com.byd.mediacenter` | `.main.MediaActivity` | 音乐播放 |
| BYD 地图 | `com.byd.launchermap` | `com.byd.automap.activity.MainActivity` | 导航 |
| BYD 车机系统 | - | - | MediaSession 控制音视频 |

屏幕分辨率：1728 x 1888

---

## 3. 音乐控制

### 3.1 场景列表

| 场景 | 用户指令示例 | 实现方式 |
|------|-------------|---------|
| 播放 | "播放音乐" / "继续播放" | `cmd media_session dispatch play` |
| 暂停 | "暂停" / "暂停音乐" | `cmd media_session dispatch pause` |
| 下一首 | "下一首" / "切歌" | `cmd media_session dispatch next` |
| 上一首 | "上一首" | `cmd media_session dispatch previous` |
| 搜索播放 | "播放周杰伦的青花瓷" | AccessibilityService 操控媒体中心 |
| 收藏 | "收藏这首歌" | AccessibilityService 点击收藏按钮（待实现） |

### 3.2 搜索播放流程

通过 AccessibilityService 操控 BYD 媒体中心 App：

```
1. 强制停止媒体中心      → am force-stop com.byd.mediacenter
2. 启动媒体中心          → am start -n com.byd.mediacenter/.main.MediaActivity
3. 等待加载 (3s)         → waitFor(target="搜索")
4. 点击搜索按钮          → findAndClick(target="搜索")
5. 等待搜索框 (2s)       → waitFor(target="搜索")
6. 输入搜索词            → setText(text="周杰伦 青花瓷", target="搜索")
7. 回车搜索              → input keyevent 66
8. 等待结果 (5s)         → waitFor(target="青花瓷")
9. 点击匹配结果          → clickResult(target="青花瓷")
10. 播放                 → cmd media_session dispatch play
```

### 3.3 API 调用

```
POST http://127.0.0.1:18800/command
Content-Type: application/json

# 搜索播放
{"action": "music_search", "query": "周杰伦 青花瓷"}

# 简单控制（通过 shell 命令，不经过 car-router）
cmd media_session dispatch play
cmd media_session dispatch pause
cmd media_session dispatch next
cmd media_session dispatch previous
```

### 3.4 搜索播放响应

```json
{
  "ok": true,
  "reply": "正在播放周杰伦青花瓷"
}
```

### 3.5 语音回复

| 场景 | 回复 |
|------|------|
| 播放成功 | "好的，正在播放[歌名]" |
| 暂停 | "已暂停" |
| 切歌 | "好的，下一首" |
| 搜索无结果 | "没找到[歌名]，换个名字试试？" |
| 搜索多个结果 | "找到了几首，正在播放第一首" |

---

## 4. 导航控制

### 4.1 场景列表

| 场景 | 用户指令示例 | 实现方式 |
|------|-------------|---------|
| 搜索目的地 | "导航到大梅沙" | AccessibilityService 操控地图 App |
| 选择结果 | "选第一个" / "2" | 坐标点击结果列表 |
| 回家 | "回家" | input tap 241 488（快捷按钮） |
| 去公司 | "去公司" | input tap 543 488（快捷按钮） |
| 取消导航 | "取消导航" | 待实现 |

### 4.2 导航搜索流程（nav_search）

分两步：先搜索，用户选择后再导航。

```
1. 强制停止地图          → am force-stop com.byd.launchermap
2. 启动地图              → am start -W -n com.byd.launchermap/com.byd.automap.activity.MainActivity
3. 等待加载 (10s)        → waitFor(target="查找目的地", text="10000")
4. 点击"查找目的地"      → findAndClick(target="查找目的地")
5. 等待输入框 (5s)       → waitFor(target="请输入目的地", text="5000")
6. 点击输入框            → click(target="请输入目的地")
7. 输入目的地            → setText(text="大梅沙", target="请输入目的地")
8. 等待联想结果 (3s)     → waitFor(target="大梅沙", text="3000")
9. 回车搜索              → input keyevent 66
10. 等待结果列表 (8s)    → waitFor(target="结果列表", text="8000")
11. dump UI 解析结果     → uiautomator dump → 解析 XML 提取结果
```

### 4.3 UI 解析逻辑

地图搜索结果的 UI dump 结构：

```xml
<ListView resource-id="com.byd.launchermap:id/slv_search_result_listview">
  <node text="1" />     <!-- 序号 -->
  <node text="大梅沙海滨公园" />  <!-- 名称 -->
  <node text="公园" />   <!-- 类型 -->
  <node text="12.5公里" /> <!-- 距离 -->
  <node text="2" />
  <node text="大梅沙地铁站" />
  ...
</ListView>
```

解析规则：找到纯数字节点（序号），后面紧跟的文字节点就是名称，再后面是类型和距离。

```javascript
// 解析逻辑
const results = [];
for (let i = 0; i < texts.length; i++) {
  if (/^\d+$/.test(texts[i]) && i + 1 < texts.length) {
    const name = texts[i + 1];
    const type = texts[i + 2]; // 如果不是纯数字或距离
    const dist = texts.find((t, j) => j > i && /\d+公里/.test(t));
    results.push({ idx: results.length + 1, name, type, dist });
  }
}
```

### 4.4 导航选择流程（nav_select）

```
1. 计算目标坐标         → x=860, y=430 + (choice-1)*160
2. 点击结果             → input tap 860 <y>
3. 等待详情页 (5s)      → waitFor(target="去这里")
4. 点击"去这里"         → findAndClick(target="去这里")
```

坐标计算（1728x1888 屏幕）：
- 结果列表 x 固定 860
- 第 1 个结果 y=430
- 每个结果间隔 160px
- 最多 5 个结果 (y=430 到 y=1070)

### 4.5 API 调用

```
# 第一步：搜索目的地
POST http://127.0.0.1:18800/command
{"action": "nav_search", "dest": "大梅沙"}

# 响应
{
  "ok": true,
  "reply": "搜索到3个结果：\n1. 大梅沙海滨公园 (公园) 12.5公里\n2. 大梅沙地铁站 (地铁站) 8.3公里\n3. 大梅沙奥特莱斯 (商场) 15.1公里\n回复数字选择，或说取消",
  "results": [
    {"idx": 1, "name": "大梅沙海滨公园", "type": "公园", "dist": "12.5公里"},
    {"idx": 2, "name": "大梅沙地铁站", "type": "地铁站", "dist": "8.3公里"},
    {"idx": 3, "name": "大梅沙奥特莱斯", "type": "商场", "dist": "15.1公里"}
  ],
  "dest": "大梅沙"
}

# 第二步：选择并开始导航
POST http://127.0.0.1:18800/command
{"action": "nav_select", "dest": "大梅沙", "choice": "1"}

# 响应
{
  "ok": true,
  "reply": "正在导航到大梅沙海滨公园"
}
```

### 4.6 语音回复

| 场景 | 回复 |
|------|------|
| 有结果 | "搜索到N个结果：1. xxx N公里，2. xxx N公里。选第几个？" |
| 无结果 | "没找到[目的地]，换个说法试试？" |
| 选择成功 | "好的，正在导航到[目的地]" |
| 无效选择 | "没有这个选项，请重新选择" |

### 4.7 快捷导航

回家/去公司使用屏幕固定位置的快捷按钮，无需搜索：

```
回家：input tap 241 488
去公司：input tap 543 488
```

---

## 5. AccessibilityService 命令参考

所有 UI 自动化通过广播发送：

```bash
am broadcast -n com.caragent.bootstrap/.UiCommandReceiver \
  -a com.caragent.UI_CMD \
  --es action <action> \
  --es text <text>      # 可选 \
  --es target <target>   # 可选
```

| Action | 参数 | 说明 |
|--------|------|------|
| `click` | target | 点击包含 target 文字的节点 |
| `setText` | text, target | 在 target 输入框中设置文字（支持中文） |
| `findAndClick` | target | 查找并点击一步完成 |
| `clickResult` | target | 在搜索结果中点击匹配项 |
| `scroll` | text=(forward/backward) | 滚动列表 |
| `waitFor` | target, text=(timeout ms) | 等待 target 出现 |

启用 AccessibilityService：

```bash
adb shell settings put secure enabled_accessibility_services \
  com.caragent.bootstrap/com.caragent.bootstrap.UiAutomationService
```

---

## 6. SKILL.md（LLM 指令）

```yaml
---
name: car-control
description: Control BYD Yangwang car apps (music, map, UI automation)
tools:
  - bash
---

# Car Control Skill

你是仰望车载语音助手。回复简短自然，适合语音播报。

## 指令对照表

| 用户说 | 执行命令 |
|--------|---------|
| 播放 | `cmd media_session dispatch play` |
| 暂停 | `cmd media_session dispatch pause` |
| 下一首 | `cmd media_session dispatch next` |
| 上一首 | `cmd media_session dispatch previous` |
| 回家 | `input tap 241 488` |
| 去公司 | `input tap 543 488` |
| 导航到XX | 先执行 `sh /data/local/tmp/car-cmd.sh nav_search dest=XX`，然后执行 `sh /data/local/tmp/car-cmd.sh nav_select dest=XX choice=1` |
| 播放XX | `sh /data/local/tmp/car-cmd.sh music_search query=XX` |

## 绝对规则

- 导航时必须连续执行 nav_search 和 nav_select，不能只执行一个
- 不要用 curl（车机不存在）
- 不要用 am start 打开地图（没用）
- 做不到的事直说
```

---

## 7. 已知问题 & 改进方向

### 7.1 当前限制

| 问题 | 原因 | 影响 |
|------|------|------|
| 导航选择坐标硬编码 | 不同分辨率/ DPI 偏移 | 升级车机后可能失效 |
| 音乐搜索结果直接播放第一个 | 无结果列表展示 | 可能播放错误歌曲 |
| 无空调/车窗控制 | 未接入车辆 CAN 总线 | 功能受限 |
| UI 操作延迟固定 | 网络抖动时超时 | 偶尔操作失败 |

### 7.2 改进方向

- **坐标自适应**：通过 resource-id 查找节点，获取 bounds 坐标
- **音乐结果列表**：同导航一样返回列表供选择
- **车辆控制 API**：接入 BYD 开放平台或 CAN 总线
- **重试机制**：UI 操作失败后自动重试
- **超时动态调整**：根据网络状态调整 waitFor 时间
