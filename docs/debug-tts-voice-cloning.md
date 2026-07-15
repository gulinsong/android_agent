# TTS 语音克隆 & QQ Bot 语音链路调试记录

**日期：** 2026-05-14
**现象：** QQ Bot 收到语音消息后，TTS 回复音色为默认男声，前端切换音色/方言均无效

---

## 问题一：TTS 语音回复不触发

### 现象
QQ Bot 文字回复正常，但没有语音（TTS）回复。

### 排查过程

1. **检查 OpenClaw TTS 配置**
   - `openclaw.json` 中 `messages.tts.auto` 原为 `"inbound"`（仅语音输入时才回复语音）
   - 改为 `"always"`（所有回复都生成语音）
   - `channels.qqbot.tts.auto` 同步改为 `"always"`

2. **检查 SOUL.md — LLM 返回 NO_REPLY**
   - SOUL.md 包含 "拒绝无意义闲聊" 指令
   - 导致 LLM 对日常对话返回 `NO_REPLY`，跳过回复
   - 修复：删除 "拒绝无意义闲聊"，添加 "有问必答，不要用 NO_REPLY 跳过用户的问题"

3. **media/outbound/ 权限问题（根本原因）**
   - 错误日志：`EACCES: permission denied, open '.../media/outbound/.voice-xxx---xxx.wav...tmp'`
   - `media/outbound/` 目录被 root 创建（drwx------），gateway 以 shell 用户运行无写入权限
   - 修复：
     ```bash
     adb root
     chown shell:shell /data/local/tmp/openclaw-home/.openclaw/media/outbound
     chmod 777 /data/local/tmp/openclaw-home/.openclaw/media/outbound
     chown shell:shell /data/local/tmp/openclaw-home/.openclaw/media/outbound/*
     adb unroot
     ```

### 结论
TTS 不触发的根本原因是 `media/outbound/` 目录权限问题。gateway 无法写入 TTS 生成的音频文件。

---

## 问题二：TTS 音色始终为男声，切换无效

### 现象
无论前端怎么切换音色（温柔女声/活泼女声等），TTS 输出始终是默认男声。切换方言也无效。

### 排查过程

1. **确认 adapter 端配置正确**
   - `voices.json` 中 default 预设指向 `voice_samples/sample_1.wav`（温柔女声）
   - 前端切换时 adapter 日志确认收到了更新请求

2. **检查 adapter → VoxCPM2 的调用链**
   ```
   adapter.py → load_ref_audio_latents() → POST /encode_latents → 404 Not Found!
   ```
   - adapter 调用 `http://localhost:8000/encode_latents` 返回 404
   - VoxCPM2 server（`voxcpm_server.py`）只暴露了 `/generate` 和 `/health` 两个端点
   - `/encode_latents` 端点**根本不存在**

3. **检查 VoxCPM2 server 源码**
   - `nanovllm_voxcpm` 底层库 `AsyncVoxCPM2ServerPool` **确实支持**：
     - `encode_latents(wav_bytes, wav_format)` — 编码参考音频
     - `generate(..., ref_audio_latents=bytes)` — 使用 latents 进行声音克隆
   - 但 `voxcpm_server.py`（FastAPI 包装层）**没有暴露这两个功能**：
     - 没有 `/encode_latents` 端点
     - `/generate` 端点只传递 `target_text`、`cfg_value`、`temperature`，**忽略了 `ref_audio_latents`**

4. **影响**
   - `load_ref_audio_latents()` 返回 `None` → latents 为空
   - `/generate` 不传递 latents → VoxCPM2 用默认音色（男声）生成
   - 所有 ref_audio 声音克隆完全失效

### 修复：`voxcpm_server.py`

**添加 `/encode_latents` 端点：**
```python
@app.post("/encode_latents")
async def encode_latents(request: Request):
    wav_bytes = await request.body()
    wav_format = request.query_params.get("wav_format", "wav")
    latents = await server.encode_latents(wav_bytes, wav_format)
    return StreamingResponse(iter([latents]), media_type="application/octet-stream")
```

