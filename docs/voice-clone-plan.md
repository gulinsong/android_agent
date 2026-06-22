# 说话人音色克隆功能

## 概述

在音色选择中增加"我的音色"选项。用户正常通过飞书语音跟车机对话，STT 端自动保存语音音频作为 TTS 参考音频（ref_audio），实现音色克隆。

**核心约束：**
- STT (8090)、TTS adapter (8091)、VoxCPM2 (8000) 都在同一台机器 (172.20.10.5)，可共享文件
- 只保留一条克隆音色，重新录制时覆盖
- 音频需 3 秒以上才保存
- **飞书语音格式是 OGG/Opus，不是 WAV** — STT 捕获时需要用 ffmpeg 转成 16kHz 16-bit 单声道 WAV

## 交互流程

### 首次使用
1. 用户在 app 点击"我的音色"
2. app 开启 STT 捕获 + 在音色列表下方显示提示区域
3. 提示区域显示固定朗读文本："你好，看下今天的天气，然后导航到最近的加油站"
4. 用户通过飞书发语音消息 → STT 保存音频到 `user_clone.wav` → 自动隐藏提示区域
5. 后续 TTS 回复使用克隆音色

### 再次选择
- 点击"我的音色"：直接激活已有克隆音色

### 重新录制（换人）
- 点击"我的音色"右侧的重录按钮 → 开启捕获，显示提示区域，下一次语音覆盖旧音色

## 技术实现

### Step 1: STT server 增加语音捕获

**修改：** `/home/tsm/work/stt/stt-server.py`

- 添加全局变量 `_clone_capture = False`
- 添加 `POST /v1/clone/capture` 端点：设置 `_clone_capture = True`
- 添加 `GET /v1/clone/status` 端点：返回 `{"capture_enabled": bool, "has_clone_audio": bool}`
- 在 `transcribe()` 中检查 `_clone_capture`：
  - gateway 发来的音频是 OGG/Opus 格式，需要先用 ffmpeg 转成 16kHz 16-bit 单声道 WAV
  - 转换后计算 WAV 时长（扫描 data chunk，不是固定偏移）
  - 时长 < 3 秒：不保存，日志 warn
  - 时长 >= 3 秒：写入 `/home/tsm/work/android_agent/tts-adapter/voice_samples/user_clone.wav`，自动关闭捕获

**踩坑记录：**
- gateway 发给 STT 的飞书语音是 OGG/Opus 格式（header: `OggS`），不是 WAV
- WAV 时长计算不能用固定偏移 40 读 data_size — 文件中可能有 LIST 等 extra chunk 导致 data 不在固定位置，需要扫描查找 `data` fourCC
- Python 进程有 `.pyc` 缓存，修改代码后必须清除 `__pycache__` 或用 `python -B` 运行

### Step 2: TTS adapter 增加 clone preset

**修改：** `/home/tsm/work/android_agent/tts-adapter/voices.json`

新增：
```json
"user_clone": {
  "description": "我的音色",
  "ref_audio": "voice_samples/user_clone.wav",
  "prompt_text": "",
  "auto_ref": false
}
```

### Step 3: TTS adapter 增加激活/状态端点

**修改：** `/home/tsm/work/android_agent/tts-adapter/adapter.py`

- `POST /v1/clone/activate`：检查 user_clone.wav 存在后更新 default voice 的 ref_audio，清除缓存
- `GET /v1/clone/status`：返回克隆音频是否存在及文件大小

### Step 4: TtsApiClient 增加克隆方法

**修改：** `app/src/main/java/com/openclaw/car/network/TtsApiClient.kt`

- `enableCloneCapture(): Boolean` — POST STT `/v1/clone/capture`（STT URL: `http://172.20.10.5:8090`）
- `activateCloneVoice(): Boolean` — POST TTS adapter `/v1/clone/activate`
- `getCloneStatus(): JSONObject?` — GET TTS adapter `/v1/clone/status`

### Step 5: VoicePresetAdapter 增加"我的音色"

**修改：** `app/src/main/java/com/openclaw/car/adapter/VoicePresetAdapter.kt`

- 在 3 个预设后追加 index=99 "我的音色"（用 `CLONE_INDEX = 99`）
- 右侧重录按钮 `btn_rerecord`（已有克隆音频时显示）
- `onCloneClicked` 和 `onRerecordClicked` 回调
- `hasCloneAudio` 属性控制重录按钮可见性

### Step 6: PersonaFragment 集成

**修改：** `app/src/main/java/com/openclaw/car/fragment/PersonaFragment.kt`

- 点击"我的音色"：
  - 已有音频 → 直接激活
  - 无音频 → 开启捕获 + 显示提示区域（固定朗读文本 + "语音需3秒以上"）
- 重录按钮 → 开启捕获覆盖 + 显示提示区域
- 捕获成功后自动隐藏提示区域（轮询 TTS adapter `/v1/clone/status`，每 3 秒一次）
- 提示区域是动态添加的 LinearLayout，在 RecyclerView 下方

### Step 7: PreferenceHelper

**修改：** `app/src/main/java/com/openclaw/car/util/PreferenceHelper.kt`

`voiceMode` 增加可选值 `"clone"`。

### Step 8: 同步逻辑

**修改：** `PersonaFragment.kt` 的 `syncVoiceToAdapter()`

增加 clone 分支：voiceMode == "clone" 时调用 `activateCloneVoice()`。

### 新增资源文件

- `res/drawable/ic_refresh.xml` — 重录按钮的刷新图标
- `res/layout/item_voice_preset.xml` — 增加 `btn_rerecord` ImageButton

## 关键文件

| 文件 | 改动 |
|------|------|
| `/home/tsm/work/stt/stt-server.py` | 捕获端点 + ffmpeg OGG→WAV 转换 + 保存克隆音频 |
| `/home/tsm/work/android_agent/tts-adapter/voices.json` | user_clone preset |
| `/home/tsm/work/android_agent/tts-adapter/adapter.py` | clone 激活/状态端点 |
| `network/TtsApiClient.kt` | clone HTTP 方法（STT + TTS adapter） |
| `adapter/VoicePresetAdapter.kt` | "我的音色"项 + 重录按钮 |
| `fragment/PersonaFragment.kt` | clone 流程 + 提示区域 + 轮询 |
| `res/drawable/ic_refresh.xml` | 重录图标 |

## 对现有功能的影响

- STT：仅在捕获标志开启时额外保存音频，不影响转录结果
- TTS adapter：新增独立 preset，不修改现有 lively/bright/deep 预设
- App：追加音色项，不影响原有 3 个预设的选择和使用
- 选回其他音色时走原有逻辑，完全不受影响
