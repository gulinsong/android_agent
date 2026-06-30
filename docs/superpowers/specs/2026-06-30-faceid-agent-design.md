# FaceID 接入 Agent 设计

> 日期: 2026-06-30
> 目标: 把人脸识别(faceid)能力接入 openclaw agent，实现"识别到注册用户 → 切换记忆/会话 → 个性化语音问候"

## 一、背景与现有能力

**faceid（已跑通）**：FaceEngine(yunet 检测 + R50 识别，全 MDLA APU，~55ms/帧)，OMS 实时视频流(yocto gst→跨域HTTP→app)，LiveVideoFace 注册+识别 RECOGNIZED，gallery JSON 持久化。详见 `docs/face-model-deployment.md`。

**agent 现有**：openclaw gateway(node-termux)，ppt-voice 走 FloatingBubbleService → ASR(8090) → gateway `/v1/chat/completions`(18801) → TTS(8091)。workspace 记忆文件：`USER.md`/`MEMORY.md`/`SOUL.md`/`IDENTITY.md` 等（gateway 按会话加载）。

**关键机制（已实测验证）**：
- gateway 用 `x-openclaw-session-key` header 区分 session。换 key = 新 session，**不 kill gateway，<1s**（实测 face-test key 自动建 session）。
- workspace 记忆文件支持**软链接**：`MEMORY.md → memory_faceid_{userid}.md`。gateway 读写 MEMORY.md = 读写 per-user 文件（跟链接），**零同步、不改 gateway**。需 `chown u10_a150:u10_a150`（实测 LLM 用对应记忆回答）。

## 二、场景（MVP 聚焦主动关怀）

核心场景：**用户上车 → faceid 识别 → 切换到该用户的 session/记忆 → LLM 个性化语音问候**。

后续场景（同一 faceid 服务，不同触发）：
- 唤醒识别身份（个性化响应）
- agent 工具查身份（MCP tool）
- 人脸认证/权限

本 spec 聚焦**主动关怀**，其他场景复用同一 faceid 服务 + session key 机制。

## 三、架构

```
OMS视频流(yocto) → app FaceIdService(后台)
   ↓ 每秒检测(yunet 4ms MDLA)
   ↓ 有脸 → 识别(55ms MDLA) + gallery match
   ↓ 连续N帧确认用户变化(防抖) + 冷却(防反复)
   ↓ 检测到注册用户 X
   ├─① 切 session key: currentSessionKey = "agent:main:face-X"
   ├─② 切记忆: ln -sf memory_faceid_X.md MEMORY.md + chown u10_a150
   ├─③ 问候: POST gateway /v1/chat/completions (key=face-X, system="当前用户X,请个性化问候")
   └─④ TTS 播报(复用 ppt-voice TTS 链路)

后续用户说话 → ppt-voice 用 currentSessionKey → 同 session(连贯)
```

**全复用 ppt-voice 的 gateway chat + TTS，零新通道。** faceid 只做「检测+切换+触发问候」。

## 四、组件

### 1. FaceIdService（app 后台服务，新增）
- 职责：后台每秒跑 faceid 检测+识别，用户变化时切换 session/记忆 + 触发问候
- 依赖：FaceEngine（检测+识别 MDLA）、OMS 视频流（pullFrame）、FaceGallery（match）
- 触发：app 启动 / 切换开关开启时起；每秒一次检测循环
- 防抖：连续 N 帧（如 3 帧/3s）识别到同一注册用户才确认切换
- 冷却：MVP **先关闭**（不设时间窗口冷却），防反复靠连续N帧确认 + 切换开关；后续如需可加

### 2. SessionKey 管理（全局）
- `currentSessionKey`：全局变量，默认 `agent:main:ppt-voice`
- faceid 切换：`currentSessionKey = "agent:main:face-{userid}"`
- FloatingBubbleService 改一处：`x-openclaw-session-key` 从固定常量 → 读 `currentSessionKey`
- 切换开关关闭：key 回 `agent:main:ppt-voice`

### 3. 记忆切换（软链接）
- per-user 持久化：`workspace/memory_faceid_{userid}.md`（注册时建空，对话中 LLM 写入）
- 活跃：`workspace/MEMORY.md` → 软链接当前用户文件
- 切换：`ln -sf memory_faceid_{userid}.md MEMORY.md && chown u10_a150:u10_a150 MEMORY.md`
- gateway 读写 MEMORY.md 自动 = per-user（跟链接），**零额外代码**
- 前端 MemoryFragment 读 MEMORY.md → 自动显示当前用户记忆（不改）

### 4. 切换开关（app 底部按钮）
- 关闭时：FaceIdService 不切换（只识别不触发问候/切换），demo 多人场景用
- 开启时：正常主动关怀

### 5. 问候触发
- faceid 确认切换 → POST gateway `/v1/chat/completions`
  - header: `x-openclaw-session-key: agent:main:face-{userid}` + auth Bearer token
  - body: `{model:"openclaw", messages:[{role:"system",content:"检测到注册用户{userid}上车，请用其记忆中的称呼/偏好自然问候"},{role:"user",content:"(用户上车)"}]}`
- gateway 同 session 生成个性化问候 → TTS

## 五、数据流（主动关怀完整链路）

1. OMS 流每秒一帧 → FaceIdService 检测(yunet 4ms) → 有脸(centerCrop 主驾)
2. 识别(R50 55ms) + gallery match → userid + cos
3. 连续 3 帧同 userid 且 cos≥0.5 → 确认（防抖）
4. 切 session key + 软链接记忆（ln+chown，<1ms）
5. POST gateway 问候（新 session + per-user 记忆，system 注入 userid）
6. gateway LLM 个性化问候 → TTS 播报（复用 ppt-voice TTS）
7. 后续用户说话 → ppt-voice 用 currentSessionKey → 同 session 连贯

## 六、边界与错误处理

- **无人/未注册**：检测无人或 cos<0.5 → 不切换，保持现状
- **OMS 流断**：pullFrame 失败 → 跳过本轮，下秒重试（不崩）
- **gallery 空**：识别无 match → UNKNOWN，不触发问候
- **切换开关关**：FaceIdService 只识别不切换（demo 模式）
- **记忆文件不存在**：首次注册用户 → 建空 `memory_faceid_{userid}.md`
- **软链接失败**（权限/空间）→ 降级不切记忆，只切 session（问候仍可）

## 七、实测验证（已完成）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| session key 切换不 kill | curl 新 key `agent:main:face-test` | ✅ 自动建 session，LLM 响应 |
| 软链接记忆 | ln -sf + chown + chat 问记忆内容 | ✅ gateway 跟链接读 per-user，LLM 答"拿铁" |
| faceid 检测+识别 | LiveVideoFace OMS 实时 | ✅ detScore 0.93, RECOGNIZED cos 0.78 |
| 全 MDLA 推理 | FaceEngine | ✅ detect 4ms + embed 7ms |

## 八、不在本 spec 范围（YAGNI）

- 唤醒识别/工具查身份/认证：后续复用同一 faceid 服务 + session key，单独 spec
- per-user 人设(SOUL/IDENTITY)切换：当前只切 MEMORY.md（偏好/事实），人设暂全局；如需 per-user 人设，同理软链接 SOUL.md
- 记忆容量管理：per-user MEMORY.md 增长，后续按需清理/摘要
- 多人并发（副驾识别）：当前只 centerCrop 主驾，副驾后续