**更新 `/generate` 端点传递 `ref_audio_latents`：**
```python
ref_audio_latents = None
raw_latents = body.get("ref_audio_latents")
if raw_latents:
    ref_audio_latents = bytes(raw_latents) if isinstance(raw_latents, list) else raw_latents

async for data in server.generate(
    target_text=text,
    cfg_value=cfg_value,
    temperature=temperature,
    ref_audio_latents=ref_audio_latents,  # 新增
):
```

### 修复后验证
```
adapter: Encoded ref audio: voice_samples/sample_1.wav -> 51200 bytes
voxcpm:  Encoded latents: 51200 bytes
voxcpm:  Generate: 26 chars, ref_latents=yes  ← 确认 latents 已传入
voxcpm:  Generated 4.8s audio in 2.19s (RTF=0.46)
```

### 结论
`voxcpm_server.py` 缺少 `/encode_latents` 端点，且 `/generate` 不传递 `ref_audio_latents`，导致声音克隆完全失效。这是所有音色切换无效的根本原因。

---

## 问题三：方言切换无效

### 现象
前端切换方言后，TTS 输出的语音没有方言效果。

### 分析
- adapter 的 `build_target_text()` 逻辑正确：`dialect_prefix = f"({dialect})"` + 拼接到文本前面
- 但因为问题二（声音克隆失效）， VoxCPM2 始终用默认音色生成，方言前缀的效果被掩盖
- 修复声音克隆后，方言前缀正常生效

### 验证
- SOUL.md 更新为 "请用上海话回复" → LLM 用上海话回复
- adapter 日志确认 `dialect` 字段正确传递
- TTS 生成时 `target_text = "(上海话)..."` 正确拼接

---

## 问题四：会话历史导致 LLM 持续 NO_REPLY

### 现象
更新 SOUL.md 后，LLM 仍然返回 `NO_REPLY`。

### 原因
- 旧会话历史（`.jsonl`）中积累了大量拒绝回答的上下文
- LLM 跟随历史模式继续拒绝
- 即使 SOUL.md 已更新，对话上下文中的旧行为占主导

### 修复
```bash
# 备份并清空会话历史
adb shell "cp sessions/xxx.jsonl sessions/xxx.jsonl.bak"
adb shell "echo '' > sessions/xxx.jsonl"
```

清空后，gateway 重新加载 SOUL.md，LLM 行为恢复正常。

---

## 完整修复清单

| 文件 | 修改 | 位置 |
|------|------|------|
| `voxcpm_server.py` | 添加 `/encode_latents` 端点 | tts-adapter/ |
| `voxcpm_server.py` | `/generate` 传递 `ref_audio_latents` | tts-adapter/ |
| `SOUL.md` | 删除 "拒绝闲聊"，添加 "有问必答" | 车机 workspace/ |
| `openclaw.json` | `tts.auto` 改为 `"always"` | 车机 .openclaw/ |
| `media/outbound/` | 修复目录权限 chown shell:shell | 车机 |

## 关键文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| TTS adapter | `tts-adapter/adapter.py` | OpenAI 兼容 TTS 代理 |
| 音色配置 | `tts-adapter/voices.json` | 音色预设（ref_audio） |
| 全局设置 | `tts-adapter/settings.json` | 方言、语气设置 |
| 参考音频 | `tts-adapter/voice_samples/sample_*.wav` | 预设声音克隆样本 |
| 自定义 ref | `tts-adapter/voice_samples/custom_ref.wav` | auto_ref 自动保存 |
| VoxCPM2 模型服务 | 开发机 `172.20.10.2:8000` | vLLM-Omni 部署 |

## 数据流（vLLM-Omni，2026-05-19）

