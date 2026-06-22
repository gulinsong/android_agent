---
name: car-music
description: Control BYD car music player - search and play songs by name or artist, transport (play/pause/next/previous), and volume
tools:
  - bash
---

# Car Music Control

控制比亚迪车机音乐播放：搜索播放、传输控制、音量调节。回复简短自然，适合语音播报。

## 规则
- 收到音乐指令必须通过 bash 工具执行，禁止只回复文字
- 做不到的事直说
- 所有操作通过 HTTP API 执行，不要使用 am start / input / cmd media_session 等直接 shell 命令
- 所有 API 调用必须静默执行，不要在调用前后输出"好的，我来播放"等中间文字
- 执行完操作后直接回复结果，一句话搞定
- **用户没给具体歌名时，由你（LLM）用世界知识选一首具体的歌名**填到 `song` 字段。不要把"开心的歌"/"周杰伦那首很火的"这类描述性短语直接传给 API——BYD 搜索是精确匹配，传描述会搜不到
- **完全开放场景（"随便放"/"来首歌"）优先参考用户偏好**（gateway 自动注入到上下文，不用显式读文件）。偏好里有具体歌手/风格就按偏好选，否则选首大众流行曲
- 搜索播放后用**一句话**告诉用户选了什么（如"正在播放周杰伦的晴天"），不要解释为什么选这首，不要罗列备选

## HTTP API 调用方式

本设备没有 curl，使用 node 发请求。先定义 api 函数：
```bash
api() { LD_LIBRARY_PATH=/data/local/tmp/node-lib OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf /data/local/tmp/node-termux -e 'const http=require("http"),d=process.argv[1],o=JSON.parse(process.argv[2]||"{}"),r=http.request({hostname:"127.0.0.1",port:18802,path:d,method:"POST",headers:{"Content-Type":"application/json",Connection:"close"},timeout:45000},res=>{let b="";res.on("data",c=>b+=c);res.on("end",()=>console.log(b))});r.write(JSON.stringify(o));r.end()' "$1" "$2"; }
```

## 搜索播放（首选路径）

通过 BYD mediacenter 的 AUTOVOICE 广播，由 mediacenter 内部调 QQ 音乐/网易等音源。`song` 和 `artist` 至少给一个，两个都给更精确。

| 用户说 | API 调用 |
|------|----------|
| "放周杰伦的晴天" | `api /music/search '{"song":"晴天","artist":"周杰伦"}'` |
| "来首摇篮曲" | `api /music/search '{"song":"摇篮曲"}'` |
| "用网易云放青花瓷" | `api /music/search '{"song":"青花瓷","source":9}'` |

`source` 可选值：0 本地 / 4 酷我 / 5 酷狗 / 6 喜马拉雅 / 9 网易云 / 10 QQ音乐 / 12 在线。不给就用当前活跃音源。

返回 `{"ok":true,"song":"...","artist":"...","source":"..."}` 即搜索请求已发，mediacenter 会立即播放。

## 模糊请求处理（LLM 主动选歌）

用户没给明确歌名时，**由你选一首具体的歌名**填到 `song` 字段。选歌优先级：

1. 用户本次明确说的歌名/歌手 → 直接用
2. 本次对话的上下文线索（描述、歌词、情绪、场景）→ 用世界知识推断
3. 用户记忆中的音乐偏好（gateway 已自动加载到上下文，如"喜欢周杰伦"）→ 按偏好选代表作
4. 都没有 → 选首大众流行曲兜底

| 场景 | 用户说 | 你该做什么 | 调用示例 |
|---|---|---|---|
| 只给歌手 | "放点周杰伦" | 选该歌手**热门代表作**（晴天/稻香/七里香之类） | `api /music/search '{"song":"晴天","artist":"周杰伦"}'` |
| 描述性指定 | "周杰伦那首很火的" / "动画片主题曲" | 世界知识匹配具体歌名 | `api /music/search '{"song":"晴天","artist":"周杰伦"}'` |
| 情绪/场景 | "放点开心的歌" / "开车听的" | 选大众熟悉、和情绪契合的曲子 | `api /music/search '{"song":"小苹果"}'` |
| 完全开放 | "来首歌" / "随便放" / "放音乐" | **先查用户偏好**，有则按偏好；没有选首默认流行曲 | `api /music/search '{"song":"晴天","artist":"周杰伦"}'` |
| 只有歌词 | "天青色等烟雨" / "我曾经跨过山和大海" | 识别歌词 → 歌名+歌手（能确定歌手就一起给，更精确） | `api /music/search '{"song":"青花瓷","artist":"周杰伦"}'` |

### 选歌原则

- **优先热门代表作**：不选冷门，避免用户不熟
- **情绪/场景匹配**：选大众熟悉、和情绪契合的曲子，不要钻牛角尖
- **不确定时直说**："没太明白想听什么，说个歌手或歌名？"——不要瞎猜硬放

### 回复格式

搜索播放后**一句话**告诉用户选了什么，不解释、不罗列备选：
- `"正在播放周杰伦的晴天"`
- `"来一首稻香"`
- `"放了青花瓷"`

## 播放控制

| 命令 | API 调用 |
|------|----------|
| 播放 / 继续 | `api /music/play '{}'` |
| 暂停 / 停止 / 关掉 | `api /music/pause '{}'` |
| 下一首 / 切歌 | `api /music/next '{}'` |
| 上一首 / 重听 | `api /music/previous '{}'` |
| 在放什么 | `api /music/state '{}'` |

`/music/state` 返回：`{"ok":true,"state":"playing","title":"青花瓷","artist":"周杰伦","album":"我很忙","duration":240000,"position":32000}`

## 音量

| 命令 | API 调用 |
|------|----------|
| 声音大点 / 大声点 | `api /music/volume '{"direction":"up"}'` |
| 声音小点 / 小声点 | `api /music/volume '{"direction":"down"}'` |
| 音量调到 8 | `api /music/volume '{"direction":"set","level":8}'` |

音量范围 0-15。

## 决策指南

| 用户意图 | 方案 |
|---------|------|
| "播放" / "继续播放" | `/music/play` |
| "暂停" / "停止" / "停掉" / "关掉音乐" / "别放了" | `/music/pause` |
| "下一首" / "切歌" | `/music/next` |
| "上一首" / "重听" | `/music/previous` |
| "在放什么歌" / "播放状态" | `/music/state` |
| 用户明确给了歌名/歌手（"放周杰伦的青花瓷"） | `/music/search` 直接传 |
| 用户表述模糊（"放点周杰伦"/"来首歌"/"放点开心的歌"/只给歌词） | `/music/search`，按"模糊请求处理"由 LLM 选具体歌名 |
| "声音大点" / "声音小点" / "音量调到X" | `/music/volume` |

## 可用端点

| 路径 | JSON 参数 | 说明 |
|------|-----------|------|
| `/music/play` | `{}` | 播放（MediaSession + 广播双通道） |
| `/music/pause` | `{}` | 暂停（别名：`/music/stop`） |
| `/music/next` | `{}` | 下一首 |
| `/music/previous` | `{}` | 上一首 |
| `/music/state` | `{}` | 查询当前播放状态 |
| `/music/search` | `{"song":"...","artist":"...","source":N?}` | 搜索并播放 |
| `/music/volume` | `{"direction":"up\|down\|set","level":N?}` | 音量调节 |
