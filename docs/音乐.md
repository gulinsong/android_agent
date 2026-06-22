语音与音乐通信流程
 
本文档详细描述语音系统与音乐应用之间的通信机制，包括广播唤醒、Binder IPC、命令分发和结果回调的完整流程。

> 📌 **本文档定位**：BYD 官方 mediacenter SDK 的反编译/提取资料，描述 BYD **设计意图**的 IPC 接口（含 `IServerService.postMessage`、`playById` 等）。
>
> ⚠️ **实际落地与本文档不完全一致**（2026-06-17 验证）：
> - 文档描述的 `com.byd.mediacenter.controller.MediaIPCService` + `IServerService.postMessage(...)` 在当前车机 APK 反编译输出中**未找到**——可能描述的是更新版本 mediacenter 或另一模块。
> - `playById` 方法是 BYD 设计的方法名，**我们的实现没有用它**——改用 `searchMusic` 广播（按歌名/歌手搜索并播放），更贴近用户实际意图。
> - 我们当前的实际方案见 `agent_front_app/.../music/BydMusicController.kt`：app 进程内 `Context.sendBroadcast(AUTOVOICE_COMMON_OPERATION/CONTROL)` 直发到 `com.byd.mediacenter/.voicecontrol.VoiceControlReceiver`，不 bindService、不复制 AIDL stub。
> - 实测可用的方法：`searchMusic / play / pause / next / previous`（广播） + `adjustVolume / setStreamVolume`（AudioManager）。其他方法名（如 `collect / like / playSongSheet` 等）见本文档列表，理论上也可走同样广播路径，但未逐一验证。
>
> 保留本文档作为 BYD 设计与可用方法名的完整参考资料。
 
## 架构概述
 
语音系统与音乐应用采用**双通道机制**实现跨进程通信：
 
| 通道 | 方向 | 用途 | 技术 |
|------|------|------|------|
| 入口通道 | 语音 → 音乐 | 命令传递 | 广播 + Binder |
| 出口通道 | 音乐 → 语音 | 结果返回 | Binder 回调 |
 
**设计原因**：
- **广播唤醒**：静态注册的 BroadcastReceiver 可在应用未运行时接收广播，支持冷启动
- **Binder IPC**：跨进程命令传递效率高，支持双向通信
 
## 核心组件
 
### 音乐应用侧
 
| 组件 | 类名 | 职责 |
|------|------|------|
| 广播接收器 | `VoiceControllerReceiver` | 静态注册，接收语音广播，桥接到 Binder |
| 监听器 Stub | `IBydMediaListener.Stub` | Binder 服务端，接收命令调用 |
| 控制器 | `VoiceController` | 命令解析、分发、结果回调 |
| 分发器 | `DispatcherHelper` | 将命令分发到对应音源模块 |
 
### 语音系统侧（SDK）
 
| 组件 | 类名 | 职责 |
|------|------|------|
| 服务管理 | `BYDAtVoiceServManager` | 语音服务管理，注册/注销监听器 |
| 媒体接收器 | `BYDMediaReceiver` | SDK 基类，广播 → Binder 桥接 |
| 回调 Stub | `IBydMediaCallback.Stub` | Binder 服务端，接收音乐返回的结果 |
 
## AIDL 接口定义
 
### IBydMediaListener（音乐实现，语音调用）
 
```java
public interface IBydMediaListener extends IInterface {
// 设置回调，用于返回结果
void setCallback(IBydMediaCallback callback) throws RemoteException;
 
// 控制类命令（播放/暂停/切歌）
void control(String methodName, String jsonString) throws RemoteException;
 
// 操作类命令（收藏/添加播放列表）
void operation(String methodName, String jsonString) throws RemoteException;
 
// 查询类命令（获取状态/音源列表）
void query(String methodName, String jsonString) throws RemoteException;
}
```
 
### IBydMediaCallback（语音实现，音乐调用）
 
```java
public interface IBydMediaCallback extends IInterface {
// 返回命令执行结果
void onResult(String packageName, String resultJson) throws RemoteException;
}
```
 
