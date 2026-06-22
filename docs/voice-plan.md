# 车载语音助手 — 实施计划 v2

## 目标

在仰望车机上重新搭建语音交互系统：
- **核心场景**：音乐控制 + 导航控制（语音/文字输入）
- **语音输入**：车机麦克风（VoiceWake 连续监听 → 后续改为唤醒词）
- **语音输出**：车机扬声器 TTS 播放
- **文字通道**：飞书（已有）/ QQ / 微信
- **LLM**：开发机 MiniCPM-o-4.5 (172.20.10.5:8080)

---

## Phase 1：安装最新 OpenClaw + 基础环境

### 1.1 Node.js 运行环境

从备份恢复到车机：

```bash
adb push car-backup/node-termux /data/local/tmp/
adb push car-backup/node-lib/ /data/local/tmp/node-lib/
adb shell ln -sf /data/local/tmp/node-termux /data/local/tmp/node
adb shell chmod +x /data/local/tmp/node-termux
```

### 1.2 安装最新 OpenClaw (2026.5.7)

```bash
# 开发机上下载最新版
npm pack openclaw@latest
# 得到 openclaw-2026.5.7.tgz

# 解压到临时目录，推送到车机
tar xzf openclaw-2026.5.7.tgz
adb push package/ /data/local/tmp/openclaw/
adb shell ln -sf ../lib/node_modules/openclaw/openclaw.mjs /data/local/tmp/openclaw/bin/openclaw
```

### 1.3 配置 OpenClaw

```bash
# 创建 HOME 目录
adb shell mkdir -p /data/local/tmp/openclaw-home/.openclaw/workspace/skills/car-control

# 写入 openclaw.json（MiniCPM 模型 + zai 补丁）
# 写入 SKILL.md（车机控制指令）
```

### 1.4 zai 插件补丁

修补 `provider-zai-endpoint-C002s1Qu.js` 和 `model-definitions-DQoIKn0X.js`，将 GLM URL 替换为 MiniCPM API：
```
https://api.z.ai/api/paas/v4 → http://172.20.10.5:8080/v1
https://open.bigmodel.cn/api/paas/v4 → http://172.20.10.5:8080/v1
```

### 1.5 验证

```bash
# 启动 gateway
adb shell "HOME=/data/local/tmp/openclaw-home nohup node-termux openclaw.mjs gateway --port 18801 &"

# 测试 API 连通
curl http://172.20.10.4:18801/__openclaw__/canvas/ -H "Authorization: Bearer <token>"
```

---

## Phase 2：车机控制服务

重新实现 car-router，专注两个核心场景。

### 2.1 car-router.js

HTTP API 服务 (端口 18800)，接收 OpenClaw 的 bash 命令调用。

**音乐控制 API：**

| Action | 参数 | 功能 | 实现 |
|--------|------|------|------|
| `music_play` | - | 播放 | `cmd media_session dispatch play` |
| `music_pause` | - | 暂停 | `cmd media_session dispatch pause` |
| `music_next` | - | 下一首 | `cmd media_session dispatch next` |
| `music_prev` | - | 上一首 | `cmd media_session dispatch previous` |
| `music_search` | query | 搜索播放 | AccessibilityService 操控媒体中心 |

**导航控制 API：**

| Action | 参数 | 功能 | 实现 |
|--------|------|------|------|
| `nav_search` | dest | 搜索目的地 | AccessibilityService 操控地图 → 返回结果列表 |
| `nav_select` | dest, choice | 选择结果开始导航 | 坐标点击 → 点击"去这里" |
| `nav_home` | - | 回家 | `input tap 241 488` |
| `nav_work` | - | 去公司 | `input tap 543 488` |

### 2.2 AccessibilityService (com.caragent.bootstrap)

编译安装 Android App，提供：
- `setText` — 直接设置中文文本（绕过 input 限制）
- `click` / `findAndClick` — 按 text/resource-id 查找并点击
- `waitFor` — 等待 UI 元素出现
- `scroll` — 列表滚动
- 开机自启 + 看门狗

### 2.3 SKILL.md

LLM 指令，告诉模型如何通过 bash 执行车机命令。

### 2.4 验证

飞书发 "播放周杰伦的青花瓷" → 执行 → 音乐播放
飞书发 "导航到大梅沙" → 搜索 → 选择 → 开始导航

---

## Phase 3：语音输入输出（VoiceWake 连续监听）

### 3.1 架构

```
[车机麦克风] → ALSA 录音
    ↓ (PCM 16kHz, 分块)
[Voice Agent] → WebSocket → [OpenClaw Gateway :18801]
    ↓
[STT :8090] → faster-whisper → 文字
    ↓
[MiniCPM :8080] → LLM → 回复文字 + 指令
    ↓                              ↓
[TTS :8091] ← 回复文字    [car-router :18800] → 执行
    ↓
[Voice Agent] ← 音频流 ← ALSA 播放
```

### 3.2 STT 服务（开发机 :8090）

```bash
# faster-whisper，OpenAI Whisper API 兼容
pip install faster-whisper-server
faster-whisper-server --host 0.0.0.0 --port 8090 --model large-v3

# 或 whisper.cpp
./server -m ggml-large-v3.bin --port 8090 --host 0.0.0.0
```

### 3.3 TTS 服务（开发机 :8091）

```bash
# Edge TTS（免费，中文好）封装为 OpenAI TTS 兼容 API
pip install edge-tts
# 封装：POST /v1/audio/speech → edge-tts 合成 → 返回 MP3
```

### 3.4 Voice Agent（车机）

