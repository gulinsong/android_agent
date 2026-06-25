# 端到端语音模型 vs 分离式 Agent 链路：集成分析

- 日期：2026-06-25
- 背景：已实测豆包 Realtime API（实现独立闲聊 app `doubao_chitchat/`，BYD 车机跑通，首响 <100ms）。本文系统对比"端到端语音模型"与"现有分离式 agent 链路"，分析把端到端模型接入 agent 的问题与可行方案。

## ⚠️ 重要纠错（2026-06-25 更新）

**初版（2026-06-25 上午）结论"豆包端到端实时语音无 function calling"是错的。** 起因是只看了 [1594356](https://www.volcengine.com/docs/6561/1594356) 一份较旧的裸 S2S WebSocket API 文档，它的事件表（StartSession/TaskRequest/ASRInfo…）里没列 function_call 事件，就以偏概全下了全局结论。

**实际**：豆包实时语音**支持 Function Calling / 工具调用**，证据：
- 官方 [《使用 Function Calling — 实时音视频》6348/2123225](https://www.volcengine.com/docs/6348/2123225)：完整 FC 机制（控制台配工具 + 服务端下发 function_call 指令 + 客户端执行回传 + LLM 生成回复）。
- [豆包实时语音模型 3.0 Seeduplex](https://www.sohu.com/a/1038552291_122014422)："原生全双工端到端语音大模型…能在对话中**直接调用工具**完成任务"。

教训与鉴权那次相同：**火山文档与控制台/产品不同步，关键能力以官方最新文档 + 实测为准，不要凭单份文档下定论。**

## 1. 两种架构

**端到端（豆包 Realtime / Seeduplex）**：voice-in → voice-out，ASR + LLM + TTS 三段**一体化在火山云端**，客户端只收发 WebSocket/RTC 流。LLM 是豆包，**支持 Function Calling**。

**分离式（现有车机 agent 链路）**：`FunASR(8090, STT)` → `deepseek-chat(LLM + agent 逻辑)` → `VoxCPM2(8091, TTS)`，三段独立、每段可替换/可干预，LLM 是 deepseek。

## 2. 维度对比（已修正）

| 维度 | 端到端 Realtime（实测 + 文档） | 分离式 deepseek agent（现有） |
|---|---|---|
| 首响延迟（说完→首音频） | **<100ms**（459 与 350 同毫秒） | 561–638ms（三段叠加） |
| LLM | 豆包（锁定） | deepseek（可换） |
| function calling / 工具调用 | **✅ 支持**（3.0 Seeduplex / RTC 智能体方案，控制台配工具 + function_call 事件） | ✅ deepseek 驱动 |
| 工具调用接入方式 | 控制台配工具 → 监听 `function_call` 事件 → 执行 → `volc_send_message` 回传 | deepseek tools 参数 → 解析 tool_calls → 执行 → 回填 |
| A2UI 卡片 / MCP / 导航 / 音乐 | ✅ **可挂**（通过 FC，需迁移工具定义） | ✅ 已深度集成 |
| 打断 / barge-in | ✅ 原生 | 需自己实现 |
| VAD | ✅ 服务端原生 | 需自己接 |
| 音色 | 官方 4 个 / 克隆 | VoxCPM2 任意 |
| 上下文窗口 | 12K（工作记忆，靠 dialog_id 扩） | 64K |
| 可控性 / 可观测性 | 低（黑盒） | 高（每段可拦截） |
| 部署 | 全云端（必须公网可达） | STT/TTS 本地 + LLM 云 |

## 3. Function Calling 机制（豆包实时语音）

完整闭环（来自 [6348/2123225](https://www.volcengine.com/docs/6348/2123225)）：

1. **准备**：客户端定义本地函数（如 `adjust_volume(action, step)`）；控制台"智能体 → 高级配置 → Function Calling"配置工具（名称/描述/参数 schema）。
2. **下发**：用户说话 → 服务端 LLM 识别意图 → 推送指令
   - WS 方案：先 `conversation.item.created`(item.type=function_call) 通知，再 `response.function_call_arguments.done`(name + arguments) 指令
   - RTC 方案：8 字节头二进制（`info` 通知 / `tool` 指令）
3. **执行 + 回传**：客户端 `on_volc_message_data` 收指令 → 执行本地函数 → `volc_send_message` 回传结果（直接 TTS 播报，或经 LLM 润色后播报）
4. **最佳实践**：耗时函数前播安抚语（如"请稍等，正在查询"）；用 system prompt 精准控制调用时机（避免闲聊也触发）。

**注意**：FC 的能力前提是模型版本/接入方案支持——我们 app 当前用的 [1594356](https://www.volcengine.com/docs/6561/1594356) + model `1.2.1.1`(O2.0) 旧版事件表里**没列** function_call 事件；要用 FC 需升级到 **Seeduplex 3.0** 或走 **RTC 智能体方案**（见 §5）。

## 4. 三种集成方案 + 修正后判断

| 方案 | 做法 | 实测/文档后判断 |
|---|---|---|
| **A. 全量替换（带 FC）** | Realtime/Seeduplex 取代整条 agent 语音链，工具定义迁移到火山控制台 | ✅ **可行**（FC 支持后）。拿到最低延迟 + 原生打断 + 省自建 STT/TTS；代价：工具定义迁控制台、LLM 换豆包、调试黑盒、需升级模型版本 |
| **B. 当 TTS 前端** | deepseek 出文本 → Realtime 合成 | ⚠️ 仍受 deepseek 首 token 限制，延迟优势打折，性价比低 |
| **C. 独立闲聊并存** ✅ | Realtime 做独立 app（已落地 doubao_chitchat） | ✅ 已落地，纯对话场景验证可用 |

## 5. 结论与建议（已修正）

- **端到端 Realtime 能驱动 agent**：FC 支持推翻了"只适合纯对话"的旧结论。理论上可承接 skill/工具/卡片（需把工具定义迁到火山控制台 + 客户端处理 function_call 事件）。
- **现阶段仍建议 C（独立并存）**，但**理由变了**：不是因为"不能 FC"，而是因为
  1. 现有 agent 的工具链/A2UI/MCP 深度绑定 deepseek，迁移到豆包 FC 有工程量 + 回归风险；
  2. 豆包作 LLM 的工具调用稳定性/JSON 遵循度需实测验证（vs deepseek 已久经考验）；
  3. 黑盒调试成本。
- **未来融合路径（A）的现实推进**：
  1. 把 doubao_chitchat 升级到 **Seeduplex 3.0**（或换 RTC 智能体方案）拿 FC 能力；
  2. 先在独立 app 里跑通 1–2 个 FC 工具（如调音量、查天气），验证豆包 FC 的可靠性；
  3. 验证通过后，再评估把 agent 主链路的工具逐步迁移，最终用端到端低延迟替换分离式。
- **若只想要低延迟不换 LLM**：走 B（deepseek 决策 + Realtime 流式 TTS 替换 VoxCPM2），首响瓶颈从 TTS 首音频转移到 deepseek 首 token。

## 附：实测关键数据（doubao_chitchat, BYD 车机，O2.0 无 FC 版本）
- 首响延迟：<100ms（`459 ASREnded` 与 `350 TTSSentenceStart` 同毫秒）
- 对比 VoxCPM2 流式：561–638ms
- 端到端链路稳定跑通：连接/开场白/对话/打断/多轮/10 分钟不崩
- 主要工程坑：鉴权实测、多用户权限、AudioTrack 路由、interrupt 协程、SIGSEGV、回声循环（详见 `doubao-chitchat-implementation.md`）