## 完整通信流程
 
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 语音系统进程 (Voice Service) │
│ │
│ ① 用户语音指令："播放周杰伦的歌" │
│ │ │
│ ▼ │
│ BYDAtVoiceServManager │
│ │ │
│ │ 解析指令 → methodName="play", json={artist:"周杰伦"} │
│ │ │
│ ▼ │
│ ② 发送广播 │
│ Action: com.byd.action.AUTOVOICE_COMMON_CONTROL │
│ Extra: methodName, jsonString │
│ │
└─────────────────────────────────────────────────────────────────────────────┘
│
│ 广播传递（系统 Binder）
▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 音乐应用进程 (Media App) │
│ │
│ ③ VoiceControllerReceiver │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ AndroidManifest.xml 静态注册 │ │
│ │ <receiver android:name=".VoiceControllerReceiver" │ │
│ │ android:exported="true"> │ │
│ │ <intent-filter> │ │
│ │ <action android:name="com.byd.action.AUTOVOICE_COMMON │ │
│ │ _CONTROL" /> │ │
│ │ <action android:name="com.byd.action.AUTOVOICE_COMMON │ │
│ │ _OPERATION" /> │ │
│ │ <action android:name="com.byd.action.AUTOVOICE_COMMON │ │
│ │ _QUERY" /> │ │
│ │ </intent-filter> │ │
│ │ </receiver> │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │ │
│ │ onReceive() 触发 │
│ │ getMediaListener() → 返回 bydMediaListenerStub │
│ │ getRegMediaTypes() → 返回支持的媒体类型 │
│ │ │
│ ▼ │
│ ④ BYDMediaReceiver (SDK 基类) │
│ │ │
│ │ 广播 → Binder 调用桥接 │
│ │ 内部调用 IBydMediaListener 的方法 │
│ │ │
│ ▼ │
│ ⑤ IBydMediaListener.Stub (bydMediaListenerStub) │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ val bydMediaListenerStub = object : IBydMediaListener.Stub() { │ │
│ │ override fun setCallback(callback: IBydMediaCallback?) { │ │
│ │ bydMediaCallback = callback │ │
│ │ } │ │
│ │ override fun control(methodName, jsonString) { │ │
│ │ dispatch(methodName, jsonString) │ │
│ │ } │ │
│ │ override fun operation(methodName, jsonString) { │ │
│ │ dispatch(methodName, jsonString) │ │
│ │ } │ │
│ │ override fun query(methodName, jsonString) { │ │
│ │ dispatch(methodName, jsonString) │ │
│ │ } │ │
│ │ } │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │ │
│ │ control(methodName="play", jsonString) │
│ │ │
│ ▼ │
│ ⑥ VoiceController.dispatch() │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ private fun dispatch(methodName: String, json: String?) { │ │
│ │ // 1. 解析 JSON 数据 │ │
│ │ val jsonData = json?.toJson() │ │
│ │ │ │
│ │ // 2. 确定 AudioSrc（音源） │ │
│ │ val audioSrc = VoiceConverter.convertMediaSourceToAudioSrc( │ │
│ │ jsonData?.optInt("mediaSource", MEDIA_SOURCE_NONE) │ │
│ │ ) ?: VoiceConverter.convertMediaTypeToAudioSrc(...) │ │
│ │ ?: AudioSrcManager.getActiveAudioSrc() │ │
│ │ │ │
│ │ // 3. 构建 Request │ │
│ │ val request = Request(audioSrc, RequestAppId.VOICE, │ │
│ │ methodName, jsonData) │ │
│ │ │ │
│ │ // 4. 分发命令 │ │
│ │ DispatcherHelper.ioScope.launch { │ │
│ │ val response = DispatcherHelper.dispatch(request) │ │
│ │ // 5. 构建结果 JSON │ │
│ │ val resultJson = Gson().toJson( │ │
│ │ object { │ │
│ │ val action = methodName │ │
│ │ val code = response.code │ │
│ │ val msg = response.data │ │
│ │ } │ │
│ │ ) │ │
│ │ // 6. 回调结果 │ │
│ │ bydMediaCallback?.onResult(pkgName, resultJson) │ │
│ │ } │ │
│ │ } │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │ │
│ ▼ │
│ ⑦ DispatcherHelper.dispatch() │
│ │ │
│ │ 检查通话阻断 │
│ │ 查找 DispatcherFactory │
│ │ │
│ ▼ │
│ ⑧ Dispatcher (音源模块) │
│ │ │
│ │ 根据 AudioSrc 获取对应 Dispatcher │
│ │ 调用模块的 dispatch() 方法 │
│ │ │
│ ▼ │
│ ⑨ CP Module (QQ/网易/酷狗/酷我/喜马拉雅等) │
│ │ │
│ │ 执行具体播放逻辑 │
│ │ 返回 Response(code, data) │
│ │ │
│ ▼ │
│ ⑩ 返回结果 │
│ │ │
│ │ Response → resultJson │
│ │ bydMediaCallback?.onResult(pkgName, resultJson) │
│ │ │
└─────────│───────────────────────────────────────────────────────────────────┘
│
│ Binder 回调（IBydMediaCallback.onResult）
▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 语音系统进程 (Voice Service) │
│ │
│ ⑪ IBydMediaCallback.Stub │
│ │ │
│ │ onResult(pkgName, resultJson) │
│ │ 解析结果：{ action:"play", code:0, msg:"播放成功" } │
│ │ │
│ ▼ │
│ ⑫ 处理结果 │
│ │ │
│ │ code=0 → 成功，向用户反馈 │
│ │ code!=0 → 失败，处理错误 │
│ │ │
│ ▼ │
│ ⑬ 语音反馈 │
│ │ │
│ │ TTS播报："正在为您播放周杰伦的歌" │
│ │ │
└─────────────────────────────────────────────────────────────────────────────┘
```
 
## 初始化流程
 
音乐应用启动时注册语音监听器：
 
```kotlin
// MainAppInitializer.onCreateAfterInitModule()
VoiceController.registerVoice(moduleMap.keys.toList())
 
