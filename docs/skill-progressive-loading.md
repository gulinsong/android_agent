# Skill 渐进式加载机制

## 概述

OpenClaw 的 skill 系统采用**索引-按需加载**模式：session 启动时只把每个 skill 的 name + description 作为轻量索引注入 system prompt，LLM 在需要时才读取完整 SKILL.md 内容。car-nav (778行) 和 car-poi (313行) 这样的大型 skill 不会一开始就占据 context，只在用户意图匹配时才加载。

## 加载流程

### 第一步：Gateway 启动时收集 Skill 索引

Gateway 启动时从多个位置扫描 SKILL.md 文件（按优先级从高到低）：

| 优先级 | 来源 | 路径（车机） | 本项目实际使用 |
|--------|------|-------------|--------------|
| 1 | Workspace skills | `~/.openclaw/workspace/skills/` | car-poi（覆盖版本） |
| 2 | Managed skills | `~/.openclaw/skills/` | car-nav, car-poi, a2ui-generation, 4个自定义skill |
| 3 | Plugin skills (symlink) | `~/.openclaw/plugin-skills/` | feishu-doc 等 feishu 插件自带 skill |
| 4 | Bundled skills | `openclaw/skills/` (npm包内置) | diagram-maker, github 等 |
| 5 | Extra skill folders | `skills.load.extraDirs` 配置 | 未使用 |

**实际车机部署结构：**

```
/data/local/tmp/openclaw-home/.openclaw/
├── skills/                          # Managed skills（优先级 2）
│   ├── car-nav/SKILL.md             # 导航控制（778行）
│   ├── car-poi/SKILL.md             # POI 搜索推荐（313行）
│   ├── a2ui-generation/SKILL.md     # A2UI 卡片生成
│   ├── inspiration-catcher/SKILL.md
│   ├── make-friends/SKILL.md
│   ├── no-reply-when-others-talk/SKILL.md
│   └── toxic-tongue-mode/SKILL.md
├── plugin-skills/                   # 插件 skill 的 symlink（优先级 3）
│   ├── car-nav → managed skills     # 重复引用
│   ├── car-poi → managed skills
│   ├── feishu-doc → feishu 插件
│   ├── feishu-drive → feishu 插件
│   ├── feishu-perm → feishu 插件
│   └── feishu-wiki → feishu 插件
└── workspace/skills/                # Workspace skills（优先级 1，最高）
    └── car-poi/SKILL.md             # 覆盖 managed skills 版本
```

### 第二步：Session 启动时生成 Skill 索引

每次新建会话时，Gateway 从收集到的 skill 列表生成 `<available_skills>` XML，注入到 LLM 的 system prompt 中。这个 XML **只包含 name 和 description**，不包含 SKILL.md 的完整内容：

```xml
<available_skills>
  <skill name="car-nav" location="~/.openclaw/skills/car-nav/SKILL.md">
    Control BYD car navigation via Map Protocol SDK + AMap route planning...
  </skill>
  <skill name="car-poi" location="~/.openclaw/workspace/skills/car-poi/SKILL.md">
    AMap POI search with rich data parsing and LLM-based recommendation...
  </skill>
  <skill name="a2ui-generation" location="~/.openclaw/skills/a2ui-generation/SKILL.md">
    Generate A2UI cards...
  </skill>
  ...
</available_skills>
```

**关键特点：**
- car-nav (778行) 在索引中只占约 2 行（name + description）
- car-poi (313行) 同样只占约 2 行
- 20+ 个 skill 的索引总共只占几百 token，不浪费 context

### 第三步：LLM 按需读取完整 Skill

当用户发送消息时，LLM 看到 skill 索引列表。如果用户意图匹配某个 skill 的触发词（如 "导航去XX" 匹配 car-nav，"附近有什么好吃的" 匹配 car-poi），LLM 通过 `read` 工具读取对应 SKILL.md 的完整内容。

**渐进式加载示例：**

