# OpenClaw 自定义 Skill 注册指南

记录如何将自定义 skill 注册到 OpenClaw gateway，使其被 LLM 自动发现和调用。

---

## 1. 背景需求

车机助手需要 5 个自定义 skill，用于控制 LLM 回复行为：

| Skill | 功能 |
|-------|------|
| emotional-healer | 情感安抚模式 — 用温暖语气回复用户情绪化消息 |
| inspiration-catcher | 灵感捕捉 — 记录用户提到的想法，整理为清单 |
| make-friends | 社交破冰 — 根据聊天对象生成破冰话题 |
| no-reply-when-others-talk | 群聊静默 — 非目标用户发言时不回复 |
| toxic-tongue-mode | 毒舌模式 — 用尖锐幽默的方式回复 |

---

## 2. OpenClaw 插件发现机制

### 2.1 Skill 被加载的条件

OpenClaw 的 skill 发现流程（源码分析 2026-05-18）：

```
gateway startup
  → resolvePluginSkillDirs()
    → loadPluginMetadataSnapshot()
      → discoverOpenClawPlugins()
        → 扫描 3 个根目录:
           1. stock: dist/extensions/ (内置插件)
           2. global: ~/.openclaw/extensions/
           3. workspace: <workspace>/.openclaw/extensions/
        → 对每个子目录:
           a. 读 package.json → 检查 openclaw.extensions
           b. 无 extensions → discoverBundleInRoot()
           c. 还不行 → 检查 DEFAULT_PLUGIN_ENTRY_CANDIDATES
    → 检查 resolveEffectivePluginActivationState()
      → 需要 plugins.allow 列表包含插件 id
    → 遍历 plugin.skills → 收集 skill 目录
    → publishPluginSkills() → 创建 symlinks 到 plugin-skills/
```

### 2.2 关键发现

1. **package.json 是必需的** — `discoverInDirectory()` 先读 `package.json`，检查 `openclaw.extensions` 字段。没有 `package.json` 的目录不会被识别为插件。

2. **openclaw.plugin.json 的陷阱** — 当目录含 `openclaw.plugin.json` 时，`detectBundleManifestFormat()` 返回 `null`，导致 `discoverBundleInRoot()` 直接跳过。这意味着仅有 `openclaw.plugin.json` **不够**，还需要 `package.json`。

3. **plugins.allow 白名单** — `openclaw.json` 的 `plugins.allow` 控制哪些插件可被激活。不在列表中的插件即使被发现也不会启用。

4. **symlink 管理** — `publishPluginSkills()` 在 `~/.openclaw/plugin-skills/` 创建 symlinks，每次启动会清理不在 managedTargets 中的旧 symlinks。

### 2.3 参考插件结构

以 qqbot 为例，一个完整的 OpenClaw 插件需要：

```
dist/extensions/qqbot/
├── package.json              # 必需！含 openclaw.extensions
├── openclaw.plugin.json      # 插件元数据
├── dist/                     # 编译后的 JS
│   └── index.js
└── skills/                   # skill 目录
    ├── qqbot-channel/
    │   └── SKILL.md
    ├── qqbot-media/
    │   └── SKILL.md
    └── qqbot-remind/
        └── SKILL.md
```

**package.json 关键字段：**
```json
{
  "name": "@openclaw/qqbot",
  "openclaw": {
    "extensions": ["./index.ts"],
    "runtimeExtensions": ["./dist/index.js"]
  }
}
```

---

## 3. 当前进展（2026-05-18）

### 3.1 已完成

1. **创建 kaka-skills 插件目录**
   ```
   dist/extensions/kaka-skills/
   ├── openclaw.plugin.json
   └── skills/
       ├── emotional-healer/SKILL.md
       ├── inspiration-catcher/SKILL.md
       ├── make-friends/SKILL.md
       ├── no-reply-when-others-talk/SKILL.md
       └── toxic-tongue-mode/SKILL.md
   ```

2. **openclaw.plugin.json 内容：**
   ```json
   {
     "id": "kaka-skills",
     "activation": { "onStartup": false },
     "enabledByDefault": true,
     "skills": ["./skills"]
   }
   ```

3. **更新 openclaw.json** — 在 `plugins.allow` 中添加了 `"kaka-skills"`

### 3.2 已尝试的方案（均未成功）

#### ~~方案 A：添加 package.json~~（失败）

添加了 `package.json` + `index.js` + `configSchema`，gateway 启动不再报错，但 symlinks 仍未创建。

#### ~~方案 B：extraDirs config~~（有已知 bug）

在 `openclaw.json` 中配置了 `skills.load.extraDirs`，gateway 启动正常但 skill 未出现在 LLM system prompt。
已知 bug：OpenClaw issues #10386、#49873 记录了 extraDirs 在某些版本不生效。

#### ~~方案 C：手动 symlinks~~（不可靠）

`publishPluginSkills()` 每次启动会清理不在 managedTargets 中的 symlinks。

### 3.3 最终方案：Managed Skills 目录（推荐）

**官方文档**（docs.openclaw.ai/tools/skills）明确列出了 skill 加载位置和优先级：

