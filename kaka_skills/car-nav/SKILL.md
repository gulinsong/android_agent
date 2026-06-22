---
name: car-nav
description: Control BYD car navigation via Map Protocol SDK + AMap route planning. Used for navigation actions and route queries. Triggers: "导航去XX", "取消导航", "先去A再到B", "导航回家", "去XX多远", "走哪条路最快", "不走高速", "路上找个加油站", "还有多远", "中途加个XX", "打开地图", "关闭地图", "返回导航", "我在哪", "换一条路", "路线刷新", "导航声音", "地图放大", "设为家", "沿途找", "沿途搜", "前面多远"
tools:
  - bash
---

# 导航控制与路线规划（BYD Map SDK + 高德路线 API）

通过 BYD 地图 Protocol SDK 控制车机导航，高德 API 查询路线/距离。回复简短自然，适合语音播报。

## 规则
- 执行完导航指令后再回复用户，一句话说清结果，不要分两次回复
- 禁止使用高德地图（com.autonavi.minimap）和 Google Maps
- 禁止自己编造命令，只使用本文件列出的命令
- **所有导航操作通过 HTTP API 执行**
- 如果用户要搜索 POI（"附近有什么好吃的"、"评分最高的日料"等），转到 car-poi skill
- **"沿途搜XX"、"路上找个XX"属于沿途搜索，归 car-nav 处理（自动加途经点），不要转给 car-poi**
- **用户说"先去A再去B"、"顺路去XX"、"中途去XX"、"路上先经过XX"、"顺道去XX"等涉及中途停靠的，必须用 naviViaPass（带途经点导航），禁止分两次导航。记住最终目的地坐标，用途经点一次性规划路线。**
- **沿途搜、中途加途经点时直接选最近/最合适的第1个结果，自动加途经点导航，不要二次问用户，不要让用户点屏幕选择。**
- **STT 地名纠错**：语音输入的地名常被 STT 识别为同音/近音错误字。先按原文搜索，若无结果或地名不像真实地名，根据拼音联想纠错重试。示例：教长委→校长围、固蜀→固戍、摄口→蛇口、明志→民治、板田→坂田、关兰→观澜、沙景→沙井。**不要问用户确认，直接纠错后执行。**

## HTTP API 调用方式

```bash
api() { LD_LIBRARY_PATH=/data/local/tmp/node-lib OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf /data/local/tmp/node-termux -e 'const http=require("http"),d=process.argv[1],o=JSON.parse(process.argv[2]||"{}"),r=http.request({hostname:"127.0.0.1",port:18802,path:d,method:"POST",headers:{"Content-Type":"application/json",Connection:"close"},timeout:45000},res=>{let b="";res.on("data",c=>b+=c);res.on("end",()=>console.log(b))});r.write(JSON.stringify(o));r.end()' "$1" "$2"; }

amap() { LD_LIBRARY_PATH=/data/local/tmp/node-lib OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf /data/local/tmp/node-termux -e 'const https=require("https"),url=process.argv[1];https.get(url,res=>{let b="";res.on("data",c=>b+=c);res.on("end",()=>console.log(b))}).on("error",e=>console.log("ERR:"+e.message))' "$1"; }
```

## 地图应用控制

### 打开地图

```bash
api /launch '{"package":"com.byd.launchermap","activity":"com.byd.automap.activity.MainActivity"}'
```

### 返回导航（导航中切回地图）

```bash
# SDK 方式（推荐）
api /map/backToMap '{"type":0}'
# 备选：直接启动地图
api /launch '{"package":"com.byd.launchermap","activity":"com.byd.automap.activity.MainActivity"}'
```

### 关闭地图/退出地图

```bash
# SDK 方式（推荐，正常退出地图）
api /map/closeMap '{"type":0}'
# 备选：HOME 键回桌面（不取消导航）
api /keyevent '{"keycode":3}'
```

## 获取车辆位置

```bash
api /location '{}'
```
返回 `{"ok":true,"lat":"22.xxx","lng":"114.xxx"}`。GCJ-02 坐标系，可直接用于高德 API。

**GPS 初始化**：
- 开机后需通过 ADB 启动 GPS 监控：`adb shell "nohup /system/bin/sh /data/local/tmp/gps-monitor.sh >/dev/null 2>&1 &"`
- 或运行完整启动脚本：`adb shell "sh /data/local/tmp/start-car-agent.sh"`
- GPS 不可用时导航仍可用（aroundSearch 用车机自身 GPS），但高德 API 查询需降级

