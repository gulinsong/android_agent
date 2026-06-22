# Android Car Agent Design - Yangwang DiLink300

## Overview

基于 OpenClaw 智能体框架的车载助手。OpenClaw Gateway 作为总入口，统一接收飞书/语音/文字输入，内置 LLM + 记忆 + Skill。car-router.js 作为执行后端，处理多步骤 AccessibilityService 操作。

## Device Profile

| Item | Value |
|------|-------|
| Device | YANGWANG DiLink300 |
| Android | 14 (SDK 34), MediaTek, arm64-v8a |
| RAM/Storage | 10GB / 230GB (226GB free) |
| Root | No |
| ADB | Works (USB + WiFi at 172.20.10.4) |
| Pre-installed | OpenClaw Android Node v2026.3.11 (`ai.openclaw.app`) + Assistant (`ai.openclaw.assistant`) with AccessibilityService enabled |
| Input Method | iFlytek (科大讯飞) |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       输入通道 (可插拔)                        │
│                                                              │
│  飞书 ──→ feishu-ws.js ──┐                                   │
│  语音 (后期) ──→ Deepgram ASR ──┤                              │
│  文字 (后期) ──→ 车机输入 ──┘                                   │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              OpenClaw Gateway (port 18790)                    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ LLM Client (内置)                                     │    │
│  │  当前: zai/glm-4.7 (智谱)                             │    │
│  │  可选: deepseek/deepseek-v4-flash                     │    │
│  │  输入: 消息 + workspace 记忆 + skill 指令              │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────┐  ┌──────────────────────────────────────┐      │
│  │ Memory   │  │ Skills                                │      │
│  │ (workspace)│  │  car-control: 音乐/地图/预设导航     │      │
│  │ USER.md  │  │  ui-explorer: UI探索 (TODO)           │      │
│  │ TOOLS.md │  │                                      │      │
│  │ AGENTS.md│  │                                      │      │
│  └──────────┘  └──────────────┬───────────────────────┘      │
└──────────────────────────────┼───────────────────────────────┘
                               │ bash skill 执行
                               │
              ┌────────────────┼────────────────────┐
              ▼                                     ▼
    ┌──────────────────┐              ┌──────────────────────────┐
    │ 简单命令 (直接)    │              │ 复杂操作 (car-router API) │
    │                  │              │                          │
    │ cmd media_session│              │ car-router.js :18800     │
    │ input tap        │              │  音乐搜索 (多步骤)         │
    │ am start         │              │  导航 (多步骤)            │
    └──────────────────┘              └────────────┬─────────────┘
                                                   │ am broadcast
                                                   ▼
                                      ┌──────────────────────────┐
                                      │ CarAgent App             │
                                      │ AccessibilityService     │
                                      │ query/click/setText/...  │
                                      └──────────────────────────┘