// VoiceController.registerVoice()
fun registerVoice(supportAudioSrc: List<AudioSrc>) {
appPackageName = AppUtil.getPkgName()
val context = AppUtil.getContext()
supportMediaSources = VoiceConverter.getSupportMediaSource(supportAudioSrc)
supportMediaTypes = VoiceConverter.getSupportMediaTypes(supportAudioSrc)
 
// 注册到语音服务
BYDAtVoiceServManager.getInstance().registerMediaListener(
context,
BYDMediaConstant.AUTO_VOICE_PACKAGE,
appPackageName,
supportMediaTypes?.toIntArray(),
bydMediaListenerStub
)
}
```
 
## 支持的媒体类型
 
```kotlin
// VoiceControllerReceiver.getRegMediaTypes()
override fun getRegMediaTypes(): IntArray {
return intArrayOf(
BYDMediaConstant.MEDIA_MUSIC, // 音乐
BYDMediaConstant.MEDIA_RADIO, // 广播
BYDMediaConstant.MEDIA_NET_RADIO, // 网络电台
BYDMediaConstant.MEDIA_NEWS // 新闻/有声书
)
}
```
 
## 常用命令示例
 
| 命令类型 | methodName | jsonString 示例 |
|----------|------------|-----------------|
| 播放 | `play` | `{}` |
| 暂停 | `pause` | `{}` |
| 下一首 | `next` | `{}` |
| 上一首 | `previous` | `{}` |
| 播放指定歌曲 | `playById` | `{id:"123456", mediaSource:1}` |
| 获取状态 | `getPlayState` | `{}` |
| 获取支持音源 | `getSupportMediaSource` | `{}` |
 
## 关键设计要点
 
### 1. 静态广播接收器
 
- **目的**：支持冷启动，应用未运行时也能接收语音命令
- **配置**：`android:exported="true"` 允许外部系统调用
- **Intent Filter**：监听三种类型的广播
 
### 2. 广播与 Binder 桥接
 
`BYDMediaReceiver`（SDK 基类）负责将广播转换为 Binder 调用：
 
```
BroadcastReceiver.onReceive()
│
│ 提取 methodName, jsonString
│
▼
getMediaListener() → IBydMediaListener.Stub
│
│ 调用对应方法
│
▼
IBydMediaListener.control/operation/query()
```
 
### 3. 音源确定策略
 
命令分发时按以下优先级确定目标音源：
 
1. JSON 中指定的 `mediaSource` 字段
2. JSON 中指定的 `mediaType` 字段
3. 当前活跃音源 `AudioSrcManager.getActiveAudioSrc()`
 
### 4. 异步处理
 
所有命令在 IO 调度器异步执行，避免阻塞 Binder 调用：
 
```kotlin
DispatcherHelper.ioScope.launch {
val response = DispatcherHelper.dispatch(request)
bydMediaCallback?.onResult(pkgName, resultJson)
}
```
 
### 5. 结果 JSON 格式
 
```json
{
"action": "play",
"code": 0,
"msg": "播放成功"
}
```
 
| 字段 | 说明 |
|------|------|
| action | 原始命令名称 |
| code | 结果码（0=成功，非0=失败） |
| msg | 结果消息或数据 |
 
### 6. 三种指令类型的差异
 
三种指令类型有不同的语义和响应机制：
 
| 指令类型 | Action | 语义 | 响应方式 | 广播用途 |
|----------|---------|------|----------|----------|
| **control** | `AUTOVOICE_COMMON_CONTROL` | 控制命令（播放/暂停/切歌） | Binder回调即可 | 无需广播，结果只给语音系统 |
| **query** | `AUTOVOICE_COMMON_QUERY` | 查询命令（获取状态/列表） | Binder回调即可 | 无需广播，结果只给语音系统 |
| **operation** | `AUTOVOICE_COMMON_OPERATION` | 操作命令（收藏/添加播放列表） | Binder回调 + **广播** | 需广播通知其他组件状态变更 |
 
**operation 类型发送广播的作用**：
 
```
operation 命令执行后（如收藏歌曲）
│
├─► Binder回调 onResult()
│ │
│ └─► 告知语音系统操作成功，用于 TTS 反馈
│
└─► 发送广播（SDK 内部）
│
│ 通知其他组件状态变化
│
├─► UI 刷新收藏图标状态
├─► 其他应用同步收藏状态
└─► 数据库/缓存更新通知
```
 
**设计原因**：
- **control/query**：请求-响应模式，结果只需返回给调用方（语音系统）
- **operation**：请求-响应 + 状态广播模式，操作会改变应用状态，需通知所有相关组件
 
## 相关文件
 
| 文件 | 路径 |
|------|------|
| VoiceController | `mediacenter/src/main/kotlin/com/byd/mediacenter/controller/voice/VoiceController.kt` |
| VoiceControllerReceiver | `mediacenter/src/main/kotlin/com/byd/mediacenter/controller/voice/VoiceControllerReceiver.kt` |
| DispatcherHelper | `mediacenter/src/main/kotlin/com/byd/mediacenter/controller/dispatcher/DispatcherHelper.kt` |
| MainAppInitializer | `app/src/main/kotlin/com/byd/mediacenter/MainAppInitializer.kt` |
| AndroidManifest | `mediacenter/src/main/AndroidManifest.xml` |
 
## 扩展复用方案
 
### 场景说明
 
**需求**：新应用进程需要与音乐应用通信，类似语音系统一样发送指令给音乐，并获得执行结果。
 
```
新应用进程 ──────────────────────────────────────────────────────────►音乐进程
│ │
│ 发送指令（play/pause/next/getPlayState等） │
│ │
│ 执行指令 │
│ │ │
│ ▼ │
│ CP Module │
│ │ │
│ ▼ │
│ ◄─────────────────────────────────────── 返回结果 │
│ │
```
 
**角色对比**：
 
| 角色 | 通信方向 | 职责 |
|------|----------|------|
| 语音系统 | 语音 → 音乐 | 解析语音指令，发送命令给音乐 |
| **新应用** | 新应用 → 音乐 | 模拟语音系统，发送命令给音乐 |
| 音乐应用 | 接收端 | 处理命令，返回结果 |
 
---
 
### 方案对比
 
| 方案 | 音乐改动 | 新应用改动 | 获取结果 | 适用场景 |
|------|----------|------------|----------|----------|
| **广播模拟** | 0 行 | 5 行 | ❌ 否 | 简单控制命令，单向触发 |
| **IPC 服务** | 0 行 | 20 行 | ✅ 是 | 需要结果反馈，推荐方案 |
 
---
 
### 方案1：IPC 服务调用（推荐，音乐零改动）
 
利用音乐现有的 `MediaIPCService`，新应用直接通过 IPC 发送指令并获取结果。
 
**通信流程**：
 
```
┌─────────────────────────────────────────────────────────────────┐
│ 新应用进程 │
│ │
│ ① 绑定 MediaIPCService │
│ │ │
│ │ bindService() → 获取 IServerService │
│ │ │
│ ▼ │
│ ② 发送指令 │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ipcService.postMessage( │ │
│ │ fromAppId = "external", │ │
│ │ destAppId = "mediacenter", │ │
│ │ audioSrc = null, // 使用当前活跃音源 │ │
│ │ methodName = "play", │ │
│ │ jsonData = {}, │ │
│ │ callback = IServerCallback.Stub() │ │
│ │ ) │ │
│ └─────────────────────────────────────────────────────────┘ │
│
 
