# 豆包 Realtime 闲聊 App

独立 Android app，豆包端到端 Realtime API 纯语音闲聊（always-on + 打断）。
设计与实现文档见 `docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md`
与 `docs/superpowers/plans/2026-06-24-doubao-realtime-chitchat.md`。

## 配置鉴权（实测：新版只需 API Key，无需 App ID）
握手实测：`X-Api-Key` + `X-Api-Resource-Id`(固定) + `X-Api-App-Key`(固定) 返回 101。
在 `~/.gradle/gradle.properties` 加（不入库）：
```
doubaoApiKey=你的API Key
```
构建时通过 `-PdoubaoApiKey=...` 传入也可。

## 构建/安装（BYD 车机）
```
./gradlew assembleDebug
adb -s <车机serial> install -r app/build/outputs/apk/debug/app-debug.apk
# BYD 多用户：app 跑在 user 10，权限必须 grant 给当前 user（不带 --user 会授权到 user 0 无效）
adb -s <车机serial> shell pm grant --user $(adb -s <车机serial> shell am get-current-user | tr -d '\r') com.openclaw.chitchat android.permission.RECORD_AUDIO
```

## 单测
```
./gradlew :app:testDebugUnitTest
```
覆盖 `Protocol.kt`（字节帧 round-trip）与 `Config` payload（model=1.2.1.1、pcm_s16le）。

## 架构
- `Protocol.kt` 二进制帧 marshal/unmarshal（移植自官方 demo）
- `RealtimeClient.kt` OkHttp WebSocket + 事件分发
- `AudioRecorder.kt` 16kHz 录音 20ms 分包 / `AudioPlayer.kt` 24kHz 播放 + ASRInfo 打断
- `CallManager.kt` 会话状态机 + 指数退避重连
- `ui/ChitchatActivity` + `ChitchatViewModel` 极简全屏 + 生命周期/权限/音频焦点