## 高德 API Key

```
AMAP_KEY=09bb8ccee8c03099fb0063ea95a8e5d5
```

## 导航操作

### 带坐标导航（配合 car-poi 搜索结果使用）

```bash
api /map/naviToPoi "{\"poiName\":\"POI名称\",\"lat\":\"纬度\",\"lng\":\"经度\",\"preference\":0}"
```
高德 location 格式 `经度,纬度`（如 `114.049883,22.550607`），拆分时 lng=114.049883, lat=22.550607。
naviToPoi 是 fire-and-forget，立即返回 `{"ok":true}`，导航几秒后开始。

### 一步导航（不需要用户选择）

**方式 A：车机 SDK（推荐，自动用车机 GPS）**
```bash
api /map/aroundSearch '{"keyword":"加油站"}'
api /map/select '{"index":1}'
```

**方式 B：BYD 自带一步搜索+导航**
```bash
api /map/navi '{"keyword":"肯德基","index":1}'
```

### 回家 / 去公司
```bash
api /map/home '{}'
api /map/office '{}'
```
如果 `/map/home` 或 `/map/office` 返回超时/失败，从 MEMORY.md 中查找"家"或"公司"的地址名称，改用 `api /map/naviToPoi '{"poiName":"智慧家园"}'` 导航。

### 路线偏好

`naviToPoi` 和 `naviViaPass` 的 `preference` 参数（位掩码，可组合）：

| 值 | 含义 |
|---|------|
| 0 | 高德推荐（默认） |
| 1 | 躲避拥堵 |
| 2 | 避免收费 |
| 4 | 不走高速 |
| 8 | 高速优先 |
| 16 | 大路优先 |
| 32 | 速度最快 |
| 64 | 智驾优先 |

组合：`3` = 躲避拥堵+避免收费，`34` = 速度最快(32)+避免收费(2)

```bash
# 不走高速
api /map/naviToPoi '{"poiName":"加油站","lat":"22.55","lng":"114.05","preference":4}'
# 躲避拥堵+大路优先
api /map/naviViaPass '{"poiName":"公司","lat":"...","lng":"...","passPoiName":"加油站","passLat":"...","passLng":"...","preference":17}'
```

## 途经点

SDK 原生 addViaPoi (31014) 在此版本不可用（返回错误 10023）。addViaPoi 接口内部使用 **取消当前导航 + naviViaPass (31005) 重新规划** 实现。只支持 1 个途经点。多个途经点需分段导航。

### 导航前（1个途经点）："先去A再去B"
```bash
api /map/naviViaPass '{"poiName":"目的地","lat":"22.55","lng":"114.05","passPoiName":"途经点","passLat":"22.53","passLng":"114.07"}'
```

### 导航中加途经点："中途加个加油站"
```bash
# addViaPoi 自动取消当前导航并带途经点重新规划（需要先有活跃导航目标）
api /map/addViaPoi '{"poiName":"加油站","lat":"...","lng":"..."}'
# 注意：系统会记住最近一次 naviToPoi/naviViaPass 的目的地，addViaPoi 自动使用
```

### 多个途经点（3+地点）
需分段导航，每段最多 1 个途经点：
```bash
# 第1段：当前位置 → A
api /map/naviToPoi '{"poiName":"A","lat":"...","lng":"..."}'
# 到达A后
# 第2段：A → B → C
api /map/naviViaPass '{"poiName":"C","lat":"...","lng":"...","passPoiName":"B","passLat":"...","passLng":"..."}'
```

### 删除途经点

> ⚠️ 仅在**导航中且有途经点**时调用。无导航或无途经点时不要调用 delViaPass。

```bash
# 先确认导航中
api /map/naviState '{}'
# → {"ok":true,"navi":true,...} 才能操作

# 删除全部途经点
api /map/delViaPass '{}'

# 删除第N个途经点（index: 1/2/3）
api /map/delViaPass '{"index":1}'
```

## 取消导航
```bash
api /map/cancel '{}'
```

## 查询导航状态
```bash
api /map/naviState '{}'
# 返回 {"ok":true,"navi":true/false,"foreground":true/false}
```

---

## 导航控制（SDK 高级功能）