| # | 来源 | 路径 | 优先级 |
|---|------|------|--------|
| 1 | Workspace skills | `<workspace>/skills/` | 最高 |
| 2 | Project agent skills | `<workspace>/.agents/skills/` | 高 |
| 3 | Personal agent skills | `~/.agents/skills/` | 中 |
| 4 | **Managed skills** | **`~/.openclaw/skills/`** | **中** |
| 5 | Bundled skills | 内置 | 低 |
| 6 | Extra skill folders | `skills.load.extraDirs` | 最低 |

**最简方案**：将 5 个 skill 目录复制到 `~/.openclaw/skills/`，无需插件注册、package.json 或 extraDirs 配置。

车机路径：
```
/data/local/tmp/openclaw-home/.openclaw/skills/
├── emotional-healer/SKILL.md
├── inspiration-catcher/SKILL.md
├── make-friends/SKILL.md
├── no-reply-when-others-talk/SKILL.md
└── toxic-tongue-mode/SKILL.md
```

**操作命令：**
```bash
adb shell mkdir -p /data/local/tmp/openclaw-home/.openclaw/skills
adb shell cp -r /data/local/tmp/openclaw/lib/node_modules/openclaw/dist/extensions/kaka-skills/skills/* /data/local/tmp/openclaw-home/.openclaw/skills/
```

**SKILL.md 格式要求**（YAML frontmatter）：
```markdown
---
name: emotional-healer
description: 情感安抚模式 — 用温暖语气回复用户情绪化消息
---

（具体指令内容）
```

`name` 和 `description` 为必填字段。`name` 使用小写字母、数字和连字符。

### 3.3 相关文件位置（车机）

| 文件 | 路径 |
|------|------|
| kaka-skills 插件 | `/data/local/tmp/openclaw/lib/node_modules/openclaw/dist/extensions/kaka-skills/` |
| plugin-skills 目录 | `/data/local/tmp/openclaw-home/.openclaw/plugin-skills/` |
| openclaw.json | `/data/local/tmp/openclaw-home/.openclaw/openclaw.json` |
| 源码-插件发现 | `dist/discovery-CVL9-KJt.js` |
| 源码-skill symlink | `dist/plugin-skills-79cwWJx9.js` |
| 源码-manifest注册 | `dist/manifest-registry-BiAsJcRZ.js` |
| 源码-skill加载 | `dist/workspace-B4eaH2KK.js` |

---

## 4. OpenClaw 插件 Skill 系统总结

### 4.1 Skill 加载位置和优先级

**来源：官方文档 docs.openclaw.ai/tools/skills**

| # | 来源 | 路径 | 优先级 | 作用域 |
|---|------|------|--------|--------|
| 1 | Workspace skills | `<workspace>/skills/` | 最高 | 单 agent |
| 2 | Project agent skills | `<workspace>/.agents/skills/` | 高 | 单 workspace |
| 3 | Personal agent skills | `~/.agents/skills/` | 中 | 本机所有 agent |
| 4 | **Managed skills** | **`~/.openclaw/skills/`** | **中** | **本机所有 agent** |
| 5 | Bundled skills | 随安装包发布 | 低 | 全局 |
| 6 | Extra skill folders | `skills.load.extraDirs` | 最低 | 自定义共享 |

同名 skill 冲突时，高优先级的覆盖低优先级。

### 4.2 SKILL.md 格式（YAML frontmatter）

必填字段：
- `name` — 唯一标识符，小写字母+数字+连字符
- `description` — 一行描述，展示给 LLM

可选字段：
- `metadata.openclaw.os` — 平台过滤 (`["linux"]`)
- `metadata.openclaw.requires.bins` — 需要 PATH 中存在的二进制
- `metadata.openclaw.requires.config` — 需要的配置键

### 4.3 LLM 如何使用 Skill

1. Gateway 启动时收集所有 skill，生成 `<available_skills>` XML 列表
2. 列表包含每个 skill 的 name、description、location
3. LLM 在 system prompt 中看到可用 skill 列表
4. 当用户请求匹配 skill 时，LLM 使用 `read` 工具读取 SKILL.md
5. 按 SKILL.md 中的指令执行操作
6. Skill 快照在 session 启动时生成，同一 session 内不会更新

### 4.4 Config 覆盖

可在 `openclaw.json` 中通过 `skills.entries` 控制每个 skill：
```json
{
  "skills": {
    "entries": {
      "emotional-healer": { "enabled": true },
      "toxic-tongue-mode": { "enabled": false }
    }
  }
}
```

### 4.5 插件 Skill（备选方案）

插件可以附带 skills（通过 `openclaw.plugin.json` 的 `skills` 字段），但加载优先级与 extraDirs 相同（最低），且需要完整的插件注册流程。对纯 skill 需求，建议使用 managed skills 目录。

---

## 5. 待办

- [ ] 复制 skill 到 managed skills 目录（方案 D — 推荐）
- [ ] 验证 SKILL.md 的 YAML frontmatter 格式（name + description）
- [ ] 重启 gateway，检查 LLM system prompt 中是否出现 5 个 skill
- [ ] 发 QQ 消息测试 skill 是否被 LLM 触发
- [ ] 清理：移除 openclaw.json 中的 extraDirs 配置和 kaka-skills 插件

## 6. 参考

- 官方文档：docs.openclaw.ai/tools/skills — Skill 加载、优先级、gating 规则
- 官方文档：docs.openclaw.ai/tools/creating-skills — 创建自定义 skill 指南
- ClawHub：clawhub.ai — 公共 skill 注册表
