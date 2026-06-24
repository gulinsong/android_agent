# 豆包 Realtime 闲聊 App

独立 Android app，豆包端到端 Realtime API 纯语音闲聊（always-on + 打断）。
设计与实现文档见 `docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md`
与 `docs/superpowers/plans/2026-06-24-doubao-realtime-chitchat.md`。

## 配置鉴权
在 `~/.gradle/gradle.properties` 加（不入库）：
```
doubaoAppId=你的AppID
doubaoAccessKey=你的AccessKey
```
构建时通过 `-PdoubaoAppId=... -PdoubaoAccessKey=...` 传入也可。

## 构建/安装（BYD 车机）
```
./gradlew assembleDebug
adb -s <车机serial> install -r app/build/outputs/apk/debug/app-debug.apk
# BYD 多用户录音权限需手动授予
adb -s <车机serial> shell pm grant com.openclaw.chitchat android.permission.RECORD_AUDIO
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