### 路线切换（多路线选择）

导航规划出多条路线时，切换到指定路线：

```bash
# 选择第 N 条路线并导航（0-based）
api /map/selectRoute '{"actionType":1,"opera":0}'
# 选择第 N 条路线（仅选择不导航）
api /map/selectRoute '{"actionType":2,"opera":1}'
# 直接导航当前选中的路线
api /map/selectRoute '{"actionType":3,"opera":0}'
```

| actionType | 含义 |
|------------|------|
| 0 | 取消选择 |
| 1 | 选择并导航 |
| 2 | 仅选择（不导航） |
| 3 | 导航当前选中路线 |

opera = 路线索引（0=第一条，1=第二条，2=第三条）。

### 导航操作（naviOpera）

`api /map/naviOpera '{"actionType":N}'`，actionType：

| 值 | 含义 |
|---|------|
| 0 | 取消导航 |
| 1 | 全览路线 |
| 2 | 路线刷新（重新规划） |
| 5 | 切换视角 |
| 6 | 昼夜模式切换 |
| 7 | 播报模式切换 |
| 8 | 导航偏好设置（需带 `operaType`） |
| 9 | 获取当前地图模式 |

### 前方路况查询

**注意**：SDK 的 frontTrafficInfo 在实际导航中不回调，以下查询统一用**高德 API** 替代（详见后文"## 距离 / 路况 / 路线规划"）：

- 剩余距离/时间 → 高德 distance API
- 堵不堵 → 高德 direction API（duration 与直线距离对比）
- 限速 → LLM 知识（详见后文"## 道路 / 交通常识问题"）
- 目的地名称 → 从上下文记住，不要调 API

### 沿途搜索

`alongTheWaySearch` 用 SDK 原生沿途搜索，会在地图上弹结果界面让用户选——**默认不要用这个**（违反"不让用户点屏幕"原则）。

只在用户**明确**说"在地图上显示沿途加油站让我选"时用。actionType 见"可用端点"表。

默认沿途搜方案见后文"## 沿途搜索（导航中找东西）"，自动选第 1 个加途经点。

### 设置家/公司地址

```bash
api /map/setHome '{"poiName":"XX花园","lat":"22.55","lng":"114.05"}'
api /map/setCompany '{"poiName":"XX大厦","lat":"22.54","lng":"114.06"}'
```

设置后，"导航回家"/"去公司" 即可直接导航到该地址。

### 地图操作（mapOpera）

`api /map/mapOpera '{"actionType":N,"operaType":M}'`，actionType：0=缩小 / 1=放大 / 2=平移；平移时 operaType：0=上 / 1=下 / 2=左 / 3=右。

### 音量控制（volumeOpera）

`api /map/volumeOpera '{"actionType":N}'`，actionType：0=静音 / 1=取消静音 / 2=设置音量（需带 `operaType` 0-10）/ 3=增大 / 4=减小。

### 页面跳转（pageJump）

`api /map/pageJump '{"type":N}'`，type：0=设置 / 1=收藏 / 2=导航历史 / 3=壁纸 / 4=车牌 / 5=互联 / 6=行程分享 / 7=地图信息 / 8=出行记录 / 9=车队 / 10=账号登录。

### 收藏操作

```bash
# type: 2=设为家 3=设为公司（推荐，用 setHome/setCompany 更直观）
# type: 0=收藏当前位置（需要在地图POI详情页调用，直接调用会报非法参数）
# type: 1=收藏当前查看的POI（需要在地图POI详情页调用）
api /map/addFavourite '{"type":2}'
```

收藏当前位置的替代方案：用导航历史的 favorite 功能。
```bash
api /map/navHistory '{"action":"favorite","poiName":"当前位置","lat":"22.55","lng":"114.05"}'
```

---

## 距离 / 路况 / 路线规划

所有距离、时间、路况、路线比较统一用高德 API（车机 SDK 的 frontTrafficInfo 不回调，naviState 只返回布尔值）。

### 单条最速路线 / 前方路况

```bash
LOC=$(api /location '{}')
amap "https://restapi.amap.com/v3/direction/driving?origin=${lng},${lat}&destination=${DEST_LNG},${DEST_LAT}&strategy=2&extensions=all&output=JSON&key=$AMAP_KEY"
```

duration 与直线距离对比判断拥堵；steps 字段含道路名（可提取转弯后的路名）。

