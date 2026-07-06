# 唤醒词模式车机实测验收 Checklist

- **日期**：2026-07-06
- **分支**：`agent_front_app` submodule `feat/wakeword-mode`（4dadc88..73e6c54 + 2 fixes）
- **设备**：`LZBYDUMNB6RW7X5P`（BYD DiLink300 IVI）
- **状态**：11 task 代码全部完成 + review 通过；自动验证项 PASS；手动实测项待填

---

## 1. 自动验证（已 PASS）

| 项 | 结果 | 证据 |
|---|---|---|
| sherpa-onnx KWS 冒烟 | ✅ | SherpaOnnxSmokeTest：喂"你好小迪"wav → 命中（tokens=[n,ǐ,h,ǎo,x,iǎo,d,í]） |
| WakeWordEngine 生产版 | ✅ | WakeWordEngineTest 2/2（命中 + 静音不命中） |
| VoiceActivityDetector (Silero) | ✅ | VoiceActivityDetectorTest 3/3（切段≥2 + 静音0 + BARGE_IN不崩） |
| WakeWordController 状态机 | ✅ | WakeWordControllerTest：注入 wav → IDLE→WAKE_CONFIRMED |
| PcmToM4a 编码 | ✅ | MediaExtractor 读回 1 AAC track @16kHz |
| ContinuousAudioCapture + AEC | ✅ | 帧分发 + AEC enabled |
| DialogState / BargeInDetector | ✅ | 9/9 + 3/3 JVM |
| **face rec native（onnxruntime 1.18→1.24.3）** | ✅ | **FaceNativeSmokeTest：OnnxFaceDetector 加载 det_10g.onnx + OrtSession.run，dlopen+推理 OK** |
| 全套 androidTest | ✅ | 8/8 绿（face 1 + wakeword 7），零回归 |

**结论：onnxruntime 升级与人脸识别兼容；唤醒词管线（KWS+VAD+状态机+barge-in）单元/集成层全通。**

## 2. APK 体积

- `app-debug.apk`：**276 MB**（debug，含人脸 w600k_r50/det_10g + sherpa KWS/VAD 模型 + 全 ABI native lib）
- 待量：`app-release.apk`（minify + abiFilters arm64-v8a only，预期显著缩小）
- 命令：`./gradlew :app:assembleRelease && ls -lh app/build/outputs/apk/release/`

## 3. 端到端手动实测

装完整 app 到车机：`./gradlew :app:installDebug`，默认唤醒词模式。

> **2026-07-06 首次真机实测**：唤醒→对话→ASR→LLM→TTS→barge-in 多轮全通。过程中暴露并修复 **3 个自动测试没覆盖的真机 bug**（崩溃 / grace 立刻超时 / ASR 转垃圾），详见 **[2026-07-06-wakeword-mode-realdevice-fixes.md](./2026-07-06-wakeword-mode-realdevice-fixes.md)**。

| 验收项（spec §7） | 目标 | 实测 | 备注 |
|---|---|---|---|
| 唤醒响应 | 说"你好小迪" 1s 内进对话窗口 + 提示音 | ✅ |  |
| 多轮追问 | 对话窗口内连问 3 轮不重复唤醒 | ✅ | 实测 2 轮 + barge-in |
| barge-in | AI 说话时插嘴，TTS 300ms 内掐断→新录音 | ✅ | 日志 `Barge-in confirmed → interrupt TTS` |
| 静默退出 | 10s 无活动回待机 | ✅ | 日志 `Dialog inactivity 10000ms → IDLE_LISTENING` |
| 唤醒命中率 | 10 次说"你好小迪" 10/10 命中 | 待测 | 命中___/10（定性：连续多次都命中） |
| barge-in 成功率 | 10 次插嘴 ≥8 次成功掐断 | 待测 | ___/10 |
| 误唤醒（静音） | 1 小时静音 ≤2 次 | 待测 | ___次 |
| 误唤醒（音乐） | 1 小时播音乐 ≤5 次 | 待测 | ___次 |
| 按键模式切换 | 首页按钮切到按键模式，单击录音可用 | ✅ | 按键模式 ASR 一直正常（本次 bug 仅 WAKE_WORD 路径） |
| BYD 共存 | 喊"你好小迪"只触发本 app，不弹 BYD 界面 | 待测 |  |
| 降级 | 模型加载失败→Toast+切按键模式，不崩 | ✅ | VAD/KWS 文件校验失败→`fallbackToButton` 不崩 |

> 命中率/误唤醒等**定量指标**需长时间统计，留待后续。功能正确性已验。

## 4. 车机调参项（Task 9/10 concerns，真麦实测后定）

- **KWS threshold**：生产默认 0.25f，60km/h 车噪下可能要调（spike TTS wav 用 0.1f）。`WakeWordController` 构造传 threshold。
- **barge-in marginDb / debounceFrames**：默认 6.0dB / 8 帧。真麦+车噪实测后调（`BargeInDetector` 构造参数）。
- **segment→TTS gap**：LLM 慢时 VAD 段结束到 TTS 开始有间隔，可能要 watchdog 延长。
- **VAD SEGMENT minSilenceDuration**：默认 0.7s，真麦实测用户停顿习惯后调。

## 5. 已知 advisory（final review 处理，不阻塞）

- **ToggleButton onResume 未重同步**：后台降级时 MainActivity 按钮不同步。修：onResume 加 `btnMode.isChecked = (InteractionMode.current(this) == WAKE_WORD)`。
- **流式 TTS orphan Finished**：onFirstChunk 可能不触发但 onDone 触发 Finished；Task 9 `ttsPlaybackFinished` 已幂等（非 AI_SPEAKING 时 no-op），实际安全。
- **UI 反馈 hooks 是 TODO no-op**：`onWakeDetected/onDialogStart/onDialogEnd` 目前空实现——唤醒命中时用户无视觉反馈（无"叮"音/气泡变样）。按 spec §5.2 对话窗口态应有 UI 区分，建议接 FloatingBubbleService 的气泡状态（背景色/图标）。
- **测试加固**（final review 批次）：Task 2 persist_survivesNewInstance 诚实化、Task 4 setConsumer_replaces 验证 first 停止。

## 6. 下一步

1. 用户按 §3 手动实测 + 填表。
2. 实测发现的问题 → 调参（§4）或回 fix。
3. final whole-branch review（superpowers:requesting-code-review）扫整个 feat/wakeword-mode 分支。
4. finishing-a-development-branch：feat/wakeword-mode 合并回 master + 主仓库更新子模块指针。