```

### Data Flow

1. **输入** — 飞书/语音/文字消息进入 OpenClaw Gateway
2. **OpenClaw 处理** — 内置 LLM 理解意图，结合 workspace 记忆和 skill 指令
3. **执行**：
   - **简单命令**（播放/暂停/切歌/回家/去公司）→ bash 直接执行
   - **复杂操作**（音乐搜索/导航）→ 调 car-router HTTP API → AccessibilityService 多步骤执行
4. **记忆更新** — agent 自主写入 workspace 文件

### Input Channels (可插拔)

| 通道 | 状态 | 方式 |
|------|------|------|
| 飞书 | 当前 | feishu-ws.js → OpenClaw Gateway API |
| 车机语音 | 后期 | Deepgram ASR → OpenClaw 内置语音处理 |
| 车机文字 | 后期 | App 输入框 → OpenClaw Gateway API |

### Memory System

| File | Content | Updated by |
|------|---------|------------|
| `USER.md` | User preferences (favorite artists, frequent places) | Agent auto-updates |
| `TOOLS.md` | Verified commands, working UI paths, environment notes | Agent auto-updates after exploration |
| `AGENTS.md` | Agent capabilities and behavior rules | Manual + agent |
| `SOUL.md` | Personality and communication style | Manual |
| Conversation history | Recent N turns context | OpenClaw auto-manages |

Memory triggers:
- "记住我喜欢周杰伦" → agent writes to USER.md
- "推荐首歌" → agent reads USER.md preferences
- "上次去的那个地方" → agent checks conversation history
- Successful UI exploration → agent writes path to TOOLS.md

### Voice Evolution (后期)

OpenClaw 内置完整语音支持：

| 能力 | 插件 | 说明 |
|------|------|------|
| ASR | Deepgram (nova-3) | 实时流式语音识别，需 `DEEPGRAM_API_KEY` |
| TTS | Edge TTS | 免费，中文支持好，无需 API Key |
| TTS | ElevenLabs | 高质量，需 `ELEVENLABS_API_KEY` |
| 语音通话 | voice-call | 完整 ASR → LLM → TTS 管道 |

切换语音只需在 openclaw.json 启用 voice-call + 配置 ASR/TTS provider。

## Components

### 1. OpenClaw Gateway (Deployed)

OpenClaw 2026.4.24 at `/data/local/tmp/openclaw/`. **总入口和智能体核心。**

- Config: `/data/local/tmp/openclaw-home/.openclaw/openclaw.json`
- Gateway: port 18790, LAN bind, token auth
- LLM: `zai/glm-4.7` (智谱)，可切换 `deepseek/deepseek-v4-flash`
- Workspace: `/data/local/tmp/openclaw-home/.openclaw/workspace/`
- Skills: `car-control` (已部署), `ui-explorer` (TODO)
- Startup: `/data/local/tmp/openclaw-gateway.sh`

### 2. feishu-ws.js (Running)

飞书消息通道适配器。转发到 OpenClaw Gateway API。

- Feishu SDK WebSocket 长连接
- Dedup: `seenMessages` Set by message_id
- Forwards to OpenClaw Gateway API
- Replies back to Feishu

### 3. car-router.js (Running)

复杂操作执行后端，port 18800。不再是入口。

- HTTP API: `POST /command` 接收 OpenClaw 转发的复杂操作
- Music search: `doMusicSearch()` via AccessibilityService broadcast
- Navigation: `doNavigationSearch()` via AccessibilityService broadcast
- 不再需要命令匹配、LLM 调用、Feishu 轮询

### 4. Node.js Runtime (Deployed)

Termux-compiled Node.js v25.8.2 running on the car via `LD_LIBRARY_PATH`.

| Path | Description |
|------|-------------|
| `/data/local/tmp/node-termux` | Node.js binary (arm64, Android linker) |
| `/data/local/tmp/node-lib/` | Shared libraries (libz, openssl, icu, cares, sqlite, libc++) |
| `/data/local/tmp/node-lib/openssl.cnf` | OpenSSL config |

### 5. Bootstrap Android App (Installed)

`com.caragent.bootstrap` — combines bootstrap + accessibility service.

- **NodeProcessService** — foreground service (NOTE: cannot exec node from app due to SELinux `untrusted_app` context; processes must run as shell user)
- **UiAutomationService** — AccessibilityService accepting broadcast commands
- **UiCommandReceiver** — receives `com.caragent.UI_CMD` broadcasts

AccessibilityService actions:
| Action | Description |
|--------|-------------|
| `query` | Dump all visible text (use `target=detail` for full node info) |
| `findAndClick` | Find by text/resource-id and click (tries parent if not clickable) |
| `clickResult` | Same as findAndClick but skips EditText nodes (for search results) |
| `setText` | Focus + set Chinese text on EditText |
| `scroll` | Scroll forward/backward in scrollable container |
| `waitFor` | Poll until target text appears (configurable timeout) |

### 6. UI Explorer Skill (TODO)

OpenClaw skill giving the agent general-purpose UI exploration capability.

**Strategy:**
1. `query detail` — see all interactive elements on screen
2. Analyze — identify clickable items, input fields, scroll containers
3. Act — `findAndClick` / `clickResult` / `setText` / `scroll`
4. Verify — `query detail` again to check result
5. Retry — try different approach if failed
6. Remember — write successful path to `TOOLS.md`

**Benefit:** Agent can handle arbitrary apps, not just hardcoded music/map flows. If an app updates its UI, the agent can re-explore and adapt.

### 7. Startup Script (TODO)

Unified script to start all services on boot.

```sh
/data/local/tmp/start-car-agent.sh
  ├─ OpenClaw Gateway (openclaw-gateway.sh)
  ├─ car-router.js (nohup node-termux)
  └─ feishu-ws.js (nohup node-termux)
