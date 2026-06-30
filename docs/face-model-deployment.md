# 车机人脸模型部署经验总结

> 设备: BYD Di300 (MediaTek mt6991, Android 14 user), APU = MDLA
> 模型: YuNet 检测(yunet.tflite) + ArcFace-R50 识别(w600k_r50.tflite)
> 日期: 2026-06-30

## 一、最终成功方案（det + rec 全 MDLA）

```
yunet.tflite  + NnApiDelegate(MDLA, fp16) + 0-255 BGR NCHW + cv2解码  → 4ms
w600k_r50.tflite + NnApiDelegate(MDLA, fp16) + RGB NCHW (x-127.5)/127.5 + L2 → 9ms
```

- 推理总耗时 ~13ms（检测+识别全 APU），比最初 CPU 1300ms 快 100 倍
- app R50 embedding 前5维 = PC onnxruntime 前5维（完全一致，验证通过）

## 二、检测（YuNet）尝试方案与时延

| # | 方案 | 后端 | 预处理 | 解码 | INFER | 结果 |
|---|------|------|--------|------|-------|------|
| 1 | yunet.tflite + NeuronDelegate | CPU fallback | NHWC RGB 归一化 | sigmoid(cls·obj) | ~2000ms | ❌ NeuroPilot 私有JNI版本地狱(AAR v8.2 vs 设备adapter v8.1.2)→静默CPU |
| 2 | yunet.tflite + NnApiDelegate MDLA **fp16** | MDLA | 错(NHWC/RGB/归一化) | sigmoid | **4ms** | ❌ 快但全图假阳性(7950框)——被误判为"MDLA精度不行" |
| 3 | yunet.tflite + NnApiDelegate MDLA **fp32** | - | - | - | 编译失败 | ❌ `Node 81 ANEURALNETWORKS_BAD_DATA`(yunet某算子MDLA fp32不支持) |
| 4 | yunet.tflite + CPU XNNPACK | CPU | 错 | sigmoid | 187ms | ❌ obj恒0假阳性 |
| 5 | det_10g.onnx + onnxruntime CPU | CPU | RGB归一化 | score直接 | 1300ms | ⚠️ 准但慢(Android onnxruntime包无NEON优化,PC同模型69ms) |
| 6 | det_10g.onnx + onnxruntime NNAPI | nnapi-reference | - | - | 1300ms | ❌ score崩0.04(onnxruntime不指定加速器,落CPU软件模拟) |
| 7 | det_10g→tflite 转换 | - | - | - | - | ❌ AveragePool kernel_size空 + onnx2tf/onnx-tf工具链连环失败 |
| 8 | OpenCV cv2 FaceDetectorYN + YuNet | CPU(cv2.dnn) | 0-255 BGR | cv2内置 | 14ms(PC) | ✅ 准(score 0.944),Android估~50ms,**揭示了正确预处理/解码** |
| 9 | **yunet.tflite + MDLA fp16 + cv2预处理/解码** | **MDLA** | **0-255 BGR NCHW** | **clamp sqrt** | **4ms** | ✅✅ **score 0.896,准且快** |

## 三、识别（R50）尝试方案与时延

| # | 方案 | 后端 | 预处理 | INFER | 结果 |
|---|------|------|--------|-------|------|
| 1 | R50.tflite + MDLA(早期) | - | NHWC BGR | - | ❌ init崩溃——**误判R50 MDLA编译失败**,实际是同init的det fp32 Node81崩拖累 |
| 2 | R50.tflite + CPU XNNPACK | CPU | NHWC BGR(错) | ~200ms | ⚠️ 能跑但预处理错(embedding不准) |
| 3 | R50.onnx + onnxruntime CPU | CPU | RGB归一化 | 198ms(PC) | 准 |
| 4 | **R50.tflite + MDLA fp16 + NCHW RGB** | **MDLA** | **RGB NCHW (x-127.5)/127.5** | **9ms** | ✅✅ **app=PC一致** |

## 四、关键失败教训（走过的弯路）

1. **"mtk_converter 把 yunet.tflite 转 bug(obj恒0)"——错。** obj≈0 是 YuNet 模型特性,不是转换bug。花很久转 det_10g/OpenCV YuNet 都是浪费。
2. **"MDLA 对检测模型精度不行"——错。** fp16假阳性是预处理错(NHWC/RGB/归一化/sigmoid),不是MDLA。修正预处理后MDLA完美。
3. **"R50 MDLA 编译失败"——错。** 是 det fp32 Node81 崩拖垮整个 FaceEngine init,误归咎R50。R50单独MDLA编译成功。
4. **onnxruntime NNAPI EP 不指定加速器** → 落 nnapi-reference(CPU软件模拟),1300ms没加速+精度异常。要强制加速器得用 tflite `NnApiDelegate.setAcceleratorName("mtk-mdla_shim")`。
5. **det_10g→tflite 转换** 卡 AveragePool(kernel_size空)+ onnx2tf(onnxsim pickle)+ onnx-tf(onnx版本)。InsightFace det_10g 的FPN AveragePool导出有问题。
6. **asFloatBuffer 视图坑**: `buf.asFloatBuffer().put()` 写入的数据 TFLite 读不到(视图与底层字节布局不一致)。改用 `ByteBuffer.putFloat(byteOffset, val)` 直接写字节。
7. **createTensor buffer 类型**: onnxruntime `createTensor(ByteBuffer, shape)` 把字节数当元素数报错,要用 `FloatBuffer.wrap(float[])`。
8. **诊断盲区**: 不在 detect() 内分段计时(letterbox/preproc/INFER),会被预处理开销掩盖真实推理速度;不 dump 模型原始输出(看cls/obj raw值),无法区分模型坏还是预处理坏。

