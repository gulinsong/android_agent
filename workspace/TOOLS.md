# 车机环境
- 型号：比亚迪仰望 DiLink 300（MediaTek MTK）
- 系统：Android 14（SDK 34），SELinux permissive
- 屏幕：1728×1888 横屏，320dpi
- CPU：8 核，内存：10GB
- 音频：Dynaudio 丹拿音响

# 导航与搜索
- 导航控制：通过 car-nav skill（HTTP API 127.0.0.1:18802）
- POI 搜索：通过 car-poi skill（HTTP API 127.0.0.1:18802 + 高德 API）
- 禁止使用 car-router、nav-search.sh、nav-select.sh 等过时工具
- 禁止使用高德地图 app（com.autonavi.minimap）

# 高德 API 调用（重要）
- 高德 API key 已内置在脚本中，使用 `sh /data/local/tmp/amap.sh "URL"` 调用
- URL 中**不要传 key 参数**，脚本会自动补上
- 禁止自己定义 amap 函数或手写 key
- 示例：`sh /data/local/tmp/amap.sh "https://restapi.amap.com/v3/weather/weatherInfo?city=440300"`
- 示例：`sh /data/local/tmp/amap.sh "https://restapi.amap.com/v3/place/around?location=114,22&keywords=加油站&radius=5000&extensions=all&output=JSON"`

# 音乐
- 通过 car-music skill 控制（HTTP API 127.0.0.1:18802）
- 仅音乐 app（com.byd.mediacenter）在前台时有效

# Shell 可用
- am, pm, cmd, input, settings, dumpsys
- grep, sed, awk 可用
- 无 curl，HTTP 调用用 node-termux
- 无 jq，JSON 解析用 node 或 grep/sed

# 权限边界
- /data/local/tmp/ 可读写
- 应用包名：com.openclaw.car（DiDiClaw 配置 App）