### 多路线比较（strategy=10 返回 3 条）

```bash
amap "https://restapi.amap.com/v3/direction/driving?origin=${lng},${lat}&destination=${DEST_LNG},${DEST_LAT}&strategy=10&extensions=all&output=JSON&key=$AMAP_KEY"
```

### 解析路线（距离/时间/过路费/红绿灯）

```bash
echo '<route_response>' | python3 -c "
import sys,json
d=json.load(sys.stdin)
paths=d.get('route',{}).get('paths',[])
for i,path in enumerate(paths[:3]):
    km=int(path.get('distance',0))/1000
    mins=int(path.get('duration',0))//60
    tolls=path.get('tolls','0')
    lights=path.get('traffic_lights','0')
    print(f'{i+1}. {km:.1f}公里 | 约{mins}分钟 | 过路费{tolls}元 | {lights}个红绿灯')
"
```

### 纯距离/时间（不要路线详情）

```bash
amap "https://restapi.amap.com/v3/distance?origins=${lng},${lat}&destination=${DEST_LNG},${DEST_LAT}&type=1&output=JSON&key=$AMAP_KEY"
# 返回 {"results":[{"distance":"12345","duration":"1800"}]}，distance 米, duration 秒
```

### strategy 参数

| 值 | 含义 |
|---|------|
| 0 | 速度最快 |
| 1 | 费用最低 |
| 2 | 距离最短 |
| 3 | 不走高速 |
| 6 | 躲避拥堵 |
| 10 | 返回3条路线比较 |
| 11 | 3条路线（避拥堵+最短+避收费） |

---

## 沿途搜索（导航中找东西）

用户说"沿途搜个洗手间"、"路上找个加油站"时，在路线前方搜索 POI 并自动加为途经点。

**前提：记住当前目的地。** 每次开始导航时必须记住 `DEST_NAME`、`DEST_LAT`、`DEST_LNG`。

```bash
# 1. 获取当前位置
api /location '{}'
# 得到 CUR_LAT, CUR_LNG

# 2. 计算路线前方点（取当前到目的地的 1/3 处，比中点更近更合理）
# FWD_LAT = CUR_LAT + (DEST_LAT - CUR_LAT) / 3
# FWD_LNG = CUR_LNG + (DEST_LNG - CUR_LNG) / 3

# 3. 在前方点附近搜索
api /map/aroundSearchAtPoi '{"poiName":"路线前方","lat":"FWD_LAT","lng":"FWD_LNG","keyword":"服务区"}'
# 注意：高速路段统一搜"服务区"（服务区内有厕所、加油站、餐厅）
# 非高速路段可直接搜用户要的东西（洗手间、加油站等）

# 4. 选择第1个结果，记住坐标
api /map/selectSearchResult '{"index":1}'

# 5. 直接 addViaPoi（系统自动取消+重新规划）
api /map/addViaPoi '{"poiName":"PASS_NAME","lat":"PASS_LAT","lng":"PASS_LNG"}'
```

完成后回复："哥，前面大概XX公里处有个服务区，已经加为途经点了，到那会提醒你。"

**记住搜索结果**：搜索返回的每条结果末尾都有坐标。记住这些坐标，用户后续说"把第X个设为途经点"时，直接用缓存的坐标调用 naviViaPass。

**行程管理**：记住完整行程列表（地点名+坐标），用于"还有几站"、"下一站去哪"等查询。行程变更（删除/调序/换途经点）一律 cancel + naviViaPass 重新规划。

## 指定道路途经点

用户说"走XX快速/XX高速去某地"时，无法直接指定走某条路，但可以把那条路上的一个点作为途经点，间接约束路线：

```bash
# 1. geocode 道路名获取路上一个点的坐标
amap "https://restapi.amap.com/v3/geocode/geo?address=南坪快速&city=深圳&output=JSON&key=$AMAP_KEY"
# 取 geocodes[0].location 作为途经点坐标

# 2. geocode 目的地
amap "https://restapi.amap.com/v3/geocode/geo?address=三洲田&city=深圳&output=JSON&key=$AMAP_KEY"

# 3. 用 naviViaPass 约束经过该道路
api /map/naviViaPass '{"poiName":"三洲田","lat":"...","lng":"...","passPoiName":"南坪快速","passLat":"...","passLng":"..."}'
```

