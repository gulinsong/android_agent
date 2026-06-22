# 车载助手 Debug 文档

记录部署和运维过程中遇到的问题及解决方案。

---

## 1. Context limit exceeded

**现象：** 飞书发消息后收到 `⚠️ Context limit exceeded. I've reset our conversation to start fresh`

**原因：** `openclaw.json` 缺少 `compaction` 配置，对话上下文超出模型 token 限制时直接报错重置，而不是提前压缩。

**解决：** 在 `agents.defaults` 中添加 compaction 配置：

```json
"compaction": {
  "reserveTokensFloor": 20000
}
```

如果对话量大（频繁调试），可调高到 30000-40000。

---

## 2. 新版 OpenClaw (2026.5.7) 依赖缺失

**现象：** 启动报 `ERR_MODULE_NOT_FOUND: Cannot find package 'json5'` 等错误

**原因：** 新版 OpenClaw npm 包不再内置所有依赖，需要 `npm install --omit=dev --ignore-scripts` 安装全部 production 依赖，然后推送到车机。

**解决：**

```bash
# 开发机上
mkdir full-deps && cd full-deps
cp <openclaw package>/package.json .
npm install --omit=dev --ignore-scripts
tar czf openclaw-full-deps.tgz node_modules/

# 推送到车机
adb push openclaw-full-deps.tgz /data/local/tmp/
adb shell "cd /data/local/tmp/openclaw/lib/node_modules/openclaw && tar xzf /data/local/tmp/openclaw-full-deps.tgz"
```

---

## 3. 飞书插件独立为 npm 包

**现象：** 新版 OpenClaw `dist/extensions/` 目录没有 `feishu` 插件

**原因：** 2026.5.7 版本飞书通道从内置变为独立 npm 包 `@openclaw/feishu`

**版本匹配：** 插件版本必须与 openclaw 版本一致，否则会报 API 不兼容错误（如 `does not provide an export named 'resolveSessionFilePath'`）。

**解决：**

```bash
# 开发机安装（注意版本号要与车机 openclaw 版本一致）
mkdir -p /tmp/feishu-plugin && cd /tmp/feishu-plugin && npm init -y
npm install @openclaw/feishu@2026.5.18   # 与车机 openclaw 版本对应

# 推送插件到 extensions 目录（需包含其所有依赖）
adb push /tmp/feishu-plugin/node_modules/@openclaw/feishu/ /data/local/tmp/openclaw/lib/node_modules/openclaw/dist/extensions/feishu/

# 推送顶层依赖（feishu 插件的传递依赖不在插件自身 node_modules 内）
# 比较 node_modules/ 和 node_modules/@openclaw/feishu/node_modules/ 的差异
for pkg in asynckit axios ... ; do
  adb push /tmp/feishu-plugin/node_modules/$pkg /data/local/tmp/openclaw/lib/node_modules/openclaw/dist/extensions/feishu/node_modules/$pkg
done
# @larksuiteoapi/node-sdk 是必需的飞书 SDK
adb push /tmp/feishu-plugin/node_modules/@larksuiteoapi /data/local/tmp/openclaw/lib/node_modules/openclaw/dist/extensions/feishu/node_modules/@larksuiteoapi

# 修复权限（openclaw 以 u10_a150 用户运行）
adb shell "su -c 'chown -R u10_a150:u10_a150 /data/local/tmp/openclaw/lib/node_modules/openclaw/dist/extensions/feishu/'"

# 重启 gateway
adb shell "su -c 'am force-stop com.openclaw.car'" && sleep 3 && adb shell "su -c 'am start-activity com.openclaw.car/.MainActivity'"
```

QQ bot 同理：`npm install @openclaw/qqbot`

---

## 4. zai 插件指向智谱云端 API

**现象：** 飞书消息收到后报 `401 token expired or incorrect`

**原因：** zai 插件的 base URL 硬编码为智谱云端 (`https://open.bigmodel.cn/api/paas/v4`)，需要改为局域网 llama.cpp 地址 (`http://172.20.10.5:8080/v1`)。

**涉及文件（需全部修改）：**
- `dist/model-definitions-DgzI8W0b.js`
- `dist/provider-zai-endpoint-KYlI05LE.js`

**解决：**

```bash
adb shell "sed -i 's|https://api.z.ai/api/coding/paas/v4|http://172.20.10.5:8080/v1|g; s|https://open.bigmodel.cn/api/coding/paas/v4|http://172.20.10.5:8080/v1|g; s|https://api.z.ai/api/paas/v4|http://172.20.10.5:8080/v1|g; s|https://open.bigmodel.cn/api/paas/v4|http://172.20.10.5:8080/v1|g' <文件路径>"
```

**注意：** 文件名含 hash，每次升级 OpenClaw 后文件名可能变化，需要重新查找和修改。

---

## 5. agents/main/agent/models.json 覆盖主配置

**现象：** 修改了 zai 插件源码的 base URL，但请求仍然打向云端

**原因：** `~/.openclaw/agents/main/agent/models.json` 中的 `providers.zai.baseUrl` 覆盖了插件内部的 URL 定义

**解决：** 修改 `models.json` 中的 baseUrl：

```json
{
  "providers": {
    "openai": {
      "baseUrl": "http://172.20.10.5:8080/v1",
      "apiKey": "lmstudio-local",
      "models": [
        {"id": "glm-4.7", "name": "glm-4.7", "api": "openai-completions"},
        {"id": "MiniCPM-o-4_5-Q4_K_M.gguf", "name": "MiniCPM-o-4.5 Q4", "api": "openai-completions"}
      ]
    }
  }
}
```

**推荐：** 使用 `openai` provider 替代 `zai`，直接配置 OpenAI 兼容 API，避免智谱认证逻辑干扰。

---

## 6. 新版 OpenClaw 需要 auth-profiles.json

**现象：** 报 `No API key found for provider "openai". Auth store: auth-profiles.json`

**原因：** 新版 OpenClaw (2026.5.x) 不再从 `models.json` 的 `apiKey` 字段或环境变量直接读取 API key，而是需要显式的 auth profile 文件。

**解决：** 创建 `agents/main/agent/auth-profiles.json`：

```json
{
  "profiles": {
    "openai:default": {
      "provider": "openai",
      "mode": "api_key",
      "apiKey": "lmstudio-local"
    }
  }
}
```

---

## 7. 飞书配对 (Pairing)

**现象：** 首次在飞书发消息收到 `access not configured` 和 pairing code

**解决：**

```bash
adb shell "export HOME=/data/local/tmp/openclaw-home && ... && openclaw.mjs pairing approve feishu <CODE>"
```

配对后配置文件会自动写入 `commands.ownerAllowFrom`。

---

## 8. Context overflow — prompt too large

**现象：** 报 `400 request (19347 tokens) exceeds the available context size (4096 tokens)`

**原因：** llama.cpp 默认 context size 为 4096，MiniCPM-o-4.5 支持最大 40960。请求包含系统提示 + 多轮对话历史，轻松超过 4096。

**解决：**