### 方案1：IPC 服务调用（推荐，音乐零改动）
 
利用音乐现有的 `MediaIPCService`，新应用直接通过 IPC 发送指令并获取结果。
 
**通信流程**：
 
```
┌─────────────────────────────────────────────────────────────────┐
│ 新应用进程 │
│ │
│ ① 绑定 MediaIPCService │
│ │ │
│ │ bindService() → 获取 IServerService │
│ │ │
│ ▼ │
│ ② 发送指令 │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ ipcService.postMessage( │ │
│ │ fromAppId = "external", │ │
│ │ destAppId = "mediacenter", │ │
│ │ audioSrc = null, // 使用当前活跃音源 │ │
│ │ methodName = "play", │ │
│ │ jsonData = {}, │ │
│ │ callback = IServerCallback.Stub() │ │
│ │ ) │ │
│ └─────────────────────────────────────────────────────────┘ │
│ │
└─────────────────────────────────────────────────────────────────┘
│
│ Binder IPC
▼
┌─────────────────────────────────────────────────────────────────┐
│ 音乐应用进程 │
│ │
│ MediaIPCService.postMessageImpl() │
│ │ │
│ │ ProcessorManager.processMessage() │
│ │ │
│ ▼ │
│ Dispatcher → CP Module → 执行播放 │
│ │ │
│ │ Response(code=0, data="播放成功") │
│ │ │
│ ▼ │
│ callback.onResult(resultJson) │
│ │
└─────────────────────────────────────────────────────────────────┘
│
│ Binder 回调
▼
┌─────────────────────────────────────────────────────────────────┐
│ 新应用进程 │
│ │
│ ③ IServerCallback.onResult(resultJson) │
│ │ │
│ │ 解析结果：{ code:0, data:"播放成功" } │
│ │ │
│ ▼ │
│ ④ 处理结果 │
│ │
└─────────────────────────────────────────────────────────────────┘
```
 