```
用户：导航去附近的加油站

LLM 内部推理：
  → 用户要导航，匹配 car-nav skill
  → 调用 read ~/.openclaw/skills/car-nav/SKILL.md
  → 加载 778 行完整 skill 内容
  → 按指令执行：/location → aroundSearch("加油站") → select(1)
  → 回复："最近的加油站是中石化XX站，600米，正在为您导航"

context 中此时只有 car-nav 被完整加载，car-poi 和其他 skill 仍是索引状态。
```

```
用户：附近有什么好吃的日料推荐

LLM 内部推理：
  → 用户要搜索推荐，匹配 car-poi skill
  → 调用 read ~/.openclaw/workspace/skills/car-poi/SKILL.md
  → 加载 313 行完整 skill 内容
  → 按指令执行：/location → regeo → around 搜"日料" → LLM 推荐前3
  → 回复："找到3家评分4.5以上的日料：1)XX评分4.7..."

此时 car-poi 被加载，之前可能加载过的 car-nav 在 context 中（如 compaction 未清除）。
```

### 第四步：Skill 内容在 Session 中的生命周期

- **Session 级别静态**：skill 索引在 session 启动时生成快照，同一 session 内不会更新
- **内容按需驻留**：读取后的 SKILL.md 内容进入对话 context，受 compaction 策略管理
- **更新需新 session**：修改 SKILL.md 后需新建 session 才生效

## car-nav 和 car-poi 的协作机制

两个 skill 通过 AGENTS.md 中的规则和 skill 自身的描述实现协作：

1. **car-nav 的 description** 中明确标注触发词（"导航去XX"、"取消导航"、"先去A再到B"...）
2. **car-poi 的 description** 中明确标注触发词（"附近有什么好吃的"、"评分最高的日料"、"推荐一个XX"...）
3. **car-nav SKILL.md** 中写明：POI 搜索类意图转交 car-poi（"如果用户要搜索 POI，转到 car-poi skill"）
4. **car-poi SKILL.md** 中写明：导航执行转交 car-nav（"用户最终确认要导航，转到 car-nav skill"）
5. **AGENTS.md** 中写明全局规则：导航用 car-nav，搜索用 car-poi

**协作流程示例：**

```
用户："附近评分最高的日料，导航过去"

→ LLM 先读 car-poi（搜索意图）
  → 执行 aroundSearch("日料") → 解析评分 → 推荐 top 1
  → 用户确认后，car-poi 指示"转到 car-nav skill"

→ LLM 再读 car-nav（导航意图）
  → 用 car-poi 搜索结果的坐标调用 naviToPoi
  → 完成导航
```

## car-poi 的两层部署

car-poi 存在两个版本：

| 位置 | 版本 | 说明 |
|------|------|------|
| `~/.openclaw/skills/car-poi/` | 基础版 | managed skills 目录 |
| `~/.openclaw/workspace/skills/car-poi/` | 覆盖版 | workspace skills 目录（优先级更高） |

Workspace skills 优先级最高，所以实际生效的是 workspace 版本。这允许在不修改 managed skills 的情况下，针对特定 workspace 做定制。

## 配置文件

相关配置在 `/data/local/tmp/openclaw-home/.openclaw/openclaw.json`：

- `plugins.allow` — 控制哪些插件可被激活（影响插件自带 skill 的发现）
- `skills.entries` — 可单独启用/禁用某个 skill（当前未使用）
- `skills.load.extraDirs` — 额外 skill 目录（已知有 bug，未使用）

## 更新 Skill 的操作流程

1. 修改本地 `kaka_skills/car-nav/SKILL.md`
2. 推送到车机：`adb push kaka_skills/car-nav/SKILL.md /data/local/tmp/openclaw-home/.openclaw/skills/car-nav/SKILL.md`
3. **必须新建 session**（skill 快照在 session 启动时生成，session 内不更新）
4. 可通过飞书/前端发一条新消息触发新 session

## 注意事项

- **文件权限**：`~/.openclaw/` 下文件必须属于 `u10_a150`（openclaw 进程用户），不能是 root 或 shell
- **AGENTS.md 按 session 加载**：修改 AGENTS.md 后需新建 session 才生效
- **Workspace skills 覆盖**：`workspace/skills/` 中的 car-poi 会覆盖 `skills/` 中的版本，更新时注意推送到正确位置