1. llama.cpp 启动时加大 context：
```bash
./llama-server -m MiniCPM-o-4_5-Q4_K_M.gguf --host 0.0.0.0 --port 8080 -c 16384 -np 4
```

2. OpenClaw compaction 配置与 context size 配合：
```json
"compaction": {
  "reserveTokensFloor": 4000
}
```
建议 `reserveTokensFloor` 设为 context size 的 25% 左右。

3. 如果 session 里积累了脏数据（如多次错误），清除 session 文件：
```bash
adb shell "rm /data/local/tmp/openclaw-home/.openclaw/agents/main/sessions/*.jsonl"
```

**Context size 选择参考：**

| Context | 适用场景 | 显存占用 |
|---------|---------|---------|
| 4096 | 单轮问答 | 最低 |
| 8192 | 短对话 | 低 |
| 16384 | 多轮对话 + skill | 中 |
| 32768 | 长对话 | 较高 |
| 40960 | 模型上限 | 高 |

---

## 9. MiniCPM Q4 处理不了 OpenClaw 系统提示

**现象：** MiniCPM-o-4.5 Q4_K_M 返回乱码/幻觉内容（重复 JSON 片段、不完整输出）

**原因：** OpenClaw 内置系统提示（6 个插件的工具定义 + agent 配置）约 15-19k tokens，MiniCPM Q4 量化模型处理复杂 agent 格式能力不足

**解决：** 使用云端 GLM-4.7 API 替代本地 MiniCPM

---

## 10. 模型配置方法备份

### 方案 A：云端 GLM-4.7（当前使用）

**openclaw.json：**
```json
{
  "env": {
    "ZAI_API_KEY": "<智谱 API Key>"
  },
  "agents": {
    "defaults": {
      "model": { "primary": "zai/glm-4.7" },
      "models": { "zai/glm-4.7": {} },
      "compaction": { "reserveTokensFloor": 4000 }
    }
  }
}
```

**agents/main/agent/models.json：**
```json
{
  "providers": {
    "zai": {
      "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
      "apiKey": "<智谱 API Key>",
      "models": [{"id": "glm-4.7", "name": "glm-4.7"}]
    }
  }
}
```

**agents/main/agent/auth-profiles.json：**
```json
{
  "profiles": {
    "zai:default": {
      "provider": "zai",
      "mode": "api_key",
      "apiKey": "<智谱 API Key>"
    }
  }
}
```

### 方案 B：本地 MiniCPM (llama.cpp)

需要同时修改：
1. zai 插件源码中的 base URL → `http://172.20.10.5:8080/v1`
2. `models.json` 的 `baseUrl` → `http://172.20.10.5:8080/v1`
3. `openclaw.json` 的 `primary` → `openai/glm-4.7`
4. `auth-profiles.json` 的 provider → `openai`，apiKey → `lmstudio-local`
5. 精简 workspace 文件减少系统提示 token 数
6. llama.cpp context 至少 32768

**注意：** 本地 MiniCPM Q4 质量不足以处理 OpenClaw 的复杂 agent 系统提示，建议优先用方案 A。

---

---

## 11. GLM-4.7 不调用 bash 工具

**现象：** GLM-4.7 只回复文字说明（如"正在为您导航"），但不实际调用 bash 工具执行车机命令

**原因：** GLM-4.7 的 function calling 能力与 OpenClaw 的工具定义格式可能不完全兼容，模型倾向于直接文字回复而非 tool_use

**结论：** GLM-4.7 确实在调用工具（确认通过 session 日志），但使用的是错误命令。

---

## 12. GLM-4.7 不遵循 SKILL.md 多步骤导航指令

**现象：** SKILL.md 明确禁止高德地图命令，要求用 AccessibilityService 多步操作 BYD 地图，但 GLM-4.7 仍然：
- 使用 `am broadcast -a com.autonavi.minimap.action.NAVI`（高德地图 intent）
- 或自行探索系统、编造不存在的命令（如 `com.byd.automap.NAVIGATE_TO`）
- 完全不遵循 SKILL.md 的 7 步导航流程

**原因：** GLM-4.7 的指令遵循能力不足，尤其对多步骤复杂指令。它会优先使用训练数据中的"常见做法"（如高德地图 intent），而不是遵循 SKILL.md 的具体步骤。

**解决：** 将多步导航操作封装为 shell 脚本，让 LLM 只需调用简单的一两个命令：

1. **`/data/local/tmp/nav-search.sh "目的地"`** — 自动执行打开地图、点击搜索、输入目的地、提交、读取结果
2. **`/data/local/tmp/nav-select.sh <1|2|3>`** — 选择搜索结果并开始导航

SKILL.md 简化为只包含这两个命令，降低 LLM 犯错概率。

**关键文件：**
- `nav-search.sh` — 搜索脚本（车机 `/data/local/tmp/nav-search.sh`）
- `nav-select.sh` — 选择脚本（车机 `/data/local/tmp/nav-select.sh`）
- `SKILL.md` — 简化后的导航指令

---

## 13. SKILL.md 未被加载到 LLM system prompt

**现象：** 在 SKILL.md 中写了导航命令，但 GLM-4.7 完全不使用，甚至尝试打开 Google Maps 浏览器。

**排查过程：** 通过分析 session trajectory 文件，发现 `<available_skills>` 列表中只有内置插件 skills（browser-automation, feishu-doc 等），**workspace 目录下的 SKILL.md 没有被注册为 skill**，LLM 根本不知道它的存在。

**原因：** OpenClaw 的 skill 系统有两种：
1. **插件 skills** — 安装在 `~/.openclaw/plugin-skills/*/SKILL.md` 或内置 `skills/*/SKILL.md`，会自动出现在 `<available_skills>` 列表中
2. **workspace SKILL.md** — 放在 workspace 目录，需要模型主动 `read` 加载，但 LLM 不知道它的路径

workspace 的 IDENTITY.md 会被直接注入到 system prompt 的 "Project Context" 部分，但 SKILL.md 不会自动注入。

**解决：** 将所有关键指令直接写入 IDENTITY.md（确保注入 system prompt），不再依赖 SKILL.md 的 skill 注册机制。

**经验：**
- **workspace 文件加载顺序：** IDENTITY.md ✅ 自动注入 → SOUL.md → USER.md → AGENTS.md → SKILL.md ❌ 不自动注入
- **给 LLM 的指令应该放在 IDENTITY.md 中**，这是最可靠的方式
- **SKILL.md 适合存放可选的、按需加载的技能**，不适合放核心必执行的规则

---

## 14. 导航功能最终解决方案（成功）

**完整链路验证通过：** 飞书 "导航到大梅沙" → 搜索结果为空 → GLM 自动扩展为 "大梅沙海滨公园" → 展示3个选项 → 用户选2 → 导航启动

**解决方案要点：**

