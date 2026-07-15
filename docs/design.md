# 车载语音助手 — 设计文档

## 1. 系统组件

### 1.1 组件清单

| 组件 | 位置 | 职责 |
|------|------|------|
| OpenClaw Gateway | 车机 :18801 | 消息路由、会话管理、skill 调度、语音管线 |
| OpenClaw feishu 插件 | 车机 (内置) | 飞书 WebSocket 长连接，收发消息 |
| OpenClaw qqbot 插件 | 车机 (内置) | QQ Bot API，收发消息 + 语音 |
| car-router | 车机 :18800 | 车机控制指令执行（音乐/导航） |
| MiniCPM LLM | 开发机 :8080 | 大模型推理（OpenAI 兼容 API） |
| STT Service | 开发机 :8090 | 语音转文字 |
| TTS Service | 开发机 :8091 | 文字转语音 |
| Voice Agent | 车机 | ALSA 音频采集/播放 |

### 1.2 架构图

```
┌────────────────────────────────────────────────────────────┐
│                     OpenClaw Gateway (:18801)               │
│                                                            │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │ feishu 插件   │  │ qqbot    │  │ talk-voice / speech  │ │
│  │ (内置 WS)    │  │ 插件     │  │     core 插件        │ │
│  └──────┬───────┘  └────┬─────┘  └──────────┬───────────┘ │
│         │               │                    │             │
│         └───────────────┼────────────────────┘             │
│                         │                                  │
│              ┌──────────┴──────────┐                       │
│              │   Agent / SKILL.md  │                       │
│              └──────────┬──────────┘                       │
└─────────────────────────┼──────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ↓               ↓               ↓
   [MiniCPM :8080]  [STT :8090]  [TTS :8091]
   (开发机 LLM)     (开发机)      (开发机)
          │
          ↓ bash 命令
   [car-router :18800]
          │
          ↓
   [AccessibilityService → BYD App]
```

### 1.3 不再需要的组件

| 组件 | 原因 |
|------|------|
| ~~feishu-ws.js~~ | OpenClaw 内置 feishu 插件，原生支持飞书 WebSocket 长连接 |
| ~~car-cmd.sh~~ | car-router 直接提供 HTTP API，LLM 通过 bash curl 调用（或 car-router 内置简化接口） |

---

## 2. OpenClaw 通道配置

### 2.1 飞书通道（内置）

OpenClaw feishu 插件直接支持飞书 WebSocket 模式，无需自写桥接。

**依赖处理**：feishu 插件需要 `@larksuiteoapi/node-sdk`，车机无 npm。方案：
1. 开发机 `mkdir /tmp/feishu-deps && cd /tmp/feishu-deps && npm init -y && npm install @larksuiteoapi/node-sdk typebox@1.1.31`
2. 打包 `tar czf feishu-deps.tgz node_modules/`
3. 推送到车机 plugin-runtime-deps 目录
4. 或直接放入 OpenClaw 的 extensions/feishu/node_modules/

**openclaw.json 配置**：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "accounts": {
        "default": {
          "appId": "cli_a9658c749eb81cc5",
          "appSecret": "lfTd3y2Dw3X083iB5g0nDfHbAxfdaibO",
          "domain": "feishu"
        }
      }
    }
  }
}
```

### 2.2 QQ 通道（内置）

qqbot 插件内置 STT 支持，可直接处理语音消息。

**依赖**：`@tencent-connect/qqbot-connector`, `silk-wasm`, `mpg123-decoder`, `ws`, `zod`
同飞书方案，开发机预装后推送。

**openclaw.json 配置**：

```json
{
  "channels": {
    "qqbot": {
      "enabled": true,
      "accounts": {
        "default": {
          "appId": "<QQ_APP_ID>",
          "clientSecret": "<QQ_CLIENT_SECRET>",
          "stt": {
            "enabled": true,
            "baseUrl": "http://172.20.10.2:8090/v1"
          }
        }
      }
    }
  }
}
```

### 2.3 微信通道（无内置插件）

需要自建桥接服务，在开发机运行：

```
微信 → wechaty (开发机) → WebSocket → OpenClaw Gateway
```

---

## 3. Voice Agent 设计

### 3.1 路线 A — 连续监听模式（Phase 3）

```
┌─────────────────────────────────────────────────────┐
│                    Voice Agent                       │
│                                                     │
│  ┌──────────┐    ┌───────────┐    ┌──────────────┐ │
│  │  Audio    │    │  WebSocket│    │   Audio      │ │
│  │  Capture  │───→│  Client   │───→│   Playback   │ │
│  │ (ALSA)    │    │ (to GW)   │    │  (ALSA)      │ │
│  └──────────┘    └─────┬─────┘    └──────────────┘ │
│                        │                            │
│                   ┌────┴────┐                       │
│                   │ Control │                       │
│                   │  Logic  │                       │
│                   └─────────┘                       │
└─────────────────────────────────────────────────────┘
```

**流程：**

1. ALSA 录音 (16kHz mono S16LE)
2. 200ms 分块通过 WebSocket 发送到 Gateway
3. Gateway speech-core → STT → LLM → TTS
4. 接收 TTS 音频流 → ALSA 播放
5. 播放完毕恢复录音

### 3.2 路线 C — 唤醒词模式（Phase 5）

```
待机：[Porcupine / Vosk 唤醒词检测] ← 低功耗监听
  ↓ 检测到 "小迪小迪"
