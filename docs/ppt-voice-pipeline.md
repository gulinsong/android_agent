# PPT 语音交互链路

## 链路概述

用户通过悬浮球 PPT 按钮，实现完整的语音交互闭环：

```
PPT按钮按下 → MediaRecorder录音 → FunASR语音识别 → Gateway对话 → TTS语音合成 → 扬声器播放
```

## 详细流程

### 1. 录音（AudioRecorder）

- API：`MediaRecorder`（标准 Android API，非 ALSA tinycap）
- 音频源：`MediaRecorder.AudioSource.MIC`
- 格式：MPEG_4 / AAC，16kHz 采样率，128kbps 码率
- 临时文件：`context.cacheDir/ppt_recording.m4a`（不能用 `/data/local/tmp/`，权限不足）

### 2. ASR 语音识别

- 端点：`http://172.20.10.5:8090/v1/audio/transcriptions`（FunASR）
- 输入：M4A 音频文件（`audio/mp4`）
- 输出：识别文字

### 3. Gateway 对话

- 端点：`http://127.0.0.1:18801/v1/chat/completions`（OpenClaw Gateway）
- 输入：ASR 识别的文字
- 输出：Agent 回复文字 + 执行指令

### 4. TTS 语音合成

- 端点：`http://172.20.10.5:8091/v1/audio/speech`（TTS 适配器 → VoxCPM2）
- 输入：Gateway 回复文字
- 输出：MP3 音频数据
- 首次请求需热身（VoxCPM2 CUDA Graph 编译约 119s，超时需提前发热身请求）

### 5. 扬声器播放

- API：`MediaPlayer`
- 临时文件：`context.cacheDir/ppt_tts_response.mp3`
- 播放完毕自动清理临时文件

## 踩坑记录

### 问题 1：BYD 多用户权限隔离

**现象**：`pm grant` 授权后录音仍然失败，`AudioRecord` 报 `permission denied`。

**根因**：BYD 车机 Android 14 多用户环境，app 运行在 User 10（UID `u10_aXXX`）。`pm grant` 不加 `--user` 参数默认只给 User 0 授权。

**解决**：
```bash
adb shell "pm grant --user 10 com.openclaw.car android.permission.RECORD_AUDIO"
```

验证：`dumpsys package com.openclaw.car | grep RECORD_AUDIO` 检查 User 10 下 `granted=true`。

### 问题 2：AudioRecord vs MediaRecorder 都被 AudioPolicy 拦截

**现象**：`AudioRecord` 和 `MediaRecorder` 都报 `setAudioSource failed` / `permission denied`。

**根因**：BYD 自定义 `AudioPolicyIntefaceImpl` 对非白名单 app 拦截录音。但通过系统 UI 弹窗授权（带 `USER_SET` flag）后可以正常使用。

**解决**：在 `MainActivity.onCreate()` 中加入运行时权限请求 `requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 100)`，用户授权后即可。

### 问题 3：临时文件写入权限

**现象**：`MediaRecorder` 报 `/data/local/tmp/ppt_recording.m4a: open failed: EACCES (Permission denied)`。

**根因**：`/data/local/tmp/` 目录 app 进程无写入权限。

**解决**：使用 `context.cacheDir` 代替。

### 问题 4：PPT 流程无 TTS 播放

**现象**：录音、ASR、Gateway 回复都正常，但扬声器没有声音。

**根因**：PPT 按钮流程原来只到 Gateway 返回文字就结束了，没有 TTS 合成和播放步骤。`TtsAudioPlayer` 监控的 outbound 目录是飞书通道的，PPT 走的 HTTP API 不会生成 outbound 文件。

**解决**：在 `sendAudioToGateway` 中加入 Step 3：提取 Gateway 回复文字 → 调 TTS 适配器 → MediaPlayer 播放。

## 重装 App 后必执行

```bash
# 悬浮窗权限
adb shell "appops set com.openclaw.car SYSTEM_ALERT_WINDOW allow"

# 录音权限（User 10）
adb shell "pm grant --user 10 com.openclaw.car android.permission.RECORD_AUDIO"

# ADB root
adb root

# 端口转发
adb forward tcp:18801 tcp:18801
```

## 关键文件

| 文件 | 作用 |
|------|------|
| `audio/AudioRecorder.kt` | MediaRecorder 录音 |
| `service/FloatingBubbleService.kt` | PPT 按钮交互、ASR → Gateway → TTS 完整链路 |
| `audio/TtsAudioPlayer.kt` | 飞书通道的 TTS outbound 文件播放（独立于 PPT） |

---

# 方言自动检测链路

## 概述

基于 FireRedLID 模型，STT 服务在语音识别的同时自动检测用户方言/语种，实现自动方言适配。

## 链路（飞书/Gateway 通道）

```
飞书语音消息 → Gateway → STT服务(8090)
                          ├→ SenseVoice ASR（并行）
                          └→ FireRedLID 方言检测（并行）
                                │
                    检测到方言 ──┤→ 注入 [系统检测到用户说的是XX] 标签
                                └→ 自动同步 TTS adapter 方言参数
                                        │
                                Agent 用方言回复
                                TTS 用方言生成语音
```

## 关键代码

**STT 服务**：`/home/tsm/work/stt/stt-server.py`（端口 8090）

核心逻辑：
1. SenseVoice ASR 和 FireRedLID 通过 `ThreadPoolExecutor` 并行执行
2. FireRedLID 检测结果通过 `DIALECT_MAP` 映射为中文名称
3. 检测到方言后：
   - 注入 `[系统检测到用户说的是XX，请用XX回复]` 到 ASR 文本末尾
   - 自动调 `POST http://127.0.0.1:8091/v1/tts-settings` 同步 TTS 方言参数
4. Agent 根据 `AGENTS.md` 中的方言适配规则用对应方言回复

**模型**：`/home/tsm/work/FireRedASR2S/pretrained_models/FireRedLID/`
- GPU fp16 推理，启动时自动加载
- 加载失败时降级为纯 ASR（方言检测关闭）

## 支持的方言映射

| FireRedLID 输出 | 中文映射 | 说明 |
|-----------------|---------|------|
| zh mandarin | (空) | 普通话，不注入标签 |
| zh xinan | 四川话 | 西南官话 |
| zh yue | 粤语 | 广东话 |
| zh north | 东北话 | 东北官话 |
| zh wu | 上海话 | 吴语 |
| zh min | 闽南话 | 闽南语 |
| zh xiang | 湖南话 | 湘语 |
| en | 英语 | English |
| ja | 日语 | Japanese |
| ko | 韩语 | Korean |

## PPT 通道注意

PPT 录音输出 M4A 格式，STT 服务收到后通过 ffmpeg 转为 16kHz WAV 再给 FireRedLID。当前 ffmpeg 转换临时文件有报错（`FileNotFoundError`），方言检测在 PPT 链路中未生效，需要排查。

## AGENTS.md 方言适配规则

Agent 的 AGENTS.md 中定义了方言适配规则（第 41-46 行）：
- 用户说任何语言/方言，Agent 必须用相同语言/方言回复
- `[系统检测到用户说的是XX，请用XX回复]` 标签由 STT 服务自动注入
- Agent 看到标签后自动匹配语言