注意：这是近似方案，导航器不一定完全沿指定道路走，但会经过途经点。

## 导航历史

每次导航开始时，目的地自动保存到本地历史文件。可查询最近去过的地点。

```bash
# 查看导航历史（最近10条）
api /map/navHistory '{}'

# 收藏/取消收藏某个历史记录
api /map/navHistory '{"action":"favorite","poiName":"XX餐厅","lat":"...","lng":"..."}'
api /map/navHistory '{"action":"unfavorite","index":2}'

# 查看收藏列表
api /map/navHistory '{"action":"favorites"}'

# 清空历史
api /map/navHistory '{"action":"clear"}'
```

## 地点别名

用户可以给地点起别名（如"妈妈家"、"老地方"、"公司二"），存储在本地，导航时自动解析。

### 使用规则

1. **用户提到的地点可能是别名**：包含人称/关系（妈妈家、老王家）、口语化描述（老地方、那个商场）、太模糊不像 POI 名（我家、外婆那里）。
2. **遇到疑似别名先 `alias get` 查**：
   - 找到坐标 → 直接 naviToPoi
   - 未找到 → 搜 POI 找地址后导航，**导航完主动问"要不要记为'XX'？"**，用户确认就 `alias set`
3. **用户主动说"把这里/把XX设为 YY"** → 获取坐标（当前位置或高德搜索）后 `alias set`
4. **同名别名再次 set 即覆盖**（"妈妈搬家了"就再 set 一次）
5. **不确定时**：先查别名 → 再搜 POI → 都没找到就问用户

### API

```bash
api /map/alias '{}'                                                # 列出所有别名
api /map/alias '{"action":"get","alias":"妈妈家"}'                 # 查询
api /map/alias '{"action":"set","alias":"妈妈家","poiName":"XX花园","lat":"22.55","lng":"114.05"}'  # 设置（覆盖）
api /map/alias '{"action":"delete","alias":"妈妈家"}'              # 删除
```

`naviToPoi` 只传 `poiName` 不传坐标时会自动解析别名。

### 别名 vs 导航历史

- **别名**：用户主动命名，永久保存，快捷导航用
- **导航历史**：自动记录，按时间查询，支持收藏

---

## 轨迹记录

每30秒自动记录一次 GPS 位置（位置变化时才记录），保留最近约10小时的轨迹。

### 查询轨迹

```bash
# 最近30分钟的轨迹
api /map/track '{"action":"recent","minutes":30}'
# 最近2小时
api /map/track '{"action":"recent","minutes":120}'
```

返回 `{"ok":true,"count":N,"track":[{"lat":...,"lng":...,"time":...},...]}`

### 清空轨迹

```bash
api /map/track '{"action":"clear"}'
```

### 轨迹相关问答

用户问"刚才经过了哪些路"时：

```bash
# 1. 获取最近轨迹
api /map/track '{"action":"recent","minutes":30}'
# 2. 每隔几个点取一个，用高德 regeo 批量查道路名
amap "https://restapi.amap.com/v3/geocode/regeo?location=${lng},${lat}&extensions=road&output=JSON&key=$AMAP_KEY"
# 3. 去重后列出经过的道路名
```

### 决策指南

| 用户意图 | 方案 |
|---------|------|
| "刚才经过了哪些路" | /map/track → 批量 regeo → 列道路名 |
| "最近去过哪些地方" | /map/navHistory 查导航历史 |
| "清空轨迹记录" | /map/track clear |

---

## 可用端点