```
用户 QQ 语音消息
  → STT (faster-whisper :8090) → 文字
  → LLM (GLM-4.7) → 回复文字
  → Gateway TTS 模块
    → POST /v1/audio/speech { input, voice } → adapter (:8091)
      → 查 voices.json → 获取 ref_audio 路径（预设音色）
      → 查 settings.json → 获取方言、语气
      → 拼接 input = "(prompt_text，tone，dialect)文本"
      → ref_audio base64 编码为 data URL
      → POST /v1/audio/speech { input, ref_audio, response_format=wav } → VoxCPM2 (:8000)
      → VoxCPM2 声音克隆 + 语气/方言控制 → 返回 WAV
    → adapter 返回 WAV → Gateway 保存到 media/outbound/
  → WAV → SILK (silk-wasm) → QQ Bot API 发送语音消息
```

---

## 问题五：官方 voxcpm 包声音克隆失效（已回退）

**日期：** 2026-05-18

### 现象

尝试从 nanovllm-voxcpm 切换到官方 `pip install voxcpm` 包，使用 `VoxCPM.from_pretrained()` + `model.generate(reference_wav_path=...)` 进行声音克隆。无论传入什么 ref_audio 或 prompt_text，输出的始终是同一个男声。

### 排查

1. 测试了 4 种组合：
   - ref_audio=female_sample, cfg=2.0 → 男声
   - ref_audio=female_sample, cfg=2.0, prompt_text="女声" → 男声
   - ref_audio=male_sample, cfg=2.0 → 同样的男声
   - 无 ref_audio, prompt_text="温柔女声" → 同样的男声

2. 对比 nanovllm-voxcpm：同样的参考音频，nanovllm-voxcpm 能正确克隆出对应音色。

3. 确认官方包的 `reference_wav_path` 参数没有正确传递到模型。

### 结论

官方 voxcpm 包（截至 2026-05-18）的 voice cloning 功能存在 bug，`reference_wav_path` 参数无效。已回退到 nanovllm-voxcpm。

---

## 问题六：App 选择预设音色后输出男声+杂音

**日期：** 2026-05-18

### 现象

App 选择"活泼女声"后，TTS 输出是男声且带有明显杂音。

### 排查

1. 检查 adapter 日志：发现 `prompt_text` 为空字符串，`cfg_value` 为 1.5。
2. 检查 PersonaFragment.kt：发现 `"prompt_text" to ""` 硬编码清空了 prompt_text。
3. 检查 FileHelper.kt：发现 `cfg_value` 设为 1.5（而非 VoxCPM2 推荐的 2.0）。

### 根因

PersonaFragment.kt 在切换预设音色时将 `prompt_text` 清空为 `""`，导致 VoxCPM2 没有风格引导；同时 FileHelper.kt 中 `cfg_value=1.5` 偏低，cfg=1.0 会导致模型卡死，1.5 虽能生成但音质差。

### 修复

1. **FileHelper.kt** — 所有预设 `cfg_value` 改为 `2.0`；VoicePreset 新增 `promptText` 字段，每个预设配对应提示词：
   - 0: "温柔女声，轻声细语"
   - 1: "活泼女声，明亮欢快，吐字清晰"
   - 2: "沉稳男声，低沉有力"
   - 3: "知性女声，清晰自然"
   - 4: "特朗普，英文口音中文"
   - 5: "林志玲，温柔甜美"
   - 6: "雷军，略带口音的男声"

2. **PersonaFragment.kt** — `"prompt_text" to ""` → `"prompt_text" to preset.promptText`

---

## 问题七：QQ Bot 语音回复内容为空白

**日期：** 2026-05-18

### 现象

Gateway 日志显示 TTS 生成成功、QQ API 返回 200 OK，但用户收到的是空白语音消息。

### 排查方向

1. QQ Bot SILK 编码问题
2. Gateway 发送音频时的格式转换
3. QQ Bot API 的音频上传接口对 WAV 格式的兼容性

### 状态

待进一步排查。

---

## TTS 架构重构（2026-05-19）

从 nanovllm-voxcpm（自定义 API）迁移到 vLLM-Omni（OpenAI 兼容 API），同时重构 adapter 为三维度独立控制。

