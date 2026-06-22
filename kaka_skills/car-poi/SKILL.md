---
name: car-poi
description: AMap POI search with rich data parsing and LLM-based recommendation. Used when user wants to find nearby places, compare ratings/prices, or get recommendations. Triggers: "附近有什么好吃的", "评分最高的日料", "最近的加油站", "人均100以下的火锅", "XX附近有没有YY", "推荐一个XX", "哪家XX好", "有没有XX", "哪里有XX", "最著名的景点", "最好的XX", "适合XX的地方", "我想去XX", "今天天气怎么样", "下雨了吗", "明天天气"
tools:
  - bash
---

# POI 搜索与推荐（高德 API + LLM 推理）

通过高德 Web Service API 搜索 POI，返回评分、价格、距离等详细数据，由 LLM 为用户做智能推荐。回复简短自然，适合语音播报。

## 规则
- **A2UI 卡片（强制）**：POI 搜索结果 ≥3 条时，文字回复后**必须**附带 A2UI POI 列表卡片（两行 JSON），照 AGENTS.md 中的 POI 卡片模板格式。禁止只给文字不给卡片。
- 搜索结果出来后直接为用户做判断和推荐，不要把原始数据甩给用户
- 禁止使用高德地图（com.autonavi.minimap）和 Google Maps
- 禁止自己编造命令，只使用本文件列出的命令
- 如果用户最终确认要导航，转到 car-nav skill 执行
- 所有 API 调用必须静默执行，不要在调用前后输出"让我查一下"、"好的我来搜索"等中间文字
- 只在搜索完成后输出一条最终推荐结果
- **STT 地名纠错**：语音输入的地名常被 STT 识别为同音/近音错误字。先按原文搜索，若无结果或地名不像真实地名，根据拼音联想纠错重试（如教长委→校长围、固蜀→固戍、摄口→蛇口）。**不要问用户确认，直接纠错后搜索。**

## HTTP API 调用方式

```bash
api() { LD_LIBRARY_PATH=/data/local/tmp/node-lib OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf /data/local/tmp/node-termux -e 'const http=require("http"),d=process.argv[1],o=JSON.parse(process.argv[2]||"{}"),r=http.request({hostname:"127.0.0.1",port:18802,path:d,method:"POST",headers:{"Content-Type":"application/json",Connection:"close"},timeout:45000},res=>{let b="";res.on("data",c=>b+=c);res.on("end",()=>console.log(b))});r.write(JSON.stringify(o));r.end()' "$1" "$2"; }
```

### 高德 API 调用

key 已内置在 `/data/local/tmp/amap.sh` 脚本中，直接调用即可，URL 中**不需要传 key 参数**：

```bash
sh /data/local/tmp/amap.sh "https://restapi.amap.com/v3/place/around?location=${lng},${lat}&keywords=测试&output=JSON"
```

## 获取车辆位置（每次搜索/天气查询前必做）

**每次搜索或查天气前必须先获取位置**，不要跳过这步直接用示例里的硬编码城市。

```bash
api /location '{}'
# 返回 {"ok":true,"lat":"22.xxx","lng":"114.xxx"}，GCJ-02 坐标系

# 用 regeo 反查当前城市和 adcode
sh /data/local/tmp/amap.sh "https://restapi.amap.com/v3/geocode/regeo?location=${lng},${lat}&output=JSON"
# 取 regeocode.addressComponent.city / adcode
```

GPS 不可用时降级用 regeo 返回的 city 走 text API。不要猜城市名。用户明确指定城市时（"广州天气"）用 geocode 获取该城市 adcode。

## 搜索 API（统一调用模式）

所有高德 API 通过 `sh /data/local/tmp/amap.sh "<url>"` 调用，key 已内置在脚本里。

| 用途 | URL |
|---|---|
| 周边搜索（按距离排序，**首选**）| `https://restapi.amap.com/v3/place/around?location=${lng},${lat}&keywords=加油站&radius=5000&offset=10&extensions=all&output=JSON` |
| 城市搜索（GPS 不可用降级）| `https://restapi.amap.com/v3/place/text?keywords=加油站&city=${city}&offset=10&extensions=all&output=JSON` |
| 指定位置附近（"XX附近的YY"）| 先 geocode XX 拿坐标，再 around 搜 |
| geocode 地址→坐标 | `https://restapi.amap.com/v3/geocode/geo?address=万象天地&city=深圳&output=JSON` |
| regeo 坐标→地名 | `https://restapi.amap.com/v3/geocode/regeo?location=${lng},${lat}&extensions=all&output=JSON` |
| 实况天气 | `https://restapi.amap.com/v3/weather/weatherInfo?city=${adcode}` |
| 预报天气（今天+未来3天）| `https://restapi.amap.com/v3/weather/weatherInfo?city=${adcode}&extensions=all` |