**音乐应用**：无需改动，现有 IPC 服务已支持。
 
**新应用实现代码**：
 
```kotlin
// MusicCommandClient.kt
class MusicCommandClient(private val context: Context) {
 
companion object {
const val MUSIC_PACKAGE = "com.byd.mediacenter"
// IPC 服务类名（参考 MediaIPCService）
const val IPC_SERVICE_CLASS = "com.byd.mediacenter.controller.MediaIPCService"
}
 
private var ipcService: IServerService? = null
private var connection: ServiceConnection? = null
private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
 
/**
* 绑定音乐 IPC 服务
*/
fun connect(onConnected: () -> Unit, onFailed: (() -> Unit)? = null) {
val intent = Intent().apply {
setClassName(MUSIC_PACKAGE, IPC_SERVICE_CLASS)
}
 
connection = object : ServiceConnection {
override fun onServiceConnected(name: ComponentName, service: IBinder) {
ipcService = IServerService.Stub.asInterface(service)
Log.d("MusicClient", "Connected to MusicService")
onConnected()
}
 
override fun onServiceDisconnected(name: ComponentName) {
ipcService = null
Log.d("MusicClient", "Disconnected from MusicService")
}
 
override fun onBindingDied(name: ComponentName) {
ipcService = null
onFailed?.invoke()
}
}
 
val success = context.bindService(
intent,
connection!!,
Context.BIND_AUTO_CREATE
)
 
if (!success) {
Log.e("MusicClient", "Failed to bind service")
onFailed?.invoke()
}
}
 
/**
* 断开连接
*/
fun disconnect() {
try {
connection?.let { context.unbindService(it) }
} catch (e: Exception) {
Log.e("MusicClient", "unbindService error: ${e.message}")
}
ipcService = null
connection = null
scope.cancel()
}
 
/**
* 发送命令并获取结果
*
* @param method 命令名称（play/pause/next/previous/getPlayState等）
* @param json 参数 JSON
* @param onResult 结果回调
*/
fun sendCommand(
method: String,
json: JSONObject? = null,
onResult: (Result<String>) -> Unit
) {
val service = ipcService
if (service == null) {
onResult(Result.failure("Service not connected"))
return
}
 
scope.launch {
try {
val callback = object : IServerCallback.Stub() {
override fun onResult(result: String) {
scope.launch(Dispatchers.Main) {
onResult(Result.success(result))
}
}
}
 
service.postMessage(
"external", // 来源应用ID
MUSIC_PACKAGE, // 目标应用ID
null, // 音源，null使用当前活跃音源
method, // 命令名称
json, // 参数
callback // 结果回调
)
} catch (e: RemoteException) {
onResult(Result.failure("Remote error: ${e.message}"))
}
}
}
 
// ==================== 常用命令封装 ====================
 
fun play(onResult: (Result<String>) -> Unit = {}) {
sendCommand("play", null, onResult)
}
 
fun pause(onResult: (Result<String>) -> Unit = {}) {
sendCommand("pause", null, onResult)
}
 
fun next(onResult: (Result<String>) -> Unit = {}) {
sendCommand("next", null, onResult)
}
 
fun previous(onResult: (Result<String>) -> Unit = {}) {
sendCommand("previous", null, onResult)
}
 
fun getPlayState(onResult: (Result<String>) -> Unit) {
sendCommand("getPlayState", null, onResult)
}
 
fun getSupportMediaSource(onResult: (Result<String>) -> Unit) {
sendCommand("getSupportMediaSource", null, onResult)
}
 
/**
* 播放指定歌曲
*/
fun playById(songId: String, audioSrc: String? = null, onResult: (Result<String>) -> Unit = {}) {
val json = JSONObject().apply {
put("id", songId)
audioSrc?.let { put("audioSrc", it) }
}
sendCommand("playById", json, onResult)
}
 
/**
* 收藏歌曲
*/
fun collect(songId: String, onResult: (Result<String>) -> Unit = {}) {
val json = JSONObject().apply {
put("id", songId)
}
sendCommand("collect", json, onResult)
}
}
```
 