### 三维度独立控制

| 维度 | 来源 | 存储 | API |
|------|------|------|-----|
| **音色** | 预设 ref_audio 或自定义 prompt_text→ref_audio | voices.json | `POST /v1/voices` |
| **方言** | App 设置 | settings.json | `POST /v1/tts-settings` |
| **语气** | App 设置 | settings.json | `POST /v1/tts-settings` |

### 音色三种场景

#### 1. 预设音色（有 ref_audio）

预设音色绑定了 ref_audio 文件，不需要 prompt_text。直接用 ref_audio 声音克隆。

```
请求: voice=gentle
拼接: input="文本"（无前缀）
ref:  voice_samples/sample_1.wav → base64 data URL
```

#### 2. 自定义音色首次（prompt_text，无 ref_audio）

用户手动输入音色描述（如"特朗普"），作为 prompt 传给 VoxCPM2。生成的音频自动保存为 ref_audio。

```
请求: voice=custom, prompt_text="特朗普，英文口音中文"
拼接: input="(特朗普，英文口音中文)文本"
ref:  无
auto_ref: 自动保存生成音频 → voice_samples/custom_ref.wav
```

#### 3. 自定义音色第二次起（ref_audio，无 prompt_text）

auto_ref 机制将首次生成的音频保存为 ref_audio，后续直接用 ref_audio 克隆，不再加 prompt 前缀。

```
请求: voice=custom
拼接: input="文本"（无前缀）
ref:  voice_samples/custom_ref.wav → base64 data URL
```

### 方言和语气（独立于音色）

方言和语气作为全局设置，通过 `POST /v1/tts-settings` 独立控制，与音色自由组合。

```
请求: voice=gentle, settings={ dialect: "上海话", tone: "悲伤的语气" }
拼接: input="(悲伤的语气，上海话)文本"
ref:  voice_samples/sample_1.wav
```

### input 拼接规则

```
parts = []
if preset.prompt_text:  parts.append(prompt_text)  # 仅自定义首次有值
if settings.tone:       parts.append(tone)
if settings.dialect:    parts.append(dialect)
if parts:
    input = f"({'，'.join(parts)}){text}"
else:
    input = text
```

### Adapter API 接口

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/v1/audio/speech` | TTS 合成（gateway 调用） |
| `POST` | `/v1/voices` | 更新音色预设（App 调用） |
| `GET` | `/v1/voices/{id}` | 查询音色预设 |
| `POST` | `/v1/tts-settings` | 更新方言/语气（App 调用） |
| `GET` | `/v1/tts-settings` | 查询当前设置 |
| `GET` | `/health` | 健康检查 |

### 与旧架构对比

| 项目 | 旧（nanovllm-voxcpm） | 新（vLLM-Omni） |
|------|----------------------|-----------------|
| VoxCPM2 API | `/encode_latents` + `/generate` | `/v1/audio/speech`（OpenAI 兼容） |
| 声音克隆 | latents 编码 → 传二进制 | ref_audio base64 data URL |
| 参数 | `cfg_value`, `temperature` | 不需要（模型内置） |
| 重采样 | 48kHz → 24kHz | 不需要（直接输出 48kHz WAV） |
| 依赖 | numpy, scipy, soundfile | 无额外依赖 |
| 方言 | 绑在 voice preset 里 | 独立全局设置 |
| 语气 | 无 | 独立全局设置 |

### voices.json 格式

```json
{
  "default": {
    "description": "活泼女声（默认）",
    "ref_audio": "voice_samples/sample_2.wav"
  },
  "gentle": {
    "description": "温柔女声，轻声细语",
    "ref_audio": "voice_samples/sample_1.wav"
  },
  "custom": {
    "description": "自定义音色",
    "prompt_text": "",
    "ref_audio": null,
    "auto_ref": true
  }
}
```

预设音色只有 `description` + `ref_audio`。自定义音色有 `prompt_text`（首次提示词）和 `auto_ref`（自动保存机制）。
