# 端到端语音模型 vs 分离式 Agent 链路：集成分析

- 日期：2026-06-25
- 背景：已实测豆包 Realtime API（实现独立闲聊 app `doubao_chitchat/`，BYD 车机跑通，首响 <100ms）。本文系统对比"端到端语音模型"与"现有分离式 agent 链路"，分析把端到端模型接入 agent 的问题与可行方案。
- 关联：`docs/doubao-chitchat-implementation.md`（实现踩坑）、`docs/superpowers/specs/2026-06-24-doubao-realtime-chitchat-design.md`

## 1. 两种架构

**端到端（豆包 Realtime API）**：voice-in → voice-out，ASR + LLM + TTS 三段**一体化在火山云端**，客户端只收发 WebSocket 二进制流。LLM 锁定豆包。

**分离式（现有车机 agent 链路）**：`FunASR(8090, STT)` → `deepseek-chat(LLM + agent 逻辑)` → `VoxCPM2(8091, TTS)`，三段独立、每段可替换/可干预，LLM 是 deepseek。

## 2. 维度对比

| 维度 | 端到端 Realtime（实测） | 分离式 deepseek agent（现有） |
|---|---|---|
| 首响延迟（说完→首音频） | **<100ms**（459 与 350 同毫秒） | 561–638ms（ASR 等完 + LLM 首 token + TTS 首音频 三段叠加） |
| LLM | 豆包（**锁定**，不可换） | deepseek（可换任何 OpenAI 兼容） |
| function calling / 工具调用 | **❌ 无**（协议层无 tools 字段） | ✅ deepseek 驱动，agent 能力根基 |
| A2UI 卡片 / MCP / 导航 / 音乐控制 | ❌ 挂不上 | ✅ 深度集成（[[a2ui-music-card]]、[[byd-mediacenter-integration]] 等） |
| 打断 / barge-in | ✅ 原生（ASRInfo 450 + duplex） | 需自己实现（ASRInfo 拦截 + 停 TTS） |
| VAD | ✅ 服务端原生 | 需自己接（FunASR/本地） |
| 音色 | 官方 4 个 / 克隆（锁定服务端） | VoxCPM2 任意（`voices.json`） |
| 上下文窗口 | 12K（工作记忆，靠 `dialog_id` 扩） | 64K |
| 可控性 / 可观测性 | 低（黑盒，只看事件流） | 高（每段可拦截/改写/日志） |
| 部署 | 全云端（必须公网可达） | STT/TTS 本地 + LLM 云 |
| 回声/AEC | 客户端负责（车机 AEC 不足易循环） | 同样客户端负责 |

## 3. 接入 agent 的核心问题

1. **无 function calling（最大障碍）**：Realtime 协议没有 `tools`/`function` 字段，豆包输出只有语音 + 文本（`ChatResponse`），**不会、也无法自主触发外部函数/skill**。车机 agent 的全部能力（`kaka_skills`、MCP、导航、音乐、A2UI 卡片 schema）都建立在 deepseek function calling 之上，端到端模型直接替换 = agent 能力归零。

2. **LLM 锁定豆包**：不能把 agent 逻辑（结构化 JSON 输出、工具编排、卡片模板约束）平移——豆包在这个 API 里是"口语对话模型"，定位不是 agent runtime。

3. **折中能力有限且失去 agent loop**：API 提供的 `ChatTextQuery(501)` / `ChatRAGText(502)` / `ChatTTSText(500)` 可以让客户端把外部结果喂回去让豆包"说"，但这是**客户端决策、豆包配音**，不是"模型自主决策调用"——没有 agent 的感知→决策→行动闭环。

4. **音色锁定**：官方 4 个精品音色或克隆音色，不是 VoxCPM2 的任意 `voices.json`，现有音色资产无法复用。

5. **上下文 12K**：长记忆弱于 deepseek 64K，需靠 `dialog_id`（持久 20 轮 QA）+ `enable_conversation_truncate` 管理工作记忆。

6. **可控性/可观测性低**：三段黑盒合一，无法在中间拦截改写（如纠错、敏感词、卡片注入），调试只能靠服务端事件流 + logid。

## 4. 三种集成方案 + 实测后判断

| 方案 | 做法 | 拿到 | 丢掉 | 实测后判断 |
|---|---|---|---|---|
| **A. 全量替换** | Realtime 取代整条 agent 语音链 | 最低延迟、原生打断、省自建 STT/TTS | 整个 deepseek agent（卡片/工具/MCP 全没） | ❌ 不可行（除非产品定位就是纯对话） |
| **B. 当 TTS 前端** | deepseek 出文本 → `ChatTTSText` 喂回 Realtime 合成 | 保留 agent + 拿到 Realtime 的 TTS 表现力 | 首响优势打折（仍受 deepseek 首 token 等待），架构变绕 | ⚠️ 性价比低，延迟优势没兑现 |
| **C. 独立闲聊并存** ✅ | Realtime 做独立 app，agent 主链路不动 | 纯对话场景的低延迟体验，风险隔离 | 不解决 agent 的延迟 | ✅ **已落地**（`doubao_chitchat/`，实测跑通） |

## 5. 结论与建议

- **端到端 Realtime 的甜区**：纯语音对话/陪伴/闲聊场景。首响 <100ms、原生打断、省自建 STT/TTS，体验显著优于分离式。**实测验证**（`doubao_chitchat/`）。
- **不适合**：agent 工具型场景（要出卡片、调导航、控音乐、跑 skill）。根因是**无 function calling**，这不是调参能弥补的架构差距。
- **现阶段落点**：**方案 C 独立并存**。agent 主链路（deepseek + A2UI + 工具）不动，端到端模型作为"独立闲聊 app"提供纯对话体验，两者各司其职、互不干扰。
- **未来重估触发点**：若火山开放 Realtime 的 function calling / tool use，或支持外部 multi-agent 编排（豆包做语音前端 + deepseek 做决策后端的双 LLM 架构），则可重新评估融合，把端到端的低延迟引入 agent 主链路。
- **若要把端到端延迟引入 agent**：现实路径是 B 的演进——deepseek 做 agent 决策，但用 Realtime 的 `ChatTTSText`/流式 TTS 替换 VoxCPM2，**只换 TTS 段**以降延迟；首响瓶颈则从"TTS 首音频"转移到"deepseek 首 token"，需配合 deepseek 流式 + 首句快答优化。

## 附：实测关键数据（doubao_chitchat, BYD 车机）
- 首响延迟：<100ms（`459 ASREnded` 与 `350 TTSSentenceStart` 同毫秒）
- 对比 VoxCPM2 流式：561–638ms（[[tts-streaming-comparison]]）
- 端到端链路稳定跑通：连接/开场白/对话/打断/多轮/10 分钟不崩
- 主要工程坑：鉴权实测、多用户权限、AudioTrack 路由、interrupt 协程、SIGSEGV、回声循环（详见 `doubao-chitchat-implementation.md`）
