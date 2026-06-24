# 豆包 Realtime 闲聊 App 实现笔记

- 日期：2026-06-24
- 工程：`doubao_chitchat/`（独立 Android app，BYD 车机）
- API：豆包端到端实时语音大模型 Realtime API（https://www.volcengine.com/docs/6561/1594356 ）
- 设计 spec：`docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md`

## 最终成果

端到端跑通：WebSocket 连接 → 开场白播放 → 对话（说→识别→语音回复）→ 打断（插话停 TTS）→ 多轮 → 稳定不崩。首响延迟 **<100ms**（用户说完→模型首音频同毫秒），远优于 VoxCPM2 流式的 561–638ms。

## 踩坑与解决（按定位顺序）

### 1. 鉴权：文档的 X-Api-App-ID 套件已过时 → 实测 X-Api-Key
文档 1594356 写要 `X-Api-App-ID` + `X-Api-Access-Key` + `X-Api-Resource-Id` + `X-Api-App-Key` 四个 header。**新版控制台只需一个 API Key**。用 curl 实测 WebSocket 握手（`--http1.1` + Upgrade headers）确认：
- 老套件（App-ID 填任意）→ `401 Unauthorized`
- `X-Api-Key` + `X-Api-Resource-Id` + `X-Api-App-Key` → `101 Switching Protocols` ✓
- `X-Api-Key` 单独（缺 Resource-Id/App-Key）→ `403`

结论：header 用 `X-Api-Key` + `X-Api-Resource-Id`(固定 `volc.speech.dialog`) + `X-Api-App-Key`(固定 `PlgvMymc7f3tQnJ6`)，**无需 App ID**。教训：火山文档与控制台不同步，鉴权以实测握手为准。

### 2. BYD 多用户权限：`pm grant` 必须带 `--user`
`adb shell pm grant <pkg> RECORD_AUDIO` 默认授权到 user 0，但 app 跑在 **user 10**（`UserInfo{10:司机}`）。不带 `--user` 时权限不生效，app 启动后弹到 `GrantPermissionsActivity`（权限授权页），现象是"app 没起来"。
修复：`adb shell pm grant --user 10 com.openclaw.chitchat android.permission.RECORD_AUDIO`。

### 3. 音频输出路由：`USAGE_ASSISTANT` 在车机无声 → `USAGE_MEDIA`
AudioTrack 用 `USAGE_ASSISTANT`（语音助手通道），AudioFlinger 显示流活跃、音量正常、数据持续 `write`，但**完全无声**。
诊断关键：在 AudioPlayer 里加**本地 440Hz 正弦波测试音**（绕过网络，纯测 AudioTrack）。测试音能听到 → AudioTrack/路由之外没问题；TTS 音频听不到 → 数据问题。实测测试音**能听到**，证明是路由问题。
修复：`USAGE_ASSISTANT` → `USAGE_MEDIA`（媒体通道，车机默认接扬声器）。

### 4. interrupt bug：打断后回复无声
`AudioPlayer.interrupt()` 原实现"关闭旧 channel + 重建 channel + flush"，但**没重启播放协程**——播放协程的 `for (pcm in channel)` 绑定的是旧 channel，旧 channel close 后协程退出，新 channel 的回复数据再无人消费 → 开场白能听（无打断）、回复听不到（用户说话触发 450→interrupt→协程死）。
修复：interrupt 改"排空 channel 已排队数据 + `track.flush()`"，**不重建 channel、不重启协程**，单一协程持续消费。

### 5. SIGSEGV 崩溃：并发 write + release race
修复 #4 初版用"interrupt 重启 job"，引入新问题：旧协程阻塞在 `track.write`（native 阻塞，cancel 不立即响应），新协程又启动 → 两个协程并发 write 同一 AudioTrack；`stop()` 里 `track.release()` 时旧协程可能还在 write → `Fatal signal 11 (SIGSEGV) in AudioPlayer$launchPlayback`。
修复：(a) 回到单一播放协程（interrupt 不重启）；(b) `stop()` 改 `suspend fun`，先 `channel.close()` + `job.join()`（等协程完全退出）再 `track.release()`。

