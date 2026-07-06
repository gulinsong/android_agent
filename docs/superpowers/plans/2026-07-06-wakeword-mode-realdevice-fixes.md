# 唤醒词模式车机实测调试记录

- **日期**：2026-07-06
- **设备**：`LZBYDUMNB6RW7X5P`（BYD DiLink300 IVI，Android 14 / MediaTek）
- **起点**：自动验证全 PASS（见 `2026-07-06-wakeword-mode-acceptance.md`），首次装车真麦实测
- **结果**：端到端跑通（唤醒→对话→ASR→LLM→TTS→barge-in 多轮）。实测暴露并修复 **3 个真机 bug**（自动测试都没覆盖到）。

---

## 端到端实测结果（最终）

```
Wake word hit '你好小迪' → WAKE_CONFIRMED → DIALOG_RECORDING
ASR:  "今天天气怎么样？"                              ✅ 转对
LLM:  "今天深圳阴天，28°C，湿度84%…出门记得带伞…"      ✅
TTS:  合成播放                                        ✅
barge-in 打断 → 第二轮 "笑话吧。" → 正常回复          ✅
```

---

## Bug 1：点唤醒词开关就 native 崩溃

**现象**：默认 WAKE_WORD 模式，app 启动或切开关时整个进程被杀（无 Java 异常栈，`adb logcat` 只有 native SIGABRT）。

**tombstone abort message**：
```
Ort::Exception: Load model from .../cache/wakeword/silero_vad.onnx failed: Protobuf parsing failed.
```

**根因链**：
1. `FloatingBubbleService.initInteractionMode()` 调 `AssetUtil.copyAssetDirToCache(this, "wakeword/silero_vad.onnx")` —— 把**文件路径**当**目录**传。
2. `AssetUtil` 顶部 `outDir.mkdirs()` 把 `silero_vad.onnx` 建成了**空目录**。
3. sherpa `Vad(assetManager=null, config)` → ONNX Runtime 打开空目录读 0 字节 → protobuf 解析失败 → **native 抛 Ort::Exception → abort() → SIGABRT**。
4. `VoiceActivityDetector.init()` 的 Java `try/catch(Throwable)` **接不住**——abort 发生在 JNI 内部，控制流没回到 Java。

**为什么 SherpaOnnxSmokeTest 历史 PASS**：它只用 `kws/` 子目录、从不碰 `silero_vad.onnx`，VAD 这条路自动测试从没覆盖。

**修复**：
- **调用点**（`FloatingBubbleService`）：改成一次性解压 `wakeword` 父目录、派生两条路径（`kwsModelDir="$root/kws"`、`vadModelPath="$root/silero_vad.onnx"`），不再对文件单独调 copyAssetDirToCache。
- **`AssetUtil`**（防御 + 根治）：
  - 用 `assetMgr.open()` 探测文件 vs 目录（open 文件成功、目录抛 IOException），不再用 `list().isNotEmpty()` 判（`build.gradle` 里 `aaptOptions { noCompress("onnx") }` 让 onnx 无压缩，某些 Android 上 `list()` 对无压缩文件会误报非空）。
  - 幂等判定用 `outFile.isFile && length()>0`，**不是** `exists() && length()>0`——`File.length()` 对目录返回 inode 大小（往往 >0），`exists()` 会把残留空目录当有效文件跳过。
  - 防御：被误传文件路径时按单文件拷贝、不 mkdirs。
- **防 native crash**（`VoiceActivityDetector` / `WakeWordEngine`）：喂 native 前校验文件 `isFile && length()>0`，坏文件优雅返回 false 而非杀进程。
- **回归测试**：`AssetUtilTest` 3 用例（解压成文件 / 替换 stale 目录 / 接受文件路径入参）。

---

## Bug 2：唤醒后立刻结束（grace 超时）

**现象**：说"你好小迪"，提示音响一下，立刻回 IDLE，没机会说指令。日志反复 `Grace expired without speech → IDLE_LISTENING`。

**根因**：grace 窗口（1.5s）靠 `onSpeechStart` 回调刷新 `lastActivityAt` 续命，而 `onSpeechStart` 是在 `drain()` 里 `v.front()` 取到**完整段**才触发的——**段完成**需要 speech + 0.7s 静音。用户持续说话时段永远完不成，1.5s grace 必然超时。提示音又吃掉 ~1s，所剩无几。

**诊断证据**（加临时 feed tick 日志）：
```
frames=20 detected=false   ← 提示音中（AEC 工作正常，没误检）
frames=40 detected=true    ← VAD 在 grace 窗口内检到了用户语音 onset！
```
说明 VAD **检到了语音**，只是 grace 用错了信号（用段完成而非 onset）。

**修复**（`WakeWordController.onWakeHit`）：VAD_SEG consumer 里，`WAKE_CONFIRMED` 期间用 `isSpeechDetected()`（onset 级）每帧刷新 `lastActivityAt`，而不是等 `onSpeechStart`（段完成）。和 BARGE_IN 模式每帧查 `isSpeechDetected()` 的思路一致。用户停顿后段完成 → `onSegmentEnd` → `enterDialogRecording`，此时状态已切走，grace runnable 自然作废。

---

## Bug 3：ASR 全转垃圾（"没。"+ 判成葡萄牙语）