around 搜索参数：`keywords`（可用 `|` 组合多个，如 `日料|日本料理`）/ `radius` 米（默认 5000）/ `offset` 最多 25 / `sortrule=distance|weight` / `citylimit=true` 限定当前城市。

## 解析搜索结果

```bash
echo '<amap_response>' | python3 -c "
import sys,json
d=json.load(sys.stdin)
for i,p in enumerate(d.get('pois',[])[:10]):
    loc=p['location']
    name=p['name']
    addr=p.get('address','')
    dist=p.get('distance','')
    rating=p.get('rating','')
    cost=p.get('cost','')
    biz_ext=p.get('biz_ext',{}) or {}
    open_time=biz_ext.get('open_time','')
    parking=p.get('parking_type','')
    tel=p.get('tel','')
    parts=[f'{i+1}. {name}']
    if rating: parts.append(f'评分{rating}')
    if cost: parts.append(f'人均{cost}元')
    if dist: parts.append(f'{dist}m')
    if open_time: parts.append(f'营业{open_time}')
    if parking: parts.append(f'停车:{parking}')
    parts.append(loc)
    print(' | '.join(parts))
"
```

**extensions=all 返回的关键字段**：
- `rating` — 评分 0-5（仅餐饮/酒店/景点/影院有值）
- `cost` — 人均消费元（仅餐饮/酒店有值）
- `distance` — 距搜索中心点米数
- `biz_ext.open_time` — 营业时间
- `parking_type` — 停车类型
- `tel` — 电话
- `photos` — 图片列表

**注意**：加油站、停车场、药店等类型没有 rating/cost 数据。

## LLM 推理指南

### 筛选策略

- **评分**："4.5分以上的"、"评分最高的" → 筛选 rating >= 阈值，按评分降序
- **价格**："人均100以下"、"便宜的" → 筛选 cost <= 阈值，按价格升序
- **距离**："最近的"、"500米内的" → distance 已按距离排序，取前N个
- **组合**："4.5分以上且100以下" → 同时筛 rating 和 cost
- **否定**："不要世界之窗" → 排除包含该名称的结果

### 推荐决策

1. 按用户条件过滤结果
2. **1个符合** → 直接推荐并导航："推荐XX，评分4.7距离800米，正在为您导航"
3. **多个符合** → 列前3个简短说明："找到3家：1)XX 评分4.7 2)XX 评分4.5 3)XX 评分4.3，去哪家？"
4. **0个符合** → 放宽条件或报"没有找到完全符合的，最近的是XX，要去吗？"
5. **用户没提条件** → 按距离取第1个

### 模糊/主观目的地

用户说"最著名的景点"、"最好的商场"、"适合爬山的地方"等模糊描述时：

1. **用你的知识先提出 2-3 个候选**（如"深圳著名景点有世界之窗、欢乐谷、深圳湾公园"）
2. **用高德 geocode 或 text API 验证坐标和评分**
3. **综合你的知识 + 高德数据推荐**
4. 用户确认后转到导航

```bash
# 验证候选地点的坐标和详细信息
sh /data/local/tmp/amap.sh "https://restapi.amap.com/v3/place/text?keywords=世界之窗&city=深圳&offset=3&extensions=all&output=JSON"
```

### 模糊概念映射

用户用口语表达时，需要转换成高德能搜到的关键词：

| 用户说的 | 搜索关键词 |
|---------|-----------|
| 大块空地 | 广场、公园、运动场、操场 |
| 充电宝 | 共享充电宝、怪兽充电、街电、小电 |
| 跑步的地方 | 步道、绿道、公园、体育场 |
| 自助烧烤 | 烧烤场地、户外烧烤、农家乐烧烤 |
| 钟点房 | 时租酒店、钟点房、短租 |
| 亲子房 | 亲子酒店、家庭房 |
| 取现金 | ATM、银行营业厅 |
| 垫肚子的 | 快餐、小吃、便利店 |

根据用户描述灵活组合关键词，如果第一次搜不到结果，换一组关键词重试。

### 状态推断

有些问题高德没有直接答案，但可以从已有数据推断：

- **"前面撞了吗"** → 用 direction API 查路线，如果某段 duration 异常长，告知"前方X公里处车流缓慢，可能堵车了"
- **"经过加油站停一下"** → 搜路线上最近的加油站作为途经点，告知用户"到加油站时停一下"
- **"不走高速"但用户问"能省多少时间"** → 两次 direction 调用（一次走高速一次不走），对比时间差
- **"堵不堵"** → direction API 的 duration 与直线距离推算的预期时间对比