## 五、正确预处理/解码配方（cv2 源码 = 金标准）

**检测 YuNet**(照搬 `opencv/modules/objdetect/src/face_detect.cpp`):
- 输入: NCHW `[1,3,640,640]` **0-255 BGR 不归一化**(`dnn::blobFromImage` 无 scale/mean)
- score = `sqrt(clamp(cls,0,1) * clamp(obj,0,1))` —— **不加 sigmoid**(输出已是概率)
- bbox: `cx=(col+bbox0)*stride, cy=(row+bbox1)*stride, w=exp(bbox2)*stride, h=exp(bbox3)*stride`
- landmarks: `(kps + col)*stride, (kps + row)*stride`
- centerCrop正方形+resize640(中央人脸放大,边缘小脸裁掉)

**识别 ArcFace R50**(照搬 insightface arcface):
- 输入: NCHW `[1,3,112,112]` **RGB**(`swapRB=True`) `(x-127.5)/127.5`
- 后处理: L2 normalize

**MDLA 必开 fp16**: `NnApiDelegate.setAllowFp16(true)`。fp32 时 yunet Node81 编译失败。

## 六、验证方法

- **PC 黄金对照**: `pip install tflite-runtime onnxruntime insightface opencv-python`。`cv2.FaceDetectorYN` 跑标准 face 得 score; onnxruntime 跑 w600k_r50.onnx 得 embedding。
- **4输入铁证**(判模型是否输入相关): 喂随机噪声/全0/全1/真图,看输出是否随输入变化。恒定=模型分支死。
- **app selftest**: FaceEngine init 时 `embed(固定灰图0xff808080)` log 前5维,和 PC 同输入对比。app=PC 即 preprocessing+模型正确。

## 七、时延总对比

| 配置 | 检测 | 识别 | 总 |
|------|------|------|-----|
| CPU onnxruntime(det_10g+R50) | 1300ms | 198ms | ~1500ms |
| CPU tflite XNNPACK | 187ms | 200ms | ~390ms |
| cv2.dnn CPU | 50ms(Android估) | - | - |
| **MDLA APU(最终)** | **4ms** | **9ms** | **~13ms** |

## 八、架构文件

- `FaceEngine.kt` — det(yunet MDLA) + embed(R50 MDLA) + applyAccel(NnApiDelegate mtk-mdla_shim fp16)
- `OnnxFaceDetector.kt` — det_10g onnxruntime 备选(CPU,慢,已不用)
- `LiveVideoFaceFragment.kt` — OMS实时流 + FaceEngine检测显示
- `DMS_OMS/oms-stream.sh` + `oms-http.py` — yocto侧视频流服务
- `app/src/main/assets/face/` — yunet.tflite + w600k_r50.tflite + det_10g.onnx(备选)

## 九、端到端识别验证（2026-06-30 闭环成功）

注册 + 实时识别完整跑通（OMS 实时流 + 全 MDLA APU）：

**注册**：视频流 tab 输入姓名 → 📸注册 → OMS 抓一帧 → pickCenter(最中央正脸, detScore~0.93) → 5点 align + R50 embed → gallery(JSON 持久化)

**识别**：🎥OMS实时 → detect(4ms MDLA) → align → embed(7ms MDLA) → cosine match → **RECOGNIZED**

**实测**（注册 fxj 后实时识别，面对 OMS 镜头）：
```
recognize: status=RECOGNIZED id=fxj cos=0.793 detScore=0.933 55ms
recognize: status=RECOGNIZED id=fxj cos=0.803 detScore=0.928 54ms
recognize: status=RECOGNIZED id=fxj cos=0.820 detScore=0.930 58ms
recognize: status=RECOGNIZED id=fxj cos=0.785 detScore=0.929 57ms
```
- 连续 RECOGNIZED，cos **0.78-0.82**（正脸），detScore **0.93**
- **总 55ms/帧**（detect 4 + embed 7 + align + match + 预处理，全 MDLA）

**阈值 REC_THR=0.5**：实测同人 cos 随角度波动 0.6-0.82（正脸~0.8，侧脸~0.65），原 0.85 全 UNKNOWN，0.5 能稳定识别。
- ⚠️ 0.5 偏低有误识风险，生产建议 0.6-0.65 + 多角度注册（enrollMany）提鲁棒性
- 单张注册对角度敏感（角度差 cos 掉到 0.6），多注册不同角度可提升

**坑：增量编译不更新 const**。REC_THR 改 0.75→0.5 后，增量 `assembleDebug` 仍用旧 0.75（0.744 显示 UNKNOWN），需 `clean assembleDebug` 才生效。Kotlin companion const 内联到调用方，改 const 要 clean。

**cos=0 的真相**：`recognize` 里 UNKNOWN 时 score 硬编码 0（`RecognizeResult(UNKNOWN, null, 0f, ...)`），**不代表真实相似度**。诊断时改 `gallery.bestMatch(emb, -1f)` 拿真实最高 cos 显示，才看到 0.78。