### 6. 回声循环：always-on 全双工 + AEC 不足
现象：模型说完(359)→紧接 450(用户开口)→459→回复→359→450… 无限循环。`interrupt_score` 全 0.03–0.19（极低，是**模型声音被麦录回的回声**，不是真语音）。
根因：车机硬件 AEC 接入 Android `AcousticEchoCanceler` 效果有限，残留回声仍被服务端 VAD 当用户说话。
修复（组合拳，保留全双工打断）：
- 录音音源 `MIC` → `VOICE_COMMUNICATION`（触发系统 AEC 路径）
- 叠加 `AcousticEchoCanceler` + `NoiseSuppressor` + `AutomaticGainControl`（实测三者 `enabled=true` 都生效）
- 服务端 `asr.extra.end_smooth_window_ms = 2000`（停说判定窗口拉长，减少回声尾音误触发 459）
- **客户端 RMS 能量门限**（最有效）：录音每包算 RMS，真语音 RMS 5000–16000，回声/噪音 RMS <1000，门限卡 **1500**，低于门限的包**上传静音包**（保持时序，服务端 VAD 不触发）而非丢弃

RMS 门限值按 `AR` 日志的 `rms=` 实测标定：门限必须在"回声尖峰"和"真语音最低值"之间，本车机 1500 合适。

### 7. 频控：频繁重连触发 `resource not granted`
反复 restart/reconnect + curl 测试，短时间触发火山风控，握手返回 `{"error":"[resource_id=volc.speech.dialog] requested resource not granted"}`（注意是 403 不是 429）。等几分钟自动恢复。教训：调试期控制重连频率，reconnect 指数退避要到位。

### 8. 音量偏小：服务端响度控制
TTS 输出音量偏小。用文档的服务端响度参数（比客户端软件放大音质好）：`tts.audio_config.loudness_rate = 100`（范围 `[-50,100]`，最大档）+ `tts.extra.enable_loudness_norm = true`（2.0 模型响度均衡）。

## 最终关键参数（`Config.kt`）

| 项 | 值 |
|---|---|
| 鉴权 header | `X-Api-Key` + `X-Api-Resource-Id=volc.speech.dialog` + `X-Api-App-Key=PlgvMymc7f3tQnJ6` |
| model | `1.2.1.1`（O2.0，非 demo 的 "O"） |
| 音色 | `zh_female_xiaohe_jupiter_bigtts`（小何） |
| 上行音频 | PCM 16kHz / mono / int16 小端，20ms=640 字节/包 |
| 下行音频 | `pcm_s16le` 24kHz / mono（免 Opus 解码） |
| 录音音源 | `VOICE_COMMUNICATION` + AEC + NS + AGC |
| RMS 门限 | 1500（低于则上传静音包） |
| `end_smooth_window_ms` | 2000 |
| `loudness_rate` / `enable_loudness_norm` | 100 / true |
| AudioTrack 输出 | `USAGE_MEDIA` + `CONTENT_TYPE_MUSIC` |
| 打断策略 | `ASRInfo(450)` → 排空 channel + `AudioTrack.flush()`（单协程，不重启） |

## 二进制协议要点（移植自官方 Java demo）
- 帧 = 4 字节 header + optional + payload，**大端序**
- header: `[0x11] [type<<4|flag] [ser|comp] [0x00]`；type `FULL_CLIENT=1/AUDIO_ONLY_CLIENT=2/FULL_SERVER=9/AUDIO_ONLY_SERVER=11/ERROR=15`
- optional 顺序: event(4B) → sessionId(len+UTF8) → connectId → sequence → errorCode → payload
- sessionId 仅当事件**不是** `1/2/50/51/52`；音频帧用 `marshalRawAudio`（serialization=RAW, event=200）
- 单测用文档真实字节 fixture（StartConnection `[17,20,16,0,0,0,0,1,0,0,0,2,123,125]`）round-trip 验证

## 工程结构
`doubao_chitchat/`（独立 Gradle 工程，minSdk26/compileSdk34，OkHttp+Gson+coroutines）：
`Protocol.kt`（二进制帧）/ `Config.kt`（鉴权+payload）/ `RealtimeClient.kt`（OkHttp WS+事件分发）/ `AudioRecorder.kt`（录音+AEC+NS+AGC+RMS门限）/ `AudioPlayer.kt`（播放+打断）/ `CallManager.kt`（状态机+重连）/ `ui/`（Activity+ViewModel+开始/暂停按钮）。