激活：[ALSA 录音 → STT → LLM → TTS → 播放]
  ↓ 回复完毕
待机：[回到唤醒词检测]
```

### 3.3 ALSA 设备探测

车机有多路 PCM 设备，需要实测确定麦克风和扬声器：

```bash
# 录音测试（逐个尝试 pcmC0D15c ~ pcmC0D38c）
tinycap /sdcard/test.wav -D hw:0,<N> -r 16000 -c 1 -b 16 -T 3

# 播放测试（逐个尝试 pcmC0D0p ~ pcmC0D14p）
tinyplay /sdcard/test.wav -D hw:0,<N>
```

### 3.4 VAD 语音活动检测

基于 RMS 能量的简单 VAD：

```javascript
function detectSpeech(pcmBuffer, threshold = 500) {
  let sum = 0;
  for (let i = 0; i < pcmBuffer.length; i += 2) {
    const sample = pcmBuffer.readInt16LE(i);
    sum += sample * sample;
  }
  const rms = Math.sqrt(sum / (pcmBuffer.length / 2));
  return rms > threshold;
}
```

静音超时 1.5s 后认为一句话结束。

---

## 4. STT/TTS 服务设计

### 4.1 STT 服务（开发机 :8090）

OpenAI Whisper 兼容 API：

```
POST /v1/audio/transcriptions
Content-Type: multipart/form-data

file: <audio>  model: whisper-1  language: zh

→ { "text": "导航到大梅沙" }
```

| 方案 | 延迟 | 质量 | GPU |
|------|------|------|-----|
| faster-whisper large-v3 | 1-2s | 高 | 4GB+ |
| whisper.cpp large-v3 | 1-3s | 高 | 可 CPU |
| faster-whisper medium | 0.5-1s | 中 | 2GB |

### 4.2 TTS 服务（开发机 :8091）

OpenAI TTS 兼容 API：

```
POST /v1/audio/speech

{ "model": "tts-1", "input": "好的", "voice": "zh-CN-XiaoxiaoNeural" }

→ audio/mpeg
```

| 方案 | 延迟 | 质量 | GPU |
|------|------|------|-----|
| Edge TTS | 0.5-1s | 中 | 无 |
| CosyVoice | 1-2s | 高 | 6GB+ |

---

## 5. OpenClaw 语音配置

```json
{
  "talk": {
    "provider": "openai",
    "stt": {
      "provider": "openai",
      "baseUrl": "http://172.20.10.2:8090/v1",
      "model": "whisper-1",
      "language": "zh"
    },
    "tts": {
      "provider": "openai",
      "baseUrl": "http://172.20.10.2:8091/v1",
      "voice": "zh-CN-XiaoxiaoNeural"
    },
    "speechLocale": "zh-CN",
    "silenceTimeoutMs": 1500,
    "interruptOnSpeech": true
  }
}
```

---

## 6. 车机控制（car-router + AccessibilityService）

### 6.1 car-router API

| Action | 参数 | 功能 |
|--------|------|------|
| music_play | - | 播放 |
| music_pause | - | 暂停 |
| music_next | - | 下一首 |
| music_prev | - | 上一首 |
| music_search | query | 搜索播放歌曲 |
| nav_search | dest | 搜索目的地，返回结果列表 |
| nav_select | dest, choice | 选择结果开始导航 |
| nav_home | - | 回家 |
| nav_work | - | 去公司 |

### 6.2 AccessibilityService

com.caragent.bootstrap App 提供 UI 自动化：
- setText（中文输入）
- click / findAndClick
- waitFor
- scroll

### 6.3 SKILL.md

```yaml
---
name: car-control
description: Control BYD Yangwang car apps (music, map)
tools:
  - bash
---

你是仰望车载语音助手。回复简短自然，适合语音播报。

## 指令对照表
| 用户说 | 执行命令 |
|--------|---------|
| 播放 | cmd media_session dispatch play |
| 暂停 | cmd media_session dispatch pause |
| 下一首 | cmd media_session dispatch next |
| 上一首 | cmd media_session dispatch previous |
| 回家 | input tap 241 488 |
| 去公司 | input tap 543 488 |
| 导航到XX | curl -s http://127.0.0.1:18800/command -d '{"action":"nav_search","dest":"XX"}' 然后 curl ... nav_select |
| 播放XX | curl -s http://127.0.0.1:18800/command -d '{"action":"music_search","query":"XX"}' |

## 规则
- 导航必须连续执行 nav_search + nav_select
- 做不到的事直说
```

注：curl 如果车机没有，需要 car-router 提供一个轻量 wrapper 或者直接用 `node -e` 调 HTTP。

---

## 7. 插件依赖预装方案

车机无 npm，所有插件依赖在开发机预装后推送。

```bash
# 开发机上
mkdir /tmp/openclaw-deps && cd /tmp/openclaw-deps

# 飞书依赖
mkdir feishu && cd feishu && npm init -y && npm install @larksuiteoapi/node-sdk typebox@1.1.31 && cd ..

# QQ 依赖
mkdir qqbot && cd qqbot && npm init -y && npm install @tencent-connect/qqbot-connector silk-wasm mpg123-decoder ws zod && cd ..

# 打包推送到车机
tar czf openclaw-deps.tgz feishu/ qqbot/
adb push openclaw-deps.tgz /data/local/tmp/
adb shell "cd /data/local/tmp && tar xzf openclaw-deps.tgz"
```

部署时将 node_modules 放入对应插件的 extensions 目录。