**现象**：进入对话后，说"今天天气怎么样"，ASR 返回 `{"text":"没。","dialect":"pt"}`，LLM 用葡萄牙语回。

**诊断（逐步隔离）**：
1. **按键模式 ASR 正常** → FunASR 服务（8090，SenseVoice+Paraformer）没坏，问题在唤醒路径音频。
2. **干净中文 fixture 直喂 ASR** → `ni_hao_xiao_di.wav` 转出 `"你好，小迪。😊"` ✅ → 进一步确认 ASR 没坏。
3. **dump 喂给 ASR 的 m4a** → ZCR 46.7%、相邻样本自相关 r(1)=0.012 → **宽带噪声**。
4. dump 原始麦克输入 → 一开始也"像"噪声，**但发现是自己 dump 的 ByteBuffer 字节序反了**（默认大端，PCM 是小端）。按大端重解：r(1)=0.967 → **干净语音**。KWS 能识别也佐证输入是干净的。
5. dump sherpa 段输出 pcm（修正字节序）→ r(1)=0.947 → **也是干净语音**。
6. 锁定 **PcmToM4a**：同一段干净 pcm，ffmpeg 编 → ASR 转出 `"今天天气怎么样？"` ✅；app 的 PcmToM4a 编 → 噪声 ❌。

**根因**：`PcmToM4a.kt` 的 `ByteBuffer.allocate(frameBytes)` **默认大端**，`asShortBuffer().put(pcm)` 按**大端**写 short，但 Android PCM 标准是**小端** → 字节对调 → AAC 编码器吃到乱序样本 → 输出宽带噪声 → SenseVoice 多语种 LID 在噪声上乱判（pt/gn）。

**修复**（一行）：`ByteBuffer.allocate(frameBytes).order(java.nio.ByteOrder.LITTLE_ENDIAN)`。

> 自相关 r(1) 是判语音/噪声的利器：语音相邻样本高度相关（>0.5，平滑波形），噪声 ~0（随机）。字节对调会让 r(1) 从 0.95 掉到 0.01，特征非常明显。

---

## 🔑 核心教训：音频管线的字节序陷阱

**Java `ByteBuffer`/`ShortBuffer` 默认大端，Android PCM 全是小端。** 凡是 `ShortArray`/`short[]` ↔ `ByteBuffer`/文件/`MediaCodec` 互转，**必须显式 `.order(ByteOrder.LITTLE_ENDIAN)`**，否则字节对调会产生：
- 幅度包络保留（功率起伏看起来像语音），
- 但相邻样本不相关（r(1)≈0，内容是噪声），

极易误判为"采集坏了"或"模型坏了"。**本次 `PcmToM4a` 的 bug 和我自己的诊断 dump 都犯了同样的错**，一度把方向带偏到 sherpa/采集。

**调试音频的方法论**（按顺序，逐步隔离）：
1. 对照测试：已知能工作的路径（按键模式）+ 干净 fixture 直喂 ASR → 先证明 ASR 服务没问题。
2. 多节点 dump：喂入（mic 输入）→ 中间（VAD 段）→ 输出（编码后 m4a），二分定位腐败点。
3. 客观判定语音/噪声：ZCR（语音 5-20%、白噪 >40%）+ 相邻样本自相关 r(1)（语音 >0.5、噪声 ~0）+ 频谱图（formant 条纹 vs 全频段均匀）。不要只看波形起伏。
4. curl 直接喂 ASR：隔离 app 发送链（headers/endpoint）。
5. 同源对照编码：同一段 pcm 用 ffmpeg 编 vs app 编，分别喂 ASR。

---

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `wakeword/PcmToM4a.kt` | ByteBuffer 加 `LITTLE_ENDIAN`（Bug 3） |
| `wakeword/WakeWordController.kt` | grace 用 `isSpeechDetected()` onset 续命（Bug 2） |
| `wakeword/AssetUtil.kt` | `open()` 判文件/目录 + `isFile` 幂等 + 文件路径防御（Bug 1） |
| `wakeword/VoiceActivityDetector.kt` | 喂 native 前文件校验防 SIGABRT（Bug 1 防御） |
| `wakeword/WakeWordEngine.kt` | 喂 native 前逐文件校验（Bug 1 防御） |
| `service/FloatingBubbleService.kt` | copyAssetDirToCache 调用点改解压父目录（Bug 1） |
| `androidTest/.../AssetUtilTest.kt` | 新增 3 用例回归（Bug 1） |

> 未提交。`agent_front_app` 是 submodule，提交后主仓需 bump 指针。

---

## 备注

- **FunASR 而非 FireRedASR**：8090 跑 `~/work/stt/stt-server.py`，模型 `sensevoice`（多语种，自动 LID）+ `paraformer`（中文）。响应里 `dialect` 字段 + `[系统检测到用户说的是XX，请用XX回复]` 注入是 stt-server 包装层基于 SenseVoice LID 加的。`memory/firered-lid.md` 是另一个实验，不是生产 ASR。
- **重装换 uid 坑**：`connectedDebugAndroidTest` / `adb uninstall+install` 会换 app uid（`adb install -r` 不换），导致 openclaw-home uid 错配、gateway 起不来。boot script 已动态 chown，开机自修；开发中途手动 chown 或重启。详见 `memory/openclaw-file-permissions.md`。