Node.js 脚本，负责：
1. 从 ALSA 录音（16kHz mono S16LE）
2. VAD 静音检测，判断一句话结束
3. 通过 OpenClaw Gateway WebSocket 发送音频
4. 接收 TTS 音频回复
5. 通过 ALSA 播放

需要实测确定 ALSA 设备：
```bash
# 麦克风测试（逐个尝试 pcmC0D15c ~ pcmC0D38c）
tinycap /sdcard/test.wav -D hw:0,15 -r 16000 -c 1 -b 16 -T 3

# 扬声器测试（逐个尝试 pcmC0D0p ~ pcmC0D14p）
tinyplay /sdcard/test.wav -D hw:0,0
```

### 3.5 OpenClaw 语音配置

```json
{
  "talk": {
    "provider": "openai",
    "stt": {
      "provider": "openai",
      "baseUrl": "http://172.20.10.5:8090/v1"
    },
    "tts": {
      "provider": "openai",
      "baseUrl": "http://172.20.10.5:8091/v1",
      "voice": "zh-CN-XiaoxiaoNeural"
    },
    "speechLocale": "zh-CN",
    "silenceTimeoutMs": 1500,
    "interruptOnSpeech": true
  }
}
```

### 3.6 验证

对车机麦克风说 "播放音乐" → STT → LLM → 执行 → TTS 播放 "好的，正在播放"

---

## Phase 4：QQ / 微信通道

### 4.1 QQ 通道

OpenClaw qqbot 插件需要 npm 依赖。方案：
1. 开发机 `npm install` 装好依赖
2. 打包 node_modules 推送到车机
3. 配置 QQ Bot AppID/Token

### 4.2 微信通道

无官方插件，需要开发机跑桥接（wechaty）：
```
微信消息 → wechaty(开发机) → WebSocket → OpenClaw Gateway → 回复
```

### 4.3 语音消息

收到 SILK/AMR 语音 → 转码 PCM → STT → LLM → TTS/文字回复

---

## Phase 5：唤醒词（路线 C）

替换 Phase 3 的连续监听，改为本地唤醒词。

### 5.1 方案

OpenClaw 最新版 (2026.5.7) 内置 Vosk 离线唤醒词检测。

或使用 Porcupine：
- arm64 预编译库，CPU < 1%
- 自定义唤醒词 "你好仰望" / "小迪小迪"
- 检测到后触发 Voice Agent 开始录音

### 5.2 架构

```
待机：[Porcupine 唤醒词检测] ← 持续低功耗监听
  ↓ 检测到 "小迪小迪"
激活：[ALSA 录音 → STT → LLM → TTS → 播放]
  ↓ 回复完毕
待机：[回到唤醒词检测]
```

---

## 阶段总结

| Phase | 内容 | 依赖 | 状态 |
|-------|------|------|------|
| 1 | 最新 OpenClaw + Node.js + MiniCPM | 备份文件 | ✅ 完成 |
| 2 | car-router + AccessibilityService + 飞书 | Phase 1 | ✅ 完成 |
| 3 | VoiceWake 语音输入输出 | Phase 2 + 开发机 STT/TTS | ✅ 完成 |
| 4 | QQ/微信通道 | Phase 2 | ✅ QQ完成，微信待做 |
| 5 | 唤醒词按需激活 | Phase 3 | 待开始 |
| 6 | agent_front_app 音色/方言控制 | Phase 4 | 🔧 进行中 |

### Phase 6：App 音色控制

**目标：** 通过车机 App（agent_front_app）控制 TTS 输出音色，包括 4 个预设音色、自定义音色描述、方言设置。

**核心机制：**
- 预设音色使用参考音频（ref_audio）做声音克隆，保证一致性
- 自定义音色首次用 prompt_text 生成，adapter 自动保存为 ref_audio 并升级
- 方言作为独立字段，同时注入 TTS（prompt 前缀）和 LLM（SOUL.md）
- POST /v1/voices 为 merge 模式，只更新发送的字段

**音色映射：**
| Index | 音色 | 样本 | ref_audio |
|-------|------|------|-----------|
| 0 | 温柔女声 | sample_1.wav (8.0s) | voice_samples/sample_1.wav |
| 1 | 活泼女声 | sample_2.wav (5.6s) | voice_samples/sample_2.wav |
| 2 | 沉稳男声 | sample_3.wav (6.4s) | voice_samples/sample_3.wav |
| 3 | 知性女声 | sample_4.wav (6.1s) | voice_samples/sample_4.wav |

**文件：**
- `tts-adapter/adapter.py` — dialect 字段、merge 更新、auto_ref、GET endpoint
- `tts-adapter/voice_samples/` — 4 个预设 WAV 样本
- `agent_front_app/` — PersonaFragment + TtsApiClient + AudioPreviewPlayer

## 环境信息

```
车机:
  OS:        Android 14 (SDK 34), arm64
  Kernel:    Linux 6.1.115
  CPU:       6核 ARM Cortex
  RAM:       10GB (可用 ~4GB)
  Storage:   230GB (已用 11GB)
  Audio:     ALSA，多路 PCM capture/playback
  WiFi:      172.20.10.4

开发机:
  LLM:       MiniCPM-o-4.5 :8080
  STT:       faster-whisper :8090 (待部署)
  TTS:       Edge TTS :8091 (待部署)

OpenClaw:
  当前版本:  2026.4.24 (已卸载)
  目标版本:  2026.5.7 (最新稳定版)
  新特性:    Vosk 离线唤醒词、语音管线改进、Termux 兼容修复
```
