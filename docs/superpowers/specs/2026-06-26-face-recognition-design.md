# 车内人脸识别（端侧 demo）— 设计文档

- 日期：2026-06-26
- 状态：设计已确认，待实现计划
- 目标平台：车机 BYD Yangwang · MediaTek **MT6991** · Android 14 (API 34) · arm64-v8a
- 宿主 App：`agent_front_app`（`com.openclaw.car`，Kotlin，minSdk 待 26→27）

## 1. 目标

在车机端侧跑通一条**人脸识别 pipeline**：给定一张图片（`Bitmap`），输出**最靠图像中心的那张人脸的 ID**（命中 gallery）或 `unknown`。满足**实时性**，是 demo 级别，**不过度工程**。

明确不在本期范围（见 §8）：
- 车内摄像头取帧（本期输入是 Bitmap，相机接入留后续 Phase）
- `/face/*` HTTP 端点对外暴露（本期只在 Fragment 内跑）
- 大规模 gallery / 高精度升级（ buffalo_l / R100 等留后续）

## 2. 约束与关键决策（含依据）

| 决策 | 选择 | 依据 |
|---|---|---|
| 任务 | 人脸识别（检测→选居中→对齐→嵌入→比对） | 用户需求 |
| 模型 | **YuNet**（检测，含 5 关键点）+ **ArcFace-R50**（InsightFace buffalo_l 的 `w600k_r50`，512-d 嵌入） | YuNet 无 GroupNorm/DCN、NNAPI 命中率高；R50 是普通 conv、NNAPI 友好且精度高；识别器无 delegate 坑 |
| 推理后端 | **ONNX Runtime Android + NNAPI EP**（零模型转换） | NeuroPilot 运行时是 TFLite-only（见下），ONNX→TFLite 是额外一步；NNAPI EP 同样路由到 MTK NPU，且尊重 ONNX 通用性 |
| 输入源 | **仅 Bitmap** | 先跑通算法，相机后续接 |
| Gallery | **app 内注册 UI** | 现场演示注册+识别闭环 |

**为什么不用 NeuroPilot AAR（TFLite）路径**：拆 `Android_V_neuropilot_240408.aar` 实测，`libneuropilot_jni.so` 导出符号全是 `ANeuroPilotTFLite_*`，Java 类是 `com.mediatek.neuropilot_*` 下的 `TensorFlowLite`/`InterpreterApi`/`NeuronDelegate`；SDK 编译器叫 `ncc-tflite`、shim 叫 `NeuroPilotTFLiteShim.h`。**整个 NeuroPilot 工具链无 ONNX 入口**。故"用 NeuroPilot"=强制 ONNX→TFLite 一次性转换。本期为最小摩擦选 ONNX Runtime + NNAPI；NeuroPilot AAR 路径作为后续性能/品牌升级项（见 §9）。

## 3. 架构与 Pipeline

纯 app 内运行，NNAPI EP 命中 MTK NPU。

```
Bitmap
  → 预处理（letterbox/resize 到 YuNet 输入尺寸，如 320×320，NCHW float32）
  → YuNet 检测 → N × [bbox(x,y,w,h) + 5 关键点 + score]
  → 过滤 score < det_thr
  → 选最居中人脸：argmin( dist(bbox 中心, 图像中心) )；并列时取 score 高者
  → 无人脸 → 返回 no_face
  → 5 点仿射对齐到 112×112（ArcFace 标准参考点）
  → ArcFace-R50：BGR + (pixel-127.5)/127.5 → 512-d → L2 归一化
  → 与 gallery 各模板求 cosine 相似度，取 top-1
  → top-1 ≥ rec_thr ? 该 ID : unknown
```

## 4. 组件（新包 `com.openclaw.car.face`）

| 组件 | 职责 | 关键点 |
|---|---|---|
| `FaceEngine` | 持 2 个 `OrtSession`（det / rec）；NNAPI EP（API≥27，失败降级 CPU EP）；preprocess/postprocess | 单例，懒加载；session 复用；**`OrtSession.invoke()` 非线程安全，`recognize()` 调用需串行化（单线程或加锁）** |
| `FaceGallery` | `filesDir/face_gallery.json`：`{ name: float[512] }`；CRUD + 加载/持久化 | 注册时每人 3-5 张 embedding 平均后再 L2 归一化作模板 |
| `FaceRecognizer` | 编排 §3 整条 pipeline | 返回 `RecognizeResult(id, score, bbox, landmarks, status)` |
| `FaceFragment` | demo UI：**注册**（选图/拍照→输名字→存）+ **识别**（选测试图→画框显示居中人脸 ID+分数） | 复用现有 Fragment 模式（同 `fragment/` 下其它 Fragment） |

