# OMS 人脸视频流服务 — yocto 侧部署（移植指南）

> 给 faceid/ID管理 tab 提供实时人脸帧的 yocto 侧服务。移植到新车机时按本文操作。

## 架构

```
yocto (192.168.195.47)                         android app (com.openclaw)
  boscamsrc OMS_R 摄像头                          OkHttp 跨域拉流
    ↓ gst pipeline                                 ↓
  oms-grab.service                              LiveVideoFaceFragment
    → /data/openclaw/oms-frames/f_XXXXX.jpg      http://192.168.195.47:18080/frame
    ↓                                              ↓
  oms-http.service                             FaceRecognizer.recognize()
    GET /frame → 返回最新 jpg
```

两个域、两台 adb 设备：
- `LZBYDUMNB6RW7X5P` — android IVI（app + gateway）
- `LZBYDUMNB6RW7X5P_YOCTO` — yocto Linux（OMS 服务）

## 文件清单（yocto 侧）

| 路径 | 职责 |
|------|------|
| `/data/openclaw/oms-stream.sh` | gst 抓帧脚本：`boscamsrc sensor=OMS_R` 1920x1080 → 缩到 960x540 → jpeg → `multifilesink` 滚动保留最新 3 帧 |
| `/data/openclaw/oms-http.py` | HTTP 单帧服务：`GET /frame` 返回最新 jpg，`GET /` 健康检查 |
| `/data/openclaw/oms-frames/` | 帧输出目录（`f_00001.jpg` 滚动） |
| `/etc/systemd/system/oms-grab.service` | systemd unit（抓帧） |
| `/etc/systemd/system/oms-http.service` | systemd unit（http） |
| `/data/wayland_env_file` | wayland 环境变量（oms-stream.sh source 它，**别动**） |

> 脚本在 `/data` 分区（持久 rw ext4），不在 rootfs（rootfs 空间紧张）。

## systemd unit

`/etc/systemd/system/oms-grab.service`：
```ini
[Unit]
Description=OMS frame grabber (gst boscamsrc OMS_R -> jpeg to /data/openclaw/oms-frames)
After=network.target

[Service]
Type=simple
ExecStart=/data/openclaw/oms-stream.sh
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/oms-http.service`：
```ini
[Unit]
Description=OMS HTTP single-frame server (GET /frame)
After=oms-grab.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /data/openclaw/oms-http.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- `Restart=on-failure` + `RestartSec=3`：崩溃自动重拉
- oms-http 只 `After=` oms-grab（顺序启动，不 `Requires`——http 单独能跑，拉不到帧返回空，等 grab 出帧）
- `WantedBy=multi-user.target`：开机自启

## 移植步骤（新车机）

前提：yocto 设备能 adb 连（`adb devices` 见 `..._YOCTO`），已 root。

```bash
Y=LZBYDUMNB6RW7X5P_YOCTO   # 换成新车机的 yocto serial

# 1. 建目录 + 推脚本（从本仓库 tts-adapter 或 git 历史取 oms-stream.sh / oms-http.py）
adb -s $Y shell 'mkdir -p /data/openclaw/oms-frames'
adb -s $Y push oms-stream.sh /data/openclaw/oms-stream.sh
adb -s $Y push oms-http.py  /data/openclaw/oms-http.py
adb -s $Y shell 'chmod +x /data/openclaw/oms-stream.sh'

# 2. 推 unit
adb -s $Y push oms-grab.service /etc/systemd/system/oms-grab.service
adb -s $Y push oms-http.service /etc/systemd/system/oms-http.service

# 3. 注册 + 自启
adb -s $Y shell '
  systemctl daemon-reload && \
  systemctl enable oms-grab oms-http && \
  systemctl start oms-grab oms-http'
```

## 验证

```bash
adb -s $Y shell '
  systemctl is-active oms-grab oms-http     # active active
  systemctl is-enabled oms-grab oms-http    # enabled enabled
  ls /data/openclaw/oms-frames/ | tail -3   # 有 f_XXXXX.jpg
  wget -q -O /tmp/t.jpg http://127.0.0.1:18080/frame && echo "frame $(stat -c%s /tmp/t.jpg) bytes"'
```

android 侧确认拉流：`adb -s LZBYDUMNB6RW7X5P logcat | grep LiveVideoFace` 应见 `recognize: ... detScore=...`（非 NO_FACE）。

## 依赖（yocto 镜像需含）

- `gst-launch-1.0` + 插件：`boscamsrc`（MTK 车载摄像头）、`v4l2convert`、`videoscale`、`videoconvert`、`jpegenc`、`multifilesink`、`queue`
- `python3`（http 服务）
- `/data/wayland_env_file`（wayland env，boscamsrc 需要）

## 已知坑

- **rootfs（/）容易满**（yocto 系统 4.7G，/usr 3.3G 刚性）。push unit 到 `/etc` 前若 `No space left`，清 `/root/.npm`（npm cache，174M）或 `/root/.openclaw`（旧安装，655M，**确认不用再清**）腾空间。脚本/unit 不大，清几百 KB 就够。
- 旧版用 `systemd-run --unit=oms-grab ...`（transient，重启丢）。**已改持久 unit + enable**，transient 命令仅作 fallback。
- oms 文件原在 `/data` 根（脏），已迁 `/data/openclaw/`（yocto 侧 openclaw 既有目录，含 `openclaw.tar.gz`）。**android 侧的 `/data/local/tmp/` 是另一回事**（openclaw-home/amap/ai-news 在那，android 域，不混）。
- 跨域网络：android eth0 `192.168.195.2` ↔ yocto br0 `192.168.195.47`，端口 18080。

## android 侧拉流代码

`LiveVideoFaceFragment` / `OmsFrameSource`：
- URL: `http://192.168.195.47:18080/frame`
- OkHttp GET → `BitmapFactory.decodeByteArray` → recognize