1. **封装复杂操作为 shell 脚本** — `nav-search.sh` 和 `nav-select.sh`，LLM 只需调用简单命令
2. **指令写入 IDENTITY.md** — 确保注入 system prompt，不依赖 SKILL.md 注册
3. **GLM-4.7 能力边界：**
   - ✅ 能遵循简单的"调用脚本"指令
   - ✅ 能根据搜索结果为空自动扩展关键词重试
   - ✅ 能展示选项并等待用户选择
   - ❌ 不能遵循多步骤 bash 命令序列
   - ❌ 不能自己编造正确的 Android intent 命令
   - ❌ 会被训练数据中的"常见做法"干扰（如高德地图 intent）

**架构模式：复杂操作 → shell 脚本 → 简单命令 → IDENTITY.md 注入**

---

## 15. 飞书回复延迟分析

**现象：** 飞书发消息后，车机很快有反应（地图打开），但飞书收到回复很慢，约 25 秒。

**链路延迟拆解：**

| 阶段 | 耗时 | 说明 |
|------|------|------|
| GLM 第一次推理 | ~10s | 理解意图 + 生成 tool_call 命令 |
| nav-search.sh 执行 | ~9s | 打开地图 + waitFor UI + 搜索 + 读取结果 |
| GLM 第二次推理 | ~3s | 解析结果 + 生成回复文字 |
| 网络往返 + OpenClaw 内部 | ~3s | 飞书 WebSocket → Gateway → Agent → 回复 |
| **总计** | **~25s** | |

**瓶颈：** GLM-4.7 云端 API 响应时间（两次推理共 ~13s），这是云端延迟，本地无法优化。nav-search.sh 的 9s 是车机 UI 操作的等待时间（AccessibilityService waitFor），属必要开销。

---

## 16. QQ Bot 语音链路部署计划

### 架构

```
QQ 用户 (语音消息 SILK)
  → QQ Bot API (api.sgroup.qq.com)
  → 车机 OpenClaw Gateway (:18801) qqbot 插件
  → STT (开发机 :8090) faster-whisper-server
  → LLM (GLM-4.7 云端)
  → TTS (开发机 :8091) openai-edge-tts
  → SILK 编码 → QQ 语音消息回复
```

### 部署步骤

| 步骤 | 说明 | 状态 |
|------|------|------|
| 1 | 部署 STT：faster-whisper-server (开发机 :8090, large-v3, ~3GB 显存) | 待部署 |
| 2 | 部署 TTS：openai-edge-tts (开发机 :8091, 兼容 OpenAI /v1/audio/speech) | 待部署 |
| 3 | 安装 QQ Bot 插件：`npm install @openclaw/qqbot@2026.5.7`，推送到车机 `dist/extensions/qqbot/` | 待部署 |
| 4 | 配置 openclaw.json：qqbot channel + stt + talk TTS | 待部署 |
| 5 | 重启 Gateway，测试文字 → 语音 STT → TTS 语音回复 | 待测试 |

### QQ Bot 插件依赖

`@openclaw/qqbot@2026.5.7` 需要以下 npm 包（车机无 npm，需预装）：
- @tencent-connect/qqbot-connector ^1.1.0
- silk-wasm ^3.7.1
- mpg123-decoder ^1.0.3
- ws ^8.20.0
- zod ^4.4.3

### 显存占用

| 服务 | 显存 |
|------|------|
| faster-whisper-large-v3 (STT) | ~3 GB |
| edge-tts (TTS) | 0（调用微软 Edge API，不需要 GPU） |
| llama.cpp MiniCPM Q4 (如果跑本地 LLM) | ~3 GB |

RTX 5000 16GB 足够同时运行。

### TTS 方案对比

| 方案 | 延迟 | 音质 | 显存 | 稳定性 | 备注 |
|------|------|------|------|--------|------|
| edge-tts (当前选择) | 0.5-1s | 高 | 0 | ✅ 稳定 | 318+ 音色，免费 |
| MiniCPM-o TTS (未来) | 1-2s | 中 | 共享 ~6GB | ⚠️ 不稳定 | 需 llama.cpp-omni fork，主线未合并 |
| CosyVoice | 1-2s | 高 | ~4GB | ✅ 稳定 | 需额外 GPU |

**决策：** 先用 edge-tts 打通全流程，等 llama.cpp 主线合并 omni 支持后再考虑 MiniCPM 直接出语音。

### openclaw.json 待添加配置

```json
{
  "channels": {
    "qqbot": {
      "enabled": true,
      "appId": "<QQ_APP_ID>",
      "clientSecret": "<QQ_CLIENT_SECRET>",
      "stt": {
        "enabled": true,
        "provider": "openai",
        "baseUrl": "http://172.20.10.5:8090/v1",
        "apiKey": "not-needed",
        "model": "Systran/faster-whisper-large-v3"
      }
    }
  },
  "talk": {
    "provider": "openai",
    "providers": {
      "openai": {
        "apiKey": "not-needed",
        "baseUrl": "http://172.20.10.5:8091/v1",
        "voiceId": "zh-CN-XiaoxiaoNeural"
      }
    }
  }
}
```

---

## 17. QQ Bot TTS 语音回复不触发

**现象：** QQ 发语音消息，bot 只回复文字，不回复语音。`onMessageSent` 日志显示 `ttsText=undefined`。

**根因（三个叠加问题）：**

### 17.1 session store 的 `ttsAuto` 覆盖了 config

**现象：** `openclaw.json` 配了 `channels.qqbot.tts.auto: "always"`，但 TTS 仍然不触发。

**原因：** `sessions.json` 中有 `"ttsAuto": "inbound"` 字段，TTS auto mode 的优先级是：

```
session store ttsAuto > preferences file > config channels.qqbot.tts.auto
```

session store 的值会覆盖 config 中的设置。

**解决：** 删除 `sessions.json` 中的 `ttsAuto` 字段：

```bash
adb shell "cat .../sessions/sessions.json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
key = 'agent:main:main'
if key in data and 'ttsAuto' in data[key]:
    del data[key]['ttsAuto']
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" > /tmp/sessions_fixed.json
adb push /tmp/sessions_fixed.json .../sessions/sessions.json
```

### 17.2 TTS config 结构要求 provider 引用 providers 表

**原因：** `channels.qqbot.tts.provider` 必须引用 `talk.providers` 中的 key，不能内联配置。

**正确的 TTS 配置：**

```json
{
  "channels": {
    "qqbot": {
      "tts": {
        "provider": "openai",
        "voice": "zh-CN-XiaoxiaoNeural",
        "auto": "inbound"
      }
    }
  },
  "talk": {
    "provider": "openai",
    "providers": {
      "openai": {
        "apiKey": "not-needed",
        "baseUrl": "http://172.20.10.5:8091/v1",
        "voiceId": "zh-CN-XiaoxiaoNeural"
      }
    }
  }
}
```

`channels.qqbot.tts.provider: "openai"` 引用 `talk.providers.openai` 的连接信息。

### 17.3 回复文字少于 10 字符被跳过

**原因：** TTS 框架硬编码了 10 字符最低阈值（`tts-config-BGh3U9k2.js` + `speech-core/runtime-api.js`）：

```javascript
if (!explicitTtsText && ttsText.trim().length < 10) return nextPayload;
```

agent 回复"正在播放音乐。"只有 7 个字符，低于阈值直接跳过。