**模型放置**：`app/src/main/assets/face/yunet.onnx`、`w600k_r50.onnx`。
**依赖**：`app/build.gradle.kts` 加 `com.microsoft.onnxruntime:onnxruntime-android`（Maven Central）。
**minSdk**：26 → 27（NNAPI 下限；车机 API 34 不受影响）。

## 5. 关键参数与预处理

- YuNet 输入：320×320（可配），float32 NCHW；输出每检测 15 元素 `[x,y,w,h, lx1..lx5, ly1..ly5, score]`
- 检测阈值 `det_thr` ≈ 0.5（可调）
- 居中选择：bbox 中心到图像中心欧氏距离最小
- 对齐参考点（ArcFace 标准 112×112）：
  ```
  (38.2946, 51.6963) (73.5318, 51.5014) (56.0252, 71.7366)
  (41.5493, 92.3655) (70.7299, 92.2041)
  ```
  - 由 5 关键点 → 参考点求 **相似变换（2D similarity transform）**，对原图 `warpAffine` 到 112×112
  - **实现选择**：用**纯 Kotlin 最小二乘求解相似变换**（5 点超定，闭式解），**不引入 opencv-android** 依赖（app 现无 OpenCV，避免体积膨胀）
- ArcFace-R50（w600k_r50）：输入 112×112 **BGR**（cv2/caffe 训练惯例），`(pixel-127.5)/127.5`；输出 512-d；L2 归一化。⚠️ **通道顺序与归一化是识别成败关键**（与 MobileFaceNet 的 RGB/128 不同），Task 10 验证
- 识别阈值 `rec_thr`（cosine）≈ **0.45**（可调，注册集上调优）
- 注册：每人 K=3-5 张，分别嵌入后求平均，再 L2 归一化存为该人模板

## 6. 错误处理

| 场景 | 行为 |
|---|---|
| 无人脸 | 返回 `status=no_face` |
| 多人脸 | **只取最居中**（需求明确） |
| top-1 < rec_thr | `status=unknown` |
| NNAPI 不可用（API<27 / HAL 失败） | 自动降级 CPU EP，仍可跑（延迟变高，UI 标注当前后端） |
| 模型/session 初始化失败 | UI 提示 + logcat，不崩 |
| Gallery 空 | 识别直接返回 `unknown` |

## 7. 测试与验证

- **纯逻辑单测**：相似变换对齐、cosine、center-pick（无模型依赖，JVM 可测）
- **端到端**：3-5 人各 4-6 张照片，注册后用 held-out 图测准确率/召回 + 单帧延迟（NNAPI vs CPU 两后端）
- **性能目标**：det + rec 单帧 **< 100ms**（NPU），demo 实时足够
- **NNAPI 命中验证**：开 ORT EP node assignment 日志，确认大部分算子真上 NPU 而非静默 CPU 回退（YuNet/R50 算子干净，预期命中率高；若大量回退需换模型或回 NeuroPilot AAR 路径）

## 8. 明确不在本期范围

- 车内摄像头取帧（Camera2 / BYD HAL 探测）—— 后续 Phase
- `/face/identify`、`/face/enroll` HTTP 端点（接入 `UiHttpServer :18802`）—— 后续
- gallery > ~20 人 / 更高精度
- 持久化人脸原图（仅存 embedding）

## 9. 未来升级路径（非本期）

- **NeuroPilot AAR 路径**：若需"名正言顺用 NeuroPilot"或榨取 NeuronDelegate 厂商调优性能 → YuNet/R50 ONNX→TFLite（一次性）+ `Android_V_neuropilot.aar` + `NeuronDelegate`。接口与本期一致，仅替换 `FaceEngine` 后端。
- **精度升级**：`w600k_r50` → buffalo_l 的 `w600k_r100`（R100，更准，体积↑）。
- **相机接入**：探测 BYD 座舱内摄像头可访问性（Camera2 API vs 专有 HAL）。

## 10. 模型来源

- YuNet ONNX：OpenCV Zoo `face_detection_yunet_2023mar.onnx`（轻量，~数百 KB–MB 级）
- ArcFace-R50 ONNX：InsightFace **buffalo_l** 的 `w600k_r50.onnx`（112×112，512-d）。注意 `w600k_r50` 在 buffalo_l 包里（buffalo_s 里是 `w600k_mbf`，不是 R50）。从 buffalo_l.zip 解包获取（见 plan Task 1 Step 6）。预处理 BGR + (x-127.5)/127.5。