### 用 LLM 知识补充高德没有的实时数据

高德数据只有结构化字段（名称/坐标/评分），用户问的**实时状态**（空位/排队/优惠/库存）和**业务常识**（连锁店规则/品牌差异）都要用你的训练知识答：

- **空位/排队**：根据时间段 + 品牌热度预测。"现在工作日上午，加油站一般不排队"；饭点（11:30-13:00, 17:30-20:00）热门餐厅大概率要等位
- **优惠/活动**：根据品牌常识答（海底捞有会员、星巴克有星享俱乐部、连锁餐厅基本都有美团团购），注明"具体以店内为准"
- **油价/洗车价**：根据常识判断品牌差异（私营加油站通常比国营优惠多）
- **业务规则**：连锁药店基本支持医保、大型商场有母婴室等

**回复必须注明这是预估/常识**："搜到附近3家连锁药店，一般都支持医保，推荐最近的XX" / "现在是午饭高峰，海底捞一般要等30分钟以上，实际以到店为准"。

### 用户明确要看美团/点评

```bash
api /browse '{"url":"https://i.meituan.com"}'        # 美团 H5
api /browse '{"url":"https://m.dianping.com"}'       # 大众点评 H5
```

告知用户："已打开美团页面，停车后可以查看详细优惠和排队信息"。

### 主观判断优先级

| POI类型 | 推荐优先级 |
|---------|-----------|
| 餐饮 | 评分 > 价格 > 距离 |
| 加油站/停车场 | 距离 > 品牌 |
| 酒店 | 评分 > 价格 > 距离 |
| 景点 | 评分 > 距离 |
| 通用 | 距离 > 评分（如果无评分） |

### 回复格式（语音播报）

- 单推荐："最近的加油站是中石化XX站，600米，正在为您导航"
- 多推荐："找到3家评分4.5以上的日料：1)XX评分4.7人均120 2)XX评分4.6人均85 3)XX评分4.5人均150，去哪家？"
- 无结果："附近5公里内没找到XX，要不要扩大范围？"

**重要**：搜索结果的坐标（每条末尾的 `lng,lat`）必须保留在对话上下文中。用户可能后续说"把第2个设为途经点"、"搜个XX当途经点"，此时需要用缓存的坐标调用 car-nav 的 naviViaPass。

## 用户确认导航后

用户选定目标后，记住 POI 名称和坐标（`location` 字段，格式 `lng,lat`），调用：

```bash
api /map/naviToPoi "{\"poiName\":\"POI名称\",\"lat\":\"纬度\",\"lng\":\"经度\"}"
```

拆分 location 时：`114.049883,22.550607` → lng=114.049883, lat=22.550607

也可用车机 SDK 一步导航（不需要坐标）：
```bash
api /map/navi '{"keyword":"肯德基","index":1}'
```

## 决策指南

| 用户意图 | 方案 |
|---------|------|
| "附近的XX" | around 搜 → 解析 → 推荐前3个 |
| "附近有什么好吃的" | around 搜"美食" → 解析评分/价格 → 推荐 |
| "XX附近有没有YY" | geocode XX → around 搜YY → 报结果 |
| "最近的加油站" | around 搜 → 按距离取第1个 |
| "评分最高的日料" | around 搜"日料" → 按rating排序 → 推荐 |
| "人均100以下的火锅" | around 搜"火锅" → 筛选cost → 推荐 |
| "最便宜的停车场" | around 搜"停车场" → 取最近（停车场无价格） |
| "有停车位的商场" | around 搜"商场" → 检查parking_type |
| "推荐一个XX" | around 搜 → 综合评分距离推荐 |
| "导航去最近的XX" | around搜 → 第1个 → naviToPoi |
| "哪里有XX" | around搜 → 列出前3个 |
| "有没有XX" | around搜 → 报有没有，有的话列出来 |
| "最著名的景点" | LLM知识提候选 → 高德验证坐标评分 → 推荐 |
| "适合XX的地方" | LLM知识+高德text搜 → 推荐 |
| "我想去XX"（XX是模糊描述） | LLM知识提候选 → 高德验证 → 用户选 → 导航 |
| "今天天气怎么样"/"下雨了吗" | 高德天气 API → 报天气温度风力 |
| "明天适合出游吗" | 高德天气预报(extensions=all) → 报未来几天 |
| "广州天气怎么样" | 天气 API 换城市 adcode |
| "这家店有没有优惠/活动" | LLM 知识回答，注明"以实际为准" |
| "XX要排多久队/人多吗" | 基于时间段 + 品牌热度预测，注明预估 |
| "帮我看看美团上的优惠" | /browse 打开美团 H5 |
| "打开大众点评" | /browse 打开大众点评 H5 |