| 路径 | JSON 参数 | 说明 |
|------|-----------|------|
| `/location` | (GET) | 获取当前 GPS 坐标 `{lat,lng}` |
| `/launch` | `{"package":"包名","activity":"Activity"}` | 启动应用 |
| `/keyevent` | `{"keycode":3}` | 发送按键（3=HOME, 4=BACK） |
| `/browse` | `{"url":"https://..."}` | 在车机浏览器打开链接 |
| `/map/aroundSearch` | `{"keyword":"加油站"}` | 周边搜索（用车机 GPS，5km），配合 select |
| `/map/select` | `{"index":1}` | 选择搜索结果第 N 个并导航 |
| `/map/naviToPoi` | `{"poiName":"名称","lat":"纬度","lng":"经度","preference":0}` | 带坐标导航 |
| `/map/naviViaPass` | `{"poiName":"终点","lat":"","lng":"","passPoiName":"途经点","passLat":"","passLng":"","preference":0}` | 带途经点导航 |
| `/map/addViaPoi` | `{"poiName":"名称","lat":"纬度","lng":"经度"}` | 导航中加途经点（自动取消+重新规划，最多1个） |
| `/map/delViaPass` | `{"index":-1}` | 删除途经点（-1=全部，1/2/3=第N个） |
| `/map/navi` | `{"keyword":"关键词","index":1}` | 一步搜索+导航 |
| `/map/home` | `{}` | 导航回家 |
| `/map/office` | `{}` | 导航去公司 |
| `/map/cancel` | `{}` | 取消当前导航 |
| `/map/naviState` | `{}` | 查询导航状态 |
| `/map/selectRoute` | `{"actionType":1,"opera":0}` | 路线切换（1=选+导航, opera=路线索引） |
| `/map/naviOpera` | `{"actionType":2}` | 导航操作（0=取消,1=全览,2=刷新,5=视角,6=昼夜,7=播报） |
| `/map/frontTrafficInfo` | `{"type":0}` | ⚠️ SDK不回调，用高德API替代 |
| `/map/alongTheWaySearch` | `{"actionType":0}` | 沿途搜索（0=加油站,1=充电站,3=洗手间,6=美食） |
| `/map/setHome` | `{"poiName":"XX","lat":"...","lng":"..."}` | 设置家地址 |
| `/map/setCompany` | `{"poiName":"XX","lat":"...","lng":"..."}` | 设置公司地址 |
| `/map/closeMap` | `{"type":0}` | 关闭地图 |
| `/map/backToMap` | `{"type":0}` | 返回地图/导航界面 |
| `/map/mapOpera` | `{"actionType":1,"operaType":0}` | 地图操作（0=缩小,1=放大） |
| `/map/volumeOpera` | `{"actionType":0}` | 音量控制（0=静音,1=取消静音,3=增大,4=减小） |
| `/map/pageJump` | `{"type":1}` | 页面跳转（0=设置,1=收藏,2=导航历史） |
| `/map/addFavourite` | `{"type":0}` | 收藏（0=当前位置,1=POI,2=设为家,3=设为公司） |
| `/map/navHistory` | `{}` 或 `{"action":"favorites"}` | 导航历史/收藏列表 |
| `/map/navHistory` | `{"action":"favorite","poiName":"","lat":"","lng":""}` | 收藏地点 |
| `/map/navHistory` | `{"action":"clear"}` | 清空历史 |
| `/map/alias` | `{}` | 列出所有别名 |
| `/map/alias` | `{"action":"set","alias":"妈妈家","poiName":"XX","lat":"","lng":""}` | 设置别名 |
| `/map/alias` | `{"action":"get","alias":"妈妈家"}` | 查询别名 |
| `/map/alias` | `{"action":"delete","alias":"妈妈家"}` | 删除别名 |
| `/map/track` | `{"action":"recent","minutes":30}` | 查询最近轨迹（默认30分钟） |
| `/map/track` | `{"action":"clear"}` | 清空轨迹 |

## 道路 / 交通常识问题

限速、路宽、限行、罚款、限号、道路编号这类**公开常识**问题，高德 API 大部分给不了——**用你的训练知识直接答**：

- **注明参考性**："根据公开信息，XX 大道限速 60，以实际标志为准"
- **不编造精确数字**，给范围（"超速一般罚 200-2000 元"）
- **涉及当前日期**（如今日限号）要结合当前日期判断
- **沿途城市**（"深圳到上海经过哪些"）用你的地理知识列举主要城市

### 需要 API 辅助的问题

| 问题 | 方案 |
|---|---|
| "我在什么路上" | `/location` + 高德 regeo（extensions=road，返回 `regeocode.road.name`） |
| "前面转弯进什么路" / "经过几条高速" | 高德 direction steps 提取 `road` / `toll_road` 字段 |
| "开了一半了吗" / "还有多久" | `/location` + 高德 distance 算已走/总距离 |
| "前面还有多少红绿灯" | 高德 direction 提取剩余 `traffic_lights` |
| "堵不堵" / "前面堵多久" | 高德 direction duration vs 直线距离对比 |

### regeo 反查道路名