**使用示例**：
 
```kotlin
class MyActivity : AppCompatActivity() {
private val musicClient = MusicCommandClient(this)
 
override fun onCreate(savedInstanceState: Bundle?) {
super.onCreate(savedInstanceState)
 
// 连接音乐服务
musicClient.connect(
onConnected = {
Log.d("MyApp", "音乐服务已连接")
// 查询播放状态
musicClient.getPlayState { result ->
result.onSuccess { stateJson ->
Log.d("MyApp", "播放状态: $stateJson")
}
}
},
onFailed = {
Log.e("MyApp", "连接失败")
}
)
 
// 播放按钮点击
playButton.setOnClickListener {
musicClient.play { result ->
result.onSuccess {
Toast.makeText(this, "播放成功", Toast.LENGTH_SHORT).show()
}
result.onFailure { error ->
Toast.makeText(this, "播放失败: $error", Toast.LENGTH_SHORT).show()
}
}
}
 
// 下一首按钮
nextButton.setOnClickListener {
musicClient.next()
}
}
 
override fun onDestroy() {
super.onDestroy()
musicClient.disconnect()
}
}
```
 
**优势**：
- ✅ 音乐应用零改动
- ✅ 可获取命令执行结果
- ✅ 支持双向通信
- ✅ 利用现有 IPC 权限认证机制
- ✅ 支持所有语音命令（play/pause/next/getPlayState等）
 