**解决：** IDENTITY.md 中要求回复至少 10 个字：

```
- 回复简短自然（至少10个字），适合语音播报
```

---

## 18. QQ Bot 语音回复延迟分析

**现象：** 发"你好"到收到回复需要 ~79 秒。

**延迟拆解（2026-05-12 测试）：**

| 阶段 | 耗时 | 说明 |
|------|------|------|
| 消息到达 → 插件加载+调度 | 2s | plugin loading, dispatch setup |
| **GLM-4.7 LLM 调用** | **77s** | 云端 API 延迟，占 97% |
| 发送回复 | 1s | 文字/语音发送 |
| **总计** | **~80s** | |

**TTS 成功时的额外延迟：**

| 阶段 | 耗时 |
|------|------|
| TTS 生成音频 (edge-tts) | ~1s |
| SILK 编码 | ~1s |
| 上传到 QQ | ~1s |

**瓶颈：** GLM-4.7 云端 API（77s/79s），本地处理只需 3s。

**优化方向：**
1. **换更快的模型** — GLM-4-Flash 等快速模型
2. **减少上下文** — 当前 48 条历史消息（5456 字符），清理 session 减少 token
3. **本地模型** — MiniCPM 跑本地消除网络延迟（但 Q4 质量不够处理 agent 系统提示）

---

## 19. QQ Bot 网络断开后 Gateway 未自动重连

**现象：** 车机外网断开一段时间后恢复，但 QQ Bot 和飞书通道都没有自动重连成功，Gateway 进程存活但服务不可用。

**原因分析：**

QQ Bot WebSocket 重连机制（`sender-p-B14eLG.js` + `gateway-Cs3-_on9.js`）：

1. WebSocket 断连 → `handleClose(code)` → `scheduleReconnect()`
2. 重连需先调 `getAccessToken()` 拿 token（需外网）
3. 网络不通时 fetch 超时（10s）→ 抛异常 → `scheduleReconnect()` 退避重试
4. 指数退避：1s → 2s → 5s → 10s → 30s → 60s（最大），每轮还要加 10s fetch 超时
5. 最大退避后每约 70 秒一轮（60s 退避 + 10s 超时）
6. Token refresh loop 同理：`retryDelayMs = 5000`，无指数退避，无最大次数

关键问题：退避到 60s 后，网络恢复需要等最多 70 秒才能重连。日志中最后一次错误 08:45:15 到手动重启 08:47 之间可能还没到下一轮重试窗口。

**解决：** 手动重启 gateway。这是 OpenClaw 内置行为，非 bug，可通过以下方式改善：
- 监控 gateway 日志，网络恢复后如未自动重连则重启
- 或部署看门狗脚本定时检测并重启

**相关代码：**
- `sender-p-B14eLG.js:1216` — Token background refresh loop
- `gateway-Cs3-_on9.js:1040` — `RECONNECT_DELAYS` 退避表
- `gateway-Cs3-_on9.js:1609` — `ReconnectState` 重连状态机
- `gateway-Cs3-_on9.js:1840` — `GatewayConnection.connect()` 含 token 刷新 + WebSocket 连接

---

## 20. 本地 MiniCPM 模型无法处理 OpenClaw Agent System Prompt

**现象：** 切换到本地 llama.cpp 运行 MiniCPM-o-4.5 Q4 后，model_call 卡住 144+ 秒无输出。

**原因：** OpenClaw agent 的 system prompt 约 15k+ tokens（含 28 个工具定义、14 个 skill 描述、SOUL.md、IDENTITY.md），MiniCPM Q4 (8B) 在 RTX 5000 上 prefill 阶段极慢，无法在合理时间内完成推理。

**LLM 配置切换流程：**

| 文件 | 云端 GLM-4.7 | 本地 MiniCPM |
|------|-------------|-------------|
| `agents/main/agent/models.json` | `baseUrl: "https://open.bigmodel.cn/api/paas/v4"` | `baseUrl: "http://172.20.10.5:8080/v1"` |
| `agents/main/agent/auth-profiles.json` | zhipu.ai API key | `lmstudio-local` |
| `openclaw.json` agents.defaults.model.primary | `zai/glm-4.7` | `zai/MiniCPM-o-4_5-Q4_K_M.gguf` |

**结论：** 8B 级本地模型不适合跑完整 OpenClaw agent prompt，需云端大模型或更大参数本地模型。

---

## 21. Log Proxy 不支持流式转发导致请求卡住

**现象：** `log_proxy.py`（8080 端口，转发到 llama.cpp 18080）处理 OpenClaw 的 streaming LLM 请求时卡住。

**原因：** 原 proxy 使用 `resp.read()` 读取完整响应后才转发，但 OpenClaw 使用 SSE 流式调用 LLM，proxy 永远等不到完整响应。且原 proxy 是单线程 `HTTPServer`，一个卡住的请求会阻塞所有后续请求。

**解决：** 更新 `log_proxy.py`：
1. 检测 `stream: true` 请求，改为逐块转发（`resp.read(4096)` + `wfile.flush()`）
2. 改为多线程 `ThreadedHTTPServer`，避免单个请求阻塞

---

## 22. QQ Bot 语音回复同时带文字

**现象：** QQ bot 发语音消息回复时，先发一条文字，再发一条语音，用户收到两条消息。

**原因：** OpenClaw qqbot 插件的 `dispatchOutbound` 逻辑：先发送 markdown 文字回复，再发送本地 media（TTS 生成的语音）。没有"发语音时抑制文字"的选项。

**解决：** 待 OpenClaw 更新或通过插件配置解决。当前先接受双消息行为。

---

## 23. QQ Bot 语音消息延迟分析

**实测数据（2026-05-13）：**

| 消息 | STT+LLM | TTS | 总计 |
|------|---------|-----|------|
| #1 (08:49) | 15s | 5s | 20s |
| #2 (08:56) | 51s | 5s | 57s |
| #3 (09:05) | 25s | 14s | 44s |
| #4 (09:07) | 14.5s | 5.5s | 20s |

**瓶颈分析：**
- **LLM (GLM-4.7 云端)** — 6~51s，极不稳定，是主要瓶颈
- **System prompt 过大** — 17164 字符，28 工具 + 13 技能，tool schema 占 22,299B
- **TTS** — 稳定 ~5s（edge-tts）
- **STT** — 2~10s（QQ CDN 音频下载波动）

**优化方向：**
1. 精简工具和技能（预计减少 ~8k tokens，LLM 延迟降 30-50%）
2. 精简 prompt 后可重试本地 MiniCPM
3. 切换到 VoxCPM2 TTS（更高音质，支持声音克隆）

---

## 24. VoxCPM2 TTS 部署

