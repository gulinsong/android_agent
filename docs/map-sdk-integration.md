# BYD 地图导航 SDK 集成

## Context

当前 car-nav 技能通过无障碍服务操控地图 App（点击UI元素），但比亚迪地图的自定义 View 不响应无障碍点击，导致导航功能从未成功过。需要改用 BYD 地图 Protocol SDK（AIDL），直接调用地图 App 的原生接口。

## 逆向分析结果

已从车机地图 APK (`com.byd.launchermap`, `/product/app/BydLaunchermap/BydLaunchermap.apk`) 反编译提取出完整的 AIDL 接口。

### AIDL 服务信息

- **Service Action**: `action.com.autosdk.protocol.ProtocolService`
- **Service 实现**: `com.autosdk.protocol.service.ProtocolService`
- **AIDL 接口**: `com.autosdk.protocol.IProtocolAidlInterface`
- **回调接口**: `com.autosdk.protocol.listener.IProtocolCallback`
- **数据模型**: `com.autosdk.protocol.model.base.ProtocolBaseModel` (Parcelable)
- **错误模型**: `com.autosdk.protocol.service.ProtocolErrorModel` (extends ProtocolBaseModel)

### IProtocolAidlInterface 方法

| 方法 | 说明 |
|------|------|
| `setProtocolModelData(ProtocolBaseModel)` | **核心方法** — 发送操作指令 |
| `registCallBack(IProtocolCallback)` | 注册回调 |
| `registerCallBack(IProtocolCallback, int)` | 注册带ID的回调 |
| `getNaviState()` → boolean | 是否在导航中 |
| `isForegroundState()` → boolean | 地图是否在前台 |
| `getMapState(int type)` → String | 查询地图状态（JSON） |
| `setICompatibleIDVersion(int)` | 设置兼容版本 |
| `setVoiceDeepSearchModelData(VoiceDeepSearchModel)` | 深度搜索 |
| `setCateringInfoListener(CateringInfoListener)` | 餐饮信息监听 |

### IProtocolCallback 方法

| 方法 | 说明 |
|------|------|
| `onSuccess(String)` | 操作成功，返回 JSON 字符串 |
| `onJSONResult(String)` | JSON 结果回调 |
| `onFail(ProtocolErrorModel)` | 操作失败 |

### ProtocolBaseModel 字段（Parcelable 序列化顺序）

```
protocolID, timeStamp, callbackId, protocolVersion(String), packageName,
var1, actionType, operaType, searchKey, destPoiName, errorCode,
destLatitude, destLongitude, passPoiName, passLatitude, passLongitude,
isMainCab(boolean), isNavi(boolean), isWaypoint(boolean), searchQueryType
```

### ProtocolID 常量

| 常量 | 值 | 说明 |
|------|---|------|
| `PROTOCOL_KEYWORD_SEARCH` | 30300 | 关键字搜索 |
| `PROTOCOL_SEARCH_RESULT_SELECT` | 31003 | 选择搜索结果 |
| `PROTOCOL_GOTO_HOME_COMPANY` | 30010 | 导航回家/去公司 |
| `PROTOCOL_NAVI_TO_POI` | 31004 | POI直接导航 |
| `PROTOCOL_CHECK_HOME_OR_COMPANY` | 30020 | 检查家/公司设置 |
| `PROTOCOL_SET_HOME` | 60000 | 设置家 |
| `PROTOCOL_SET_COMPANY` | 60001 | 设置公司 |
| `PROTOCOL_NAVI_HOME` | 60002 | 导航回家 |
| `PROTOCOL_NAVI_COMPANY` | 60003 | 导航去公司 |
| `PROTOCOL_NAVI_HOME_NOT_SET_HOME` | 60004 | 设置家并导航 |
| `PROTOCOL_NAVI_COMPANY_NOT_SET_COMPANY` | 60005 | 设置公司并导航 |
| `PROTOCOL_SEARCH_EN_ROUTE` | 30302 | 沿途搜索 |
| `PROTOCOL_DISMISS` | 34000 | 关闭 |

### ProtocolBaseModel 在 doOperate 中的处理逻辑

```java
switch (protocolID) {
    case 30000: // 地图操作 (缩放/路况)
    case 30001: // 回地图
    case 30002: // 关闭地图
    case 30003: // 沿途搜索
    case 30010: // PROTOCOL_GOTO_HOME_COMPANY — 导航回家/去公司
    case 30011: // 导航操作 (视角切换)
    case 30300: // PROTOCOL_KEYWORD_SEARCH — 关键字搜索
    case 30301: // 周边搜索
    case 30302: // 沿途搜索
    case 30404: // requestFrontTrafficInfo — 前方路况
    case 30406: // naviOpera — 导航操作
    case 31003: // PROTOCOL_SEARCH_RESULT_SELECT — 选择搜索结果
    case 31004: // PROTOCOL_NAVI_TO_POI — POI直接导航
    case 31005: // 途经点导航
    case 31008: // 偏好设置
    case 31009: // 音量控制
    case 31014: // 添加收藏
    case 31015: // 我的位置
    case 34000: // PROTOCOL_DISMISS — 关闭
}
```