```

## Verified Commands

### Music (via media_session)
```
cmd media_session dispatch play|pause|next|previous
```

### Music Search (via AccessibilityService)
```
1. am force-stop com.byd.mediacenter
2. am start -n com.byd.mediacenter/.main.MediaActivity
3. waitFor "搜索" → findAndClick "搜索"
4. setText "歌手 歌名" → input keyevent 66 (Enter)
5. waitFor "歌名" → clickResult "歌名" (skips EditText)
6. cmd media_session dispatch play
```

### Map (via AccessibilityService)
```
1. am force-stop com.byd.launchermap
2. am start -W -n com.byd.launchermap/com.byd.automap.activity.MainActivity
3. waitFor "查找目的地" → findAndClick "查找目的地"
4. click "请输入目的地" → setText "目的地" → keyevent 66
5. waitFor results → select → findAndClick "去这里"
```

### Map Presets (coordinates)
- "回家": `input tap 241 488`
- "去公司": `input tap 543 488`

## Known Issues

- **SELinux**: App (`untrusted_app` context) cannot exec binaries from its data dir or write to `/data/local/tmp/` or `/sdcard/`. All Node.js processes must run as shell user.
- **Process management**: `Process.destroy()` (SIGTERM) doesn't kill node; need SIGKILL. App's NodeProcessManager cannot start processes due to SELinux.
- **BYD multi-user**: App runs as user 10 (`u10a147`) on virtual display. Broadcasts may need `--user 10`.
- **Result file**: App cannot write to any shell-readable path. AccessibilityService results only via logcat.
- **Music search reliability**: `clickResult` action added to skip EditText nodes when clicking search results. `am force-stop` added before search to ensure clean state.
- **Navigation reliability**: Still inconsistent — UI operations may fail due to timing or app state.

## TODO

### Phase 1: Architecture Integration
- [ ] **Startup script** — unified `/data/local/tmp/start-car-agent.sh` to launch all 3 processes
- [ ] **feishu-ws.js 改造** — 从转发 car-router 改为转发 OpenClaw Gateway API
- [ ] **流式响应** — feishu-ws 用 SSE 接收 OpenClaw 流式输出，用飞书 PATCH message API 逐步更新消息。消息风格像人说话（"地图开了，我搜一下"），不要机器人进度条风格
- [ ] **car-router.js 简化** — 去掉命令匹配/LLM/Feishu 轮询，改为纯 HTTP API 执行后端（只保留音乐搜索和导航）
- [ ] **OpenClaw Gateway** — verify it starts and API is reachable; test token auth
- [ ] **OpenClaw car-control skill 更新** — 简单命令直接 bash 执行，复杂操作调 car-router API

### Phase 2: Workspace & Memory
- [ ] **Update AGENTS.md** — full capability description with current verified commands
- [ ] **Update car-control skill** — include music search and navigation flows
- [ ] **Update USER.md** — personalize with user info
- [ ] **Verify memory flow** — test "记住我喜欢周杰伦" → USER.md updated

### Phase 3: UI Explorer Skill
- [ ] **Write ui-explorer skill** — SKILL.md with AccessibilityService tool definitions and exploration strategy
- [ ] **Test exploration** — give agent an unfamiliar task, verify it can explore UI
- [ ] **Test learning** — verify successful paths get written to TOOLS.md

### Phase 4: Reliability & Voice
- [ ] **Fix navigation** — improve doNavigationSearch reliability
- [ ] **Fix music search** — stabilize doMusicSearch (currently works for some songs, not others)
- [ ] **Auto-restart** — handle car sleep/wake (not full reboot), process monitoring
- [ ] **Voice channel** — configure Deepgram ASR + Edge TTS in OpenClaw
- [ ] **Bootstrap App SELinux** — investigate if AppProcess or alternative can start node as shell user