**项目：** [nanovllm-voxcpm](https://github.com/a710128/nanovllm-voxcpm) — 基于 Nano-vLLM 加速的 VoxCPM2 TTS 推理引擎

**架构：**
```
OpenClaw Gateway → TTS 适配层 (:8091, OpenAI 兼容, voices.json 配置) → VoxCPM2 (:8000, 推理)
```

**文件结构：**
```
tts-adapter/
├── adapter.py         # OpenAI 兼容适配层，支持多音色预设
├── voxcpm_server.py   # VoxCPM2 FastAPI 服务（使用 AsyncVoxCPM2ServerPool）
├── voices.json        # 音色配置：prompt_text / cfg_value / temperature / ref_audio
├── requirements.txt   # fastapi, uvicorn, httpx
└── ref_audio.wav      # (可选) 参考音频，用于声音克隆
```

**启动命令：**
```bash
# 1. 启动 VoxCPM2 推理服务
conda activate voxcpm
python voxcpm_server.py --port 8000 --gpu-memory 0.85

# 2. 启动适配层
python adapter.py --port 8091
```

**实际部署记录（2026-05-13）：**
1. `conda create -n voxcpm python=3.10`
2. `pip install torch==2.5.1+cu124`（从 pytorch.org）
3. `pip install flash-attn` — 实际从 PyPI 下载了预编译 wheel（~240MB），源码编译需 2h+
   - 如果 PyPI 没有预编译版本，设置 `TORCH_CUDA_ARCH_LIST="8.0"` 可加速编译（只编译 sm_80，跳过 sm_90/100/120）
4. `pip install git+https://github.com/a710128/nanovllm-voxcpm.git`
5. 模型下载：`modelscope download --model OpenBMB/VoxCPM2 --local_dir ~/work/models/VoxCPM2`（4.3GB，国内比 HF 快）
6. 启动 VoxCPM2：`python voxcpm_server.py --port 8000 --gpu-memory 0.85`
7. 启动适配层：`python adapter.py --port 8091`
8. OpenClaw 无需修改（已指向 :8091）

**踩坑：**
- flash-attn 源码编译极慢（2h+），优先找预编译 wheel（PyPI 或 GitHub Releases）
- GitHub Releases 有精确匹配的 wheel：`flash_attn-2.8.3+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl`
- 但 GitHub 直连下载也很慢（~200KB/s），最终 PyPI 清华镜像反而有预编译版本
- VoxCPM2 使用 `SyncVoxCPM2ServerPool` 在 FastAPI 内会冲突（event loop 嵌套），需用 `AsyncVoxCPM2ServerPool`
- 显存不足时先 `kill` 旧 VoxCPM2 进程（子进程不会自动退出）

**性能：**
- 短文本（10字）生成 2-3s 音频，耗时 ~1s（RTF ~0.4）
- 长文本（50字）生成 8-10s 音频，耗时 ~2-3s（RTF ~0.3）
- 模型加载耗时 ~15s（含音频 VAE）

**显存规划（RTX 5000 Ada 16GB, CC 8.9）：**
| 服务 | 显存 |
|------|------|
| faster-whisper large-v3 (STT) | ~2.1 GB |
| VoxCPM2 (TTS) | ~11 GB |
| 合计 | ~13.1 GB |
| 剩余 | ~2.5 GB |

需要确保 llama.cpp 已停止。

---

## 26. QQ Bot 语音消息未识别

**现象：** QQ 发送语音消息后，OpenClaw 回复 3 条文字消息（非语音），语音内容未被识别。

**原因：** QQ Bot API 的 C2C_MESSAGE_CREATE 事件在语音消息时，`content` 字段为空，`attachments` 数组应包含 `content_type: "voice"` 的附件对象。但实际日志显示 attachments 也为空。

**排查方向：**
1. 开启 debug 日志查看原始 WebSocket 事件数据（当前日志级别为 info，`Dispatch event` 日志不可见）
2. 检查 QQ Bot 是否为 sandbox 模式（沙箱机器人可能不支持语音消息）
3. QQ Bot API 文档说明 C2C 语音消息应通过 `attachments` 传递，包含 `url`、`voice_wav_url`、`asr_refer_text` 字段

**相关代码：**
- 事件分发：`extensions/qqbot/dist/gateway-Cs3-_on9.js` → `dispatchEvent()` → `C2C_MESSAGE_CREATE`
- 附件处理：同文件 → `processAttachments()` → `processVoiceAttachment()`
- STT 调用：同文件 → `transcribeAudio()` → STT 服务 `:8090`

**状态：** 待进一步排查（已暂停，优先完成 VoxCPM2 TTS 部署）。

---

## 27. QQ Bot 认证失败 (invalid appid or secret)

**现象：** `gw.log` 中 QQ Bot 每分钟重试，持续报 `{"code":100016,"message":"invalid appid or secret"}`，累计 70+ 次未成功。

**排查：**
1. 从开发机手动调用 QQ Bot API 验证凭证：
   ```bash
   curl -X POST "https://bots.qq.com/app/getAppAccessToken" \
     -H "Content-Type: application/json" \
     -d '{"appId":"1903994541","clientSecret":"BICtNegU4QXQ4Uge"}'
   ```
   返回 `{"access_token":"...","expires_in":"4948"}`，**凭证有效**。

2. 旧 gateway（5/14）的日志一直报错，但手动启动新 gateway 后 QQ Bot 成功连接。

**原因：** 旧 gateway 进程长时间运行后 QQ Bot WebSocket 断连，重连时因网络波动导致 token 获取失败，退避重试未恢复。重启 gateway 即可恢复。

**解决：**
```bash
# 停止 app（杀掉旧 gateway）
adb shell "am force-stop com.openclaw.car"
# 手动启动 gateway 验证 QQ Bot 连接
adb shell "export LD_LIBRARY_PATH=/data/local/tmp/node-lib && \
  export OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf && \
  export HOME=/data/local/tmp/openclaw-home && \
  export NODE_PATH=/data/local/tmp/node-lib/node_modules && \
  export OPENCLAW_HOME=/data/local/tmp/openclaw-home && \
  timeout 30 /data/local/tmp/node-termux \
  /data/local/tmp/openclaw/lib/node_modules/openclaw/openclaw.mjs \
  gateway run --verbose 2>&1"
# 看到 "[qqbot:default] Gateway ready" 后 Ctrl+C，再重新启动 app
adb shell "am start -n com.openclaw.car/.MainActivity"
```

**诊断经验：**
- Gateway 日志文件：`/data/local/tmp/openclaw-home/gw.log`（旧版写入）或 logcat（新版 NodeProcessManager 捕获 stdout）
- QQ Bot 连接成功标志：`[qqbot:default] Gateway ready` + `Dispatch event: t=READY`
- QQ Bot WebSocket 地址：`wss://api.sgroup.qq.com/websocket`

---

## 28. CommandReceiver 后台启动前台服务崩溃 (Android 12+)

**现象：** 通过 `am broadcast -n com.openclaw.car/.service.CommandReceiver -a com.caragent.START` 启动服务，app 直接崩溃：

```
ForegroundServiceStartNotAllowedException: startForegroundService() not allowed due to
mAllowStartForeground false: service com.openclaw.car/.service.NodeProcessService
```

**原因：** Android 12+ 限制从后台启动前台服务（BroadcastReceiver 属于后台组件）。当 app 不在前台时，`CommandReceiver.onReceive()` → `NodeProcessService.start()` → `startForegroundService()` 会被系统拒绝。

**影响：** 无法通过 `am broadcast` 远程控制 Node.js 进程启停。`com.caragent.STOP` 也有同样问题（会杀死 app 进程）。

**临时解决：**
```bash
# 先把 app 切到前台再发广播
adb shell "am start -n com.openclaw.car/.MainActivity"
sleep 2
adb shell "am broadcast -n com.openclaw.car/.service.CommandReceiver -a com.caragent.START"
```

**正式修复（待实现）：** `CommandReceiver.onReceive()` 中 try-catch `ForegroundServiceStartNotAllowedException`，改为通过 `WorkManager` 或 `JobIntentService` 延迟启动。

---

## 29. Gateway 日志查看方法

### 方法一：gw.log 文件

旧版 gateway 写入 `/data/local/tmp/openclaw-home/gw.log`。新版 gateway（由 NodeProcessManager 启动）stdout 被 NodeProcessManager 捕获后通过 `Log.d()` 输出到 logcat。

```bash
adb shell "tail -50 /data/local/tmp/openclaw-home/gw.log"
```

### 方法二：手动启动 gateway（推荐调试用）

先停掉 app，然后手动启动 gateway 可以看到完整 verbose 日志：

```bash
# 1. 停掉 app（释放端口）
adb shell "am force-stop com.openclaw.car"

# 2. 手动启动 gateway（30s 超时自动退出）
adb shell "export LD_LIBRARY_PATH=/data/local/tmp/node-lib && \
  export OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf && \
  export HOME=/data/local/tmp/openclaw-home && \
  export NODE_PATH=/data/local/tmp/node-lib/node_modules && \
  export OPENCLAW_HOME=/data/local/tmp/openclaw-home && \
  timeout 30 /data/local/tmp/node-termux \
  /data/local/tmp/openclaw/lib/node_modules/openclaw/openclaw.mjs \
  gateway run --verbose 2>&1"

# 3. 看到问题后，恢复 app
adb shell "am start -n com.openclaw.car/.MainActivity"
```

**关键日志标志：**
- `✅ Access token obtained successfully` — QQ Bot 认证成功
- `[qqbot:default] Gateway ready` — QQ Bot 频道就绪
- `feishu[default]: WebSocket client started` — 飞书频道就绪
- `http server listening (N plugins: ...)` — HTTP 服务就绪

---

## 30. VoxCPM2 TTS 参数：cfg_value 不能为 1.0

**现象：** 发送 TTS 请求后 VoxCPM2 卡住不返回音频，日志无报错。

**原因：** VoxCPM2 的 `cfg_value`（Classifier-Free Guidance 强度）设为 1.0 时，模型内部推理逻辑会导致死循环/无限等待。默认值 2.0 可以正常工作，但音质有杂音。

**解决：** `cfg_value` 设为 1.5（兼顾音质和稳定性）。

**涉及文件：**
- `tts-adapter/voices.json` — 服务端音色预设配置
- `agent_front_app/.../FileHelper.kt` — 客户端 VOICE_PRESETS
- `agent_front_app/.../TtsApiClient.kt` — 通过 API `/v1/voices` 切换音色

**参数说明：**

| 参数 | 作用 | 推荐值 | 说明 |
|------|------|--------|------|
| cfg_value | 风格引导强度 | 2.0 | 1.0 会卡死，2.0 官方默认，配合 prompt_text 使用效果好 |
| temperature | 随机性 | 0.5 | 0.5 适中，0.8 用于唱歌模式 |

---

## 31. flash-attn 与 PyTorch 版本兼容性

**现象：** `import flash_attn` 报 `undefined symbol: _ZN3c104cuda29c10_cuda_check_implementationEiPKcS2_ib`

**原因：** `flash-attn` 预编译 wheel 绑定特定 PyTorch 版本。PyTorch 2.12+cu130 与 flash-attn 2.8.3 不兼容。

**解决：** 降级 PyTorch 到 `2.6.0+cu124`：
```bash
conda activate voxcpm
pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

**注意：** 需要 CUDA 12.4 兼容的驱动。如果 `nvcc --version` 显示 < 11.7，不要尝试源码编译 flash-attn，直接用预编译 wheel。

---

## 部署清单 (新版 2026.5.7)

| 步骤 | 说明 |
|------|------|
| 1 | npm pack openclaw@2026.5.7，解压到车机 `lib/node_modules/openclaw/` |
| 2 | `npm install --omit=dev --ignore-scripts` 全量依赖推送 |
| 3 | `@openclaw/feishu` 安装到 `dist/extensions/feishu/` |
| 4 | 修改 `model-definitions-*.js` 和 `provider-zai-endpoint-*.js` 中的 base URL |
| 5 | 配置 `openclaw.json`（agent model、compaction、channels、gateway） |
| 6 | 配置 `agents/main/agent/models.json`（provider URL + 模型列表） |
| 7 | 创建 `agents/main/agent/auth-profiles.json`（API key 认证） |
| 8 | 启动 gateway，飞书配对 |

---

## 车机重启后完整启动清单

车机重启后，以下服务/配置不会自动恢复，需要手动执行。

### 第一步：ADB 连接 & Root

```bash
adb connect <device>        # 如果无线连接
adb root                    # 获取 root 权限
adb shell whoami            # 验证：应返回 root
```

### 第二步：验证 GPS Monitor（boot script 自动启动）

GPS monitor 从车机 SomeIP 日志解析 GPS 坐标，没跑会导致 UiHttpServer `/location` 接口卡死（进而导致 LLM 调用超时）。

**Magisk boot script (`/data/adb/service.d/openclaw-boot.sh`) 已在 boot 后 ~25s 自动用 `setsid` 拉起 gps-monitor.sh，不要手动 `nohup sh ... &`**——脚本是单实例锁保护的（flock），手动起会被静默挡掉（看到 `[gps-monitor] already running, exit` 就是这个原因）。如果 ps 看不到进程，**首选方案是 reboot 设备**让 boot script 重新拉；万不得已才 `setsid /system/bin/sh /data/local/tmp/gps-monitor.sh </dev/null >/dev/null 2>&1 &`。

```bash
# 验证（应该见到 1 行，PID 旁边的 ARGS 显示 sh .../gps-monitor.sh）
adb shell "ps -A -o PID,ARGS | grep -E 'monitor\\.sh|music-cmd' | grep -v grep"
# 应返回 3 行：music-cmd / music-monitor / gps-monitor 各 1 份
adb shell "cat /data/local/tmp/gps.json"
# 应返回 {"ok":true,"lat":"...","lng":"..."}
```

### 第三步：验证音乐控制 Daemons（boot script 自动启动）

音乐控制依赖两个 root daemon：`music-cmd.sh`（执行 keyevent）和 `music-monitor.sh`（每 3s 刷新播放状态写 music-state.json）。Magisk boot script 同样自动启动，验证方法同第二步（一条 ps 命令同时看 3 个脚本）。

```bash
# 验证 state 文件新鲜度（mtime 应该 <5s 前）
adb shell "stat -c '%Y %n' /data/local/tmp/music-state.json /data/local/tmp/gps.json; date +%s"
adb shell "cat /data/local/tmp/music-state.json"
# 应返回 {"ok":true,"state":"playing/paused","title":"...","artist":"..."}
```

### 第四步：悬浮球权限

```bash
adb shell "appops set com.openclaw.car SYSTEM_ALERT_WINDOW allow"
# 验证
adb shell "appops get com.openclaw.car SYSTEM_ALERT_WINDOW"
# 应返回 allow
```

### 第五步：启动车机 App

车机 App 启动后会自动启动 OpenClaw Gateway。

```bash
adb shell "am start -n com.openclaw.car/.MainActivity"
# 等待 ~10s 让 gateway 启动
sleep 10
# 验证
adb shell "netstat -tlnp 2>/dev/null | grep 18801"
# 应看到 LISTEN
```

### 第六步：ADB 端口转发

```bash
adb forward tcp:18801 tcp:18801   # Gateway (浏览器 dashboard)
adb forward tcp:18802 tcp:18802   # UiHttpServer (/location, /health)
# 验证
curl -s http://localhost:18801/v1/models -H "Authorization: Bearer fe3936a8d8dafeec8efb6d801863eb00c4c08298555a4817"
curl -s http://localhost:18802/health
curl -s --max-time 5 http://localhost:18802/location
```

### 第七步：开发机服务 (STT + TTS)

```bash
conda activate voxcpm2

# 1. VoxCPM2 TTS（~30s 加载）
nohup vllm serve /home/tsm/work/voxcpm/models/VoxCPM2 \
  --omni --host 0.0.0.0 --port 8000 \
  > /tmp/voxcpm2.log 2>&1 &

# 2. STT（等 VoxCPM2 先占显存）
sleep 5
nohup /home/tsm/miniconda3/envs/stt/bin/python \
  /home/tsm/work/stt/stt-server.py --host 0.0.0.0 --port 8090 \
  > /tmp/stt.log 2>&1 &

# 3. TTS 适配层（等 VoxCPM2 就绪）
sleep 30
nohup python /home/tsm/work/android_agent/tts-adapter/adapter.py \
  --voxcpm-url http://127.0.0.1:8000 --port 8091 --host 0.0.0.0 \
  > /tmp/tts-adapter.log 2>&1 &
```

### 第八步：诊断验证

```bash
echo "=== 车机 Gateway ==="
curl -s --max-time 5 http://localhost:18801/health

echo "=== 车机 UiHttpServer ==="
curl -s --max-time 5 http://localhost:18802/health

echo "=== 车机音乐控制 ==="
curl -s --max-time 5 -X POST http://localhost:18802/music/state -H "Content-Type: application/json" -d '{}'

echo "=== 车机 GPS ==="
curl -s --max-time 5 http://localhost:18802/location

echo "=== 开发机 STT ==="
curl -s --max-time 5 http://localhost:8090/v1/models

echo "=== 开发机 VoxCPM2 ==="
curl -s --max-time 5 http://localhost:8000/v1/models

echo "=== 开发机 TTS Adapter ==="
curl -s --max-time 5 http://localhost:8091/health
```

全部返回正常即可。飞书发一条消息测试端到端链路。

### 常见问题快速排查

| 症状 | 排查 | 解决 |
|------|------|------|
| 飞书消息无回复 | `tail gateway-stdout.log` 看是否收到消息 | 重启 gateway |
| LLM 超时 (60s) | 检查 DeepSeek API 连通性 + session 上下文大小 | 清 session 或加大 timeout |
| 语音不识别 | STT 服务是否在跑 + `/v1/audio/transcriptions` 是否正常 | 重启 STT |
| 语音回复为英文错误 | LLM 超时后的错误消息被 TTS 念出来 | 排查 LLM 超时原因 |
| `/location` 卡死 | `ps -A \| grep gps-monitor` 是否有 1 行 | reboot 设备让 boot script 拉；不要手动 nohup（脚本是单实例锁保护的，被挡掉） |
| `/music/*` 返回 error | `ps -A \| grep -E 'music-cmd\|music-monitor'` 各 1 行 | 同上，reboot 而非手动追加 |
| 悬浮球不显示 | overlay 权限 | `appops set ... allow` |
| 高德 API key 失效 | TOOLS.md 中 amap.sh 说明是否在 | 检查 TOOLS.md |

### 一键状态检查

```bash
#!/bin/bash
# 用法：在开发机上运行，检查所有服务是否正常

OK=0
FAIL=0

check() {
  local label=$1 url=$2 expect=$3
  local resp
  resp=$(curl -s --max-time 5 "$url" 2>/dev/null)
  if [ $? -eq 0 ] && echo "$resp" | grep -q "$expect"; then
    echo "✓ $label"
    ((OK++))
  else
    echo "✗ $label  (curl failed or unexpected response)"
    ((FAIL++))
  fi
}

echo "=== 车机服务 ==="
check "Gateway (18801)"    "http://localhost:18801/v1/models" "data"
check "UiHttpServer (18802)" "http://localhost:18802/health"   "ok"
check "GPS Monitor"        "http://localhost:18802/location"  "lat"

echo ""
echo "=== 开发机服务 ==="
check "STT (8090)"         "http://localhost:8090/v1/models"  "sensevoice"
check "VoxCPM2 (8000)"     "http://localhost:8000/v1/models"  "VoxCPM2"
check "TTS Adapter (8091)" "http://localhost:8091/health"      "ok"

echo ""
echo "=== 车机进程 ==="
echo -n "GPS Monitor: "
adb shell "ps -A | grep -q gps-monitor && echo ✓ running || echo ✗ not running"
echo -n "OpenClaw:     "
adb shell "ps -A | grep -q 'openclaw$' && echo ✓ running || echo ✗ not running"

echo ""
echo "结果: $OK 通过, $FAIL 失败"
[ $FAIL -eq 0 ] && echo "全部正常，可以测试飞书端到端链路。"
```

---

## Gateway 重启

### 方式一：ADB 重启 App（推荐）

强制重启整个 App，gateway 会随之重启：

```bash
adb -s LZBYDUMNB6RW7X5P shell "am force-stop com.openclaw.car && sleep 2 && am start -n com.openclaw.car/.MainActivity"
```

### 方式二：HTTP API 重启 Gateway

不重启 App，只重启 gateway 进程（需要 ADB 端口转发）：

```bash
adb -s LZBYDUMNB6RW7X5P forward tcp:18801 tcp:18801
curl -s -X POST http://localhost:18801/gateway/restart
```

### 方式三：Broadcast

```bash
adb -s LZBYDUMNB6RW7X5P shell "am broadcast -a com.caragent.STOP && sleep 2 && am broadcast -a com.caragent.START"
```

### 验证

```bash
# 端口转发（每次重连 ADB 后需要）
adb -s LZBYDUMNB6RW7X5P forward tcp:18801 tcp:18801

# 检查 gateway 是否响应
curl -s http://localhost:18801/v1/models -H "Authorization: Bearer fe3936a8d8dafeec8efb6d801863eb00c4c08298555a4817"
```

### OpenClaw 安装路径

| 路径 | 说明 |
|------|------|
| `/data/local/tmp/openclaw/lib/node_modules/openclaw/` | OpenClaw 主程序 |
| `/data/local/tmp/openclaw/lib/node_modules/openclaw/openclaw.mjs` | 入口文件 |
| `/data/local/tmp/node-termux` | Node.js 运行时 |
| `/data/local/tmp/openclaw-home/` | 工作目录 |
| `/data/local/tmp/openclaw-home/.openclaw/` | 配置目录 |
| `/data/local/tmp/openclaw-home/.openclaw/openclaw.json` | 主配置 |
| `/data/local/tmp/openclaw-home/.openclaw/logs/gateway-stdout.log` | Gateway 日志 |

---

## 开发机服务启动命令

以下服务运行在开发机（172.20.10.5, RTX 5000 16GB）上。

### 显存规划

| 服务 | 显存 | GPU 占用 |
|------|------|----------|
| VoxCPM2 (TTS) | ~11 GB | 0.7 |
| faster-whisper (STT) | ~2.1 GB | - |
| 合计 | ~13 GB | |
| 剩余 | ~3 GB | |

### STT 服务 (端口 8090)

```bash
# 启动（FunASR SenseVoice，默认模型）
nohup /home/tsm/miniconda3/envs/stt/bin/python \
  /home/tsm/work/stt/stt-server.py --host 0.0.0.0 --port 8090 \
  > /tmp/stt.log 2>&1 &

# 验证
curl -s http://localhost:8090/v1/models
# 停止
kill $(pgrep -f stt-server.py)
```

### TTS 服务 — VoxCPM2 推理 (端口 8000)

**启动方式（两种，任选其一）：**

```bash
# 激活环境后启动（必须先 conda activate，否则 vllm-omni 补丁不生效）
conda activate voxcpm2
nohup vllm serve /home/tsm/work/voxcpm/models/VoxCPM2 \
  --omni --host 0.0.0.0 --port 8000 \
  > /tmp/voxcpm2.log 2>&1 &
```

```bash
# 验证（等模型加载完约 30s）
tail -f /tmp/voxcpm2.log
# 看到 "Application startup complete" 即可

# 测试
curl http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "你好", "response_format": "wav"}' \
  --output /tmp/test.wav

# 停止
kill $(pgrep -f "vllm.*VoxCPM2")
kill $(pgrep -f "resource_tracker") 2>/dev/null  # 子进程清理
```

**注意：**
- 必须先 `conda activate voxcpm2` 再执行 `vllm serve`，直接用绝对路径调 python 会绕过环境激活导致失败
- 如果重启过 VoxCPM2，子进程可能不会自动退出：`kill $(pgrep -f "resource_tracker")`

### TTS 服务 — 适配层 (端口 8091)

```bash
# 启动
nohup python3 /home/tsm/work/android_agent/tts-adapter/adapter.py \
  --voxcpm-url http://127.0.0.1:8000 --port 8091 --host 0.0.0.0 \
  > /tmp/tts-adapter.log 2>&1 &

# 验证
curl -s http://localhost:8091/health
# 停止
kill $(pgrep -f adapter.py)
```

### 全部服务启动顺序

```bash
# 0. 激活 conda 环境
conda activate voxcpm2

# 1. VoxCPM2（最慢，需要 ~30s 加载模型）
nohup vllm serve /home/tsm/work/voxcpm/models/VoxCPM2 \
  --omni --host 0.0.0.0 --port 8000 \
  > /tmp/voxcpm2.log 2>&1 &

# 2. STT（需要 ~15s 加载模型，等 VoxCPM2 先占显存）
sleep 5
nohup /home/tsm/miniconda3/envs/stt/bin/python \
  /home/tsm/work/android_agent/stt-server.py --host 0.0.0.0 --port 8090 \
  > /tmp/stt.log 2>&1 &

# 3. TTS 适配层（秒启动，等 VoxCPM2 就绪后再启动）
sleep 30
nohup python /home/tsm/work/android_agent/tts-adapter/adapter.py \
  --voxcpm-url http://127.0.0.1:8000 --port 8091 --host 0.0.0.0 \
  > /tmp/tts-adapter.log 2>&1 &
```

### 全部服务停止

```bash
kill $(pgrep -f adapter.py) 2>/dev/null
kill $(pgrep -f stt-server.py) 2>/dev/null
kill $(pgrep -f "vllm.*VoxCPM2") 2>/dev/null
kill $(pgrep -f "resource_tracker") 2>/dev/null
```

---

## 32. 飞书 TTS 语音回复不触发

**现象：** 飞书发语音消息，bot 只回复文字，不回复语音。TTS adapter (8091) 没收到任何请求。

**根因（三个叠加问题）：**

### 32.1 Session store `ttsAuto` 优先级最高，覆盖 config

TTS auto mode 解析优先级：

```
session store ttsAuto > preferences file > config messages.tts.auto
```

`sessions.json` 中有 `"ttsAuto": "inbound"`，无论 config 写什么都会被覆盖。

**解决：** 同步修改 `sessions.json`：

```bash
adb shell "su -c 'cat .../sessions/sessions.json'" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for k in data:
    if 'ttsAuto' in data[k]:
        data[k]['ttsAuto'] = 'always'
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" > /tmp/sessions_fixed.json
adb push /tmp/sessions_fixed.json .../sessions/sessions.json
```

### 32.2 `auto: "inbound"` 模式对飞书无效

**原因：** `isInboundAudioContext()` 检查 `ctx.MediaType === "audio"`，但飞书插件**从未**在 dispatch context 中设置 `MediaType`。飞书语音消息走 `<media:audio>` 占位符 + preflight transcription 路径，不设置 MediaType。

```javascript
// dispatch-BlRYQnj0.js:168
const isInboundAudioContext = (ctx) => {
    if ([ctx.MediaType, ...ctx.MediaTypes].some(t => t === "audio")) return true;
    // ...
};
```

所以 `inboundAudio` 永远是 `false`，`auto: "inbound"` 模式下 TTS 永远跳过。

**解决：** 用 `auto: "always"` 模式。

### 32.3 必须显式配置 `messages.tts.providers.openai.baseUrl`

**原因：** TTS 请求的 baseUrl 解析链：

```
messages.tts.providers.openai.baseUrl > models.providers.openai.baseUrl > 默认 https://api.openai.com/v1
```

`models.providers.openai.baseUrl` 指向 `http://172.20.10.5:8090/v1`（STT 端口），不配 TTS 的 providers 就会发到错误的端口。

**解决：** 完整的 TTS 配置：

```json
{
  "messages": {
    "tts": {
      "provider": "openai",
      "auto": "always",
      "providers": {
        "openai": {
          "apiKey": "not-needed",
          "baseUrl": "http://172.20.10.5:8091/v1"
        }
      }
    }
  }
}
```

**注意：** `talk.providers.openai` 是给浏览器 Talk 实时语音用的，与消息 TTS 是两套独立的配置体系。消息 TTS 读 `messages.tts.providers`，不读 `talk.providers`。