## 需要的导航操作（按优先级）

### P0 - 必须实现
1. **关键字搜索** — `protocolID=30300`, `searchKey="目的地"`
2. **选择搜索结果** — `protocolID=31003`, `operaType=N` (1-based)
3. **导航回家** — `protocolID=30010`, `actionType=60002`
4. **导航去公司** — `protocolID=30010`, `actionType=60003`
5. **取消导航** — `protocolID=30406`, `actionType=0`

### P1 - 很有用
6. **导航状态查询** — `getNaviState()` / `getMapState(type)`
7. **路线偏好** — `operaType` 参数
8. **途经点导航** — `passPoiName` + `isWaypoint=true`
9. **前方路况** — `protocolID=30404`

## 实施步骤

### Step 1: 创建 AIDL 接口文件

不需要写 .aidl 文件 — 直接用反编译得到的 Java Stub 类。将其转为 Kotlin 放入项目：

在 `agent_front_app/app/src/main/java/com/openclaw/car/map/` 下：
- `IProtocolAidlInterface.kt` — 从反编译的 Stub 转换
- `IProtocolCallback.kt` — 从反编译的 Stub 转换
- `ProtocolBaseModel.kt` — Parcelable 数据模型
- `ProtocolErrorModel.kt` — 错误模型

关键：Parcelable 序列化字段顺序必须与反编译的完全一致，否则 AIDL 通信会失败。

### Step 2: 创建 MapProtocolManager

```kotlin
// service/MapProtocolManager.kt
class MapProtocolManager(private val context: Context) {
    private var service: IProtocolAidlInterface? = null
    private val callback = object : IProtocolCallback.Stub() {
        override fun onSuccess(result: String?) { ... }
        override fun onJSONResult(result: String?) { ... }
        override fun onFail(error: ProtocolErrorModel?) { ... }
    }

    fun bind() {
        val intent = Intent("action.com.autosdk.protocol.ProtocolService")
        intent.setPackage("com.byd.launchermap")
        context.bindService(intent, connection, Context.BIND_AUTO_CREATE)
    }

    // 封装操作
    fun keywordSearch(keyword: String, cb: (String) -> Unit) {
        val model = ProtocolBaseModel(30300, keyword)  // PROTOCOL_KEYWORD_SEARCH
        model.isNavi = true
        service?.setProtocolModelData(model)
    }

    fun selectResult(index: Int) {
        val model = ProtocolBaseModel(31003)  // PROTOCOL_SEARCH_RESULT_SELECT
        model.operaType = index
        service?.setProtocolModelData(model)
    }

    fun goHome() {
        val model = ProtocolBaseModel(30010)  // PROTOCOL_GOTO_HOME_COMPANY
        model.actionType = 60002  // PROTOCOL_NAVI_HOME
        service?.setProtocolModelData(model)
    }

    fun cancelNavigation() {
        val model = ProtocolBaseModel(30406)
        model.actionType = 0  // 取消导航
        service?.setProtocolModelData(model)
    }
}
```

### Step 3: 添加 HTTP API 端点

在 `UiHttpServer.kt` 添加 `/map/*` 端点：

```
POST /map/search   { "keyword": "目的地" }
POST /map/select   { "index": 1 }
POST /map/home     {}
POST /map/office   {}
POST /map/cancel   {}
POST /map/status   { "type": 0 }
```

### Step 4: 更新 car-nav 技能

重写 `kaka_skills/car-nav/SKILL.md` 使用 `/map` API。

### Step 5: 在 App 中初始化绑定

在 `OpenClawApp.kt` 或 `NodeProcessService.kt` 中初始化 `MapProtocolManager`。

## 关键文件

| 文件 | 操作 |
|------|------|
| `agent_front_app/.../map/IProtocolAidlInterface.kt` | 新建 — AIDL Stub |
| `agent_front_app/.../map/IProtocolCallback.kt` | 新建 — 回调 Stub |
| `agent_front_app/.../map/ProtocolBaseModel.kt` | 新建 — 数据模型 |
| `agent_front_app/.../map/ProtocolErrorModel.kt` | 新建 — 错误模型 |
| `agent_front_app/.../service/MapProtocolManager.kt` | 新建 — AIDL 绑定管理 |
| `agent_front_app/.../service/UiHttpServer.kt` | 修改 — 添加 /map 端点 |
| `agent_front_app/.../OpenClawApp.kt` | 修改 — 初始化绑定 |
| `kaka_skills/car-nav/SKILL.md` | 重写 — 使用 /map API |

## 验证

1. `./gradlew assembleDebug` 构建通过
2. 安装到车机，确认 AIDL 绑定成功（日志 `MapProtocolManager: service connected`）
3. `api /map/search '{"keyword":"加油站"}'` → 返回搜索结果 JSON
4. `api /map/select '{"index":1}'` → 地图开始导航
5. `api /map/home '{}'` → 地图直接导航回家
6. 通过 OpenClaw 语音说"导航去最近的加油站" → 完整链路成功