```bash
amap "https://restapi.amap.com/v3/geocode/regeo?location=${lng},${lat}&extensions=road&output=JSON&key=$AMAP_KEY"
# 返回 regeocode.road.name 为当前道路名
```

### 沿途城市提取

```bash
echo '<direction_response>' | python3 -c "
import sys,json
d=json.load(sys.stdin)
paths=d.get('route',{}).get('paths',[])
if paths:
    roads=[]
    for s in paths[0].get('steps',[]):
        road=s.get('road','')
        if road and road not in roads:
            roads.append(road)
    print('途经: '+' → '.join(roads[:20]))
"
```

## 决策指南

| 用户意图 | 方案 |
|---------|------|
| "打开地图/打开导航" | launch 地图应用 |
| "关闭地图/退出地图" | HOME 键回桌面 |
| "返回导航" | naviState 检查 → launch 地图 |
| "导航去XX"（坐标已知） | naviToPoi |
| "导航去最近的加油站" | aroundSearch → select(1) |
| "导航回家/去公司" | /map/home 或 /map/office |
| "不走高速去XX" | naviToPoi preference=4 |
| "走高速去XX" | naviToPoi preference=8 |
| "躲避拥堵" | naviToPoi preference=1 |
| "速度最快且不收费" | naviToPoi preference=34 |
| "先去A再去B" | naviViaPass |
| "先去A再去B再到C"（3+地点） | 分段导航：naviViaPass（1个途经点/段） |
| "算了XX不用去了" | 从行程列表删除 → cancel → naviViaPass 重新规划 |
| "把顺序调换一下" | 重排行程，cancel → naviViaPass 重新导航 |
| "把途经点换成XX" | cancel → naviViaPass 换新途经点 |
| "中途加个XX" | addViaPoi（自动取消+重新规划） |
| "搜个XX当途经点" | 搜途经点 → addViaPoi |
| "把第X个设为途经点" | 用缓存坐标 → addViaPoi |
| "删除途经点" | /map/delViaPass |
| "删除第N个途经点" | /map/delViaPass '{"index":N}' |
| "取消导航" / "不去了" | /map/cancel |
| "走XX快速去某地" | geocode道路名→naviViaPass途经点 |
| "最近去过的餐厅" | /map/navHistory → 选目标 → naviToPoi |
| "看下我收藏的地方" | /map/navHistory favorites |
| "去XX多远/多久" | 高德 direction API → 报距离时间 |
| "走哪条路最快" | 高德 direction strategy=10 → 比较 |
| "红绿灯最少的路" | 高德 direction → 解析 traffic_lights |
| "路上找个加油站" | 中点 around 搜 → naviViaPass |
| "还有多远" | /location + 高德 distance API |
| "现在在导航吗" | /map/naviState |
| "我在哪/当前位置" | /location + 高德 regeo 反向地理编码 |
| "我现在开在什么路上" | /location + 高德 regeo |
| "前面转弯进入什么路" | 高德 direction steps 提取 |
| "附近有什么好吃的" | **转到 car-poi skill** |
| "评分最高的日料" | **转到 car-poi skill** |
| "最近的加油站"（要搜索） | **转到 car-poi skill** |
| "我想去最著名的景点"（模糊目的地） | **转到 car-poi skill** |
| "推荐一个好玩的地方" | **转到 car-poi skill** |
| "导航去妈妈家/老地方" | 查别名 → 有则导航，无则问用户地址 |
| "把这里设为XX" | location + alias set |
| "妈妈家在哪里" | alias get 查询 |
| "换一条路/走第二条路" | selectRoute actionType=1 opera=路线索引 |
| "路线刷新/重新规划" | naviOpera actionType=2 |
| "看下全路线" | naviOpera actionType=1 |
| "地图放大/缩小" | mapOpera actionType=1/0 |
| "导航声音关了/开了" | volumeOpera actionType=0/1 |
| "导航声音大一点" | volumeOpera actionType=3 |
| "设为家/设为公司" | setHome 或 setCompany |
| "沿途找加油站" | alongTheWaySearch actionType=0 |
| "前面还有多远" | 高德 distance API（frontTrafficInfo 不可用） |
| "还有多久到" | 高德 distance API |
| "前面限速多少" | LLM 知识回答 + "以实际标志为准" |
| "下一个服务区多远" | 高德 direction API 提取途经点 |
| "打开收藏" | pageJump type=1 |
| "看导航历史" | pageJump type=2 |