**依赖**：
- 新应用需要引用 `IServerService.aidl` 和 `IServerCallback.aidl`（从 middleware 模块复制）
 
---
 
### 方案2：广播模拟（单向通信，无结果反馈）
 
仅适用于不需要结果反馈的场景。
 
**通信流程**：
 
```
┌─────────────────────────────────────────────────────────────────┐
│ 新应用进程 │
│ │
│ 发送广播 │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ val intent = Intent("com.byd.action.AUTOVOICE_COMMON_ │ │
│ │ CONTROL") │ │
│ │ intent.setPackage("com.byd.mediacenter") │ │
│ │ intent.putExtra("methodName", "play") │ │
│ │ intent.putExtra("jsonString", "{}") │ │
│ │ context.sendBroadcast(intent) │ │
│ └───────────────────────────────────────────────────────────┘ │
│ │
└─────────────────────────────────────────────────────────────────┘
│
│ 广播传递（单向，无回调）
▼
┌─────────────────────────────────────────────────────────────────┐
│ 音乐应用进程 │
│ │
│ VoiceControllerReceiver → VoiceController → 执行命令 │
│ （无法返回结果给新应用） │
│ │
└─────────────────────────────────────────────────────────────────┘
```
 
**新应用实现**：
 
```kotlin
// 简单广播发送（无结果）
class SimpleMusicController(private val context: Context) {
 
fun play() {
sendBroadcast("com.byd.action.AUTOVOICE_COMMON_CONTROL", "play")
}
 
fun pause() {
sendBroadcast("com.byd.action.AUTOVOICE_COMMON_CONTROL", "pause")
}
 
fun next() {
sendBroadcast("com.byd.action.AUTOVOICE_COMMON_CONTROL", "next")
}
 
private fun sendBroadcast(action: String, method: String) {
val intent = Intent(action)
intent.setPackage("com.byd.mediacenter")
intent.putExtra("methodName", method)
intent.putExtra("jsonString", "{}")
context.sendBroadcast(intent)
}
}
```
 
**局限**：
- ❌ 无法获取执行结果
- ❌ 无法知道命令是否成功
- ❌ 不适用于查询类命令
 
---
 
### 推荐选择
 
| 需求 | 推荐方案 |
|------|----------|
| 需要结果反馈（查询状态、确认执行成功） | **方案1：IPC 服务**（音乐零改动） |
| 简单控制命令，不需要结果 | **方案2：广播模拟** |
 
---
 
### AIDL 文件获取
 
新应用需要引用以下 AIDL 文件（从 `middleware` 模块复制）：
 
```
middleware/src/main/aidl/com/byd/middleware/ipc/
├── IServerService.aidl
└── IServerCallback.aidl
```
 
复制到新应用的 `src/main/aidl/` 目录下，保持包名结构一致。
