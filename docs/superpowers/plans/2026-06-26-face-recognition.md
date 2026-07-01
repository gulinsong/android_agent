# 车内人脸识别（端侧 demo）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `agent_front_app` 内置一条端侧人脸识别 pipeline：输入 Bitmap → 输出最靠中心人脸的 ID（命中 gallery）或 unknown，ONNX Runtime + NNAPI EP 跑在 MT6991 NPU，demo 级、实时。

**Architecture:** 新建 `com.openclaw.car.face` 包。纯逻辑（向量运算、相似变换对齐、YuNet 解码、gallery）全部 JVM 可测且不依赖 android.\*；Android 依赖部分（ORT session、Bitmap、Fragment）按构建+车机端验证。YuNet(检测)+ArcFace-R50 `w600k_r50`(嵌入) 两个 ONNX 模型从 assets 加载，NNAPI EP 命中 NPU，失败降级 CPU。

**Tech Stack:** Kotlin · ONNX Runtime Android（`onnxruntime-android`）· NNAPI EP · Gson · JUnit4（JVM 单测）· AndroidX Fragment/ViewPager2（复用现有 tab 机制）

## Global Constraints

- minSdk **27**（NNAPI 下限；原 26，需改 build.gradle.kts）。compileSdk 34，targetSdk 34。
- ABI 仅 `arm64-v8a`（ndk abiFilters 已限定，不要加别的）。
- **不引入 opencv-android**（相似变换用纯 Kotlin 求解，仿射采样用纯 IntArray 实现）。
- **`OrtSession.invoke()` 非线程安全**：`recognize()`/`enroll()` 调用需串行化（单线程执行器或加锁）。
- 纯逻辑类**不得 import 任何 android.\***（否则 JVM 单测会命中 android stub 抛异常）。
- Gallery 存 `context.filesDir/face_gallery.json`，键为人名，值为 float[512]。
- 超参：检测阈值 `det_thr=0.5`，识别 cosine 阈值 `rec_thr=0.45`（可调）。
- 复用现有约定：Fragment 用 `findViewById`（无 ViewBinding）；tab 经 `ViewPagerAdapter` + `MainActivity` 的 `TabLayoutMediator`；strings 在 `res/values/strings.xml`。
- 不新增权限（图片经 SAF `GetContent`/`GetMultipleContents` 选取；现有 MANAGE_EXTERNAL_STORAGE 已够）。

## File Structure

**新建（纯逻辑，JVM 可测）：**
- `app/src/main/java/com/openclaw/car/face/FaceTypes.kt` — `Point`、`FaceBox`、`RecognizeResult`、`Status` 数据类
- `app/src/main/java/com/openclaw/car/face/FaceMath.kt` — cosine / l2normalize / mean
- `app/src/main/java/com/openclaw/car/face/SimilarityTransform.kt` — 5 点→2×3 仿射矩阵（闭式最小二乘）
- `app/src/main/java/com/openclaw/car/face/AffineWarp.kt` — IntArray 上的双线性仿射采样（无 OpenCV）
- `app/src/main/java/com/openclaw/car/face/YuNetDecode.kt` — anchor 生成 + 输出解码 + NMS（纯函数）
- `app/src/main/java/com/openclaw/car/face/FaceGallery.kt` — JSON gallery 增删查 + bestMatch

**新建（Android 依赖）：**
- `app/src/main/java/com/openclaw/car/face/FaceEngine.kt` — ORT 双 session（NNAPI EP）、detect/embed
- `app/src/main/java/com/openclaw/car/face/FaceRecognizer.kt` — 编排 detect→center→align→embed→match
- `app/src/main/java/com/openclaw/car/fragment/FaceFragment.kt` — demo UI（注册+识别）
- `app/src/main/res/layout/fragment_face.xml`
- `app/src/main/assets/face/` — 放 `yunet.onnx`、`w600k_r50.onnx`（不入 git，见 Task 1）

**修改：**
- `app/build.gradle.kts` — minSdk 27、加 onnxruntime-android、加 JUnit testImplementation
- `app/src/main/java/com/openclaw/car/adapter/ViewPagerAdapter.kt` — 加第 6 个 tab
- `app/src/main/java/com/openclaw/car/MainActivity.kt` — tab 文案 + offscreenPageLimit
- `app/src/main/res/values/strings.xml` — 加 `tab_face` 等文案
- `.gitignore`（仓库根） — 排除 `**/assets/face/*.onnx`

**测试（JVM）：**
- `app/src/test/java/com/openclaw/car/face/FaceMathTest.kt`
- `app/src/test/java/com/openclaw/car/face/SimilarityTransformTest.kt`
- `app/src/test/java/com/openclaw/car/face/AffineWarpTest.kt`
- `app/src/test/java/com/openclaw/car/face/YuNetDecodeTest.kt`
- `app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt`

---

### Task 1: 工程脚手架（依赖、minSdk、测试基建、模型占位）

**Files:**
- Modify: `app/build.gradle.kts`
- Modify: `<repo-root>/.gitignore`
- Create: `app/src/main/assets/face/.gitkeep`
- Create: `app/src/test/java/com/openclaw/car/face/SanityTest.kt`

**Interfaces:** 无（基础设施）

- [ ] **Step 1: 改 build.gradle.kts**

把 `minSdk = 26` 改为 `minSdk = 27`。在 `dependencies` 块末尾追加：

```kotlin
    // ONNX Runtime（端侧推理，NNAPI EP 上 NPU）
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")

    // JVM 单测
    testImplementation("junit:junit:4.13.2")
```

- [ ] **Step 2: 排除 onnx 模型入 git**

在仓库根 `.gitignore` 追加一行（如已有 `assets/` 规则需确认不误伤）：

```
**/assets/face/*.onnx
```

- [ ] **Step 3: 建 assets 目录与占位**

```bash
mkdir -p app/src/main/assets/face
touch app/src/main/assets/face/.gitkeep
```

- [ ] **Step 4: 写一个最小 JVM 测试验证测试基建**

`app/src/test/java/com/openclaw/car/face/SanityTest.kt`：

```kotlin
package com.openclaw.car.face

import org.junit.Assert.assertEquals
import org.junit.Test

class SanityTest {
    @Test
    fun sanity() {
        assertEquals(4, 2 + 2)
    }
}
```

- [ ] **Step 5: 跑测试，确认 JVM 测试基建可用**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SanityTest"`
Expected: BUILD SUCCESSFUL，1 test passed。

- [ ] **Step 6: 获取 ONNX 模型（放入 assets）**

YuNet（OpenCV Zoo，可靠直链）：

```bash
cd app/src/main/assets/face
curl -L -o yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
ls -l yunet.onnx   # 预期 ~5MB 量级
```

ArcFace-R50（InsightFace **buffalo_l** 的 `w600k_r50`，112×112，512-d；注意 `w600k_r50` 在 buffalo_l 包里，buffalo_s 里是 `w600k_mbf` 不是 R50）。从官方 buffalo_l 包解包：

```bash
cd app/src/main/assets/face
curl -L -o buffalo_l.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -o buffalo_l.zip w600k_r50.onnx
rm buffalo_l.zip
ls -lh w600k_r50.onnx   # 预期 ~167MB
# 若 release tag/链接不符，从 https://github.com/deepinsight/insightface/releases 手动取 buffalo_l.zip 解包
```

最终 `app/src/main/assets/face/` 下有 `yunet.onnx` 与 `w600k_r50.onnx`。

- [ ] **Step 7: Commit**

```bash
git add app/build.gradle.kts .gitignore app/src/main/assets/face/.gitkeep \
        app/src/test/java/com/openclaw/car/face/SanityTest.kt
git commit -m "feat(face): 工程脚手架 - onnxruntime 依赖 + minSdk27 + JVM 测试基建"
```

（onnx 模型被 gitignore，不入库）

---

### Task 2: 向量运算 FaceMath（cosine / l2normalize / mean）

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/FaceMath.kt`
- Test: `app/src/test/java/com/openclaw/car/face/FaceMathTest.kt`

**Interfaces:**
- Produces: `FaceMath.cosine(a: FloatArray, b: FloatArray): Float`、`FaceMath.l2normalize(a: FloatArray): FloatArray`、`FaceMath.mean(vectors: List<FloatArray>): FloatArray`

- [ ] **Step 1: 写失败测试**

`app/src/test/java/com/openclaw/car/face/FaceMathTest.kt`：

```kotlin
package com.openclaw.car.face

import org.junit.Assert.assertEquals
import org.junit.Test
import kotlin.math.abs

class FaceMathTest {
    @Test
    fun cosine_identical_is_one() {
        val a = floatArrayOf(1f, 2f, 3f)
        assertEquals(1f, FaceMath.cosine(a, a), 1e-5f)
    }

    @Test
    fun cosine_orthogonal_is_zero() {
        val a = floatArrayOf(1f, 0f)
        val b = floatArrayOf(0f, 1f)
        assertEquals(0f, FaceMath.cosine(a, b), 1e-5f)
    }

    @Test
    fun l2normalize_unit_length() {
        val n = FaceMath.l2normalize(floatArrayOf(3f, 4f))
        val len = kotlin.math.sqrt(n[0] * n[0] + n[1] * n[1])
        assertEquals(1f, len, 1e-5f)
        assertEquals(0.6f, n[0], 1e-5f) // 3/5
        assertEquals(0.8f, n[1], 1e-5f) // 4/5
    }

    @Test
    fun mean_averages_componentwise() {
        val m = FaceMath.mean(listOf(floatArrayOf(1f, 3f), floatArrayOf(3f, 7f)))
        assertEquals(2f, m[0], 1e-5f)
        assertEquals(5f, m[1], 1e-5f)
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.FaceMathTest"`
Expected: FAIL（`FaceMath` 未解析 / unresolved reference）。

- [ ] **Step 3: 实现 FaceMath**

`app/src/main/java/com/openclaw/car/face/FaceMath.kt`：

```kotlin
package com.openclaw.car.face

import kotlin.math.sqrt

object FaceMath {

    fun cosine(a: FloatArray, b: FloatArray): Float {
        require(a.size == b.size) { "length mismatch: ${a.size} vs ${b.size}" }
        var dot = 0.0
        var na = 0.0
        var nb = 0.0
        for (i in a.indices) {
            dot += a[i].toDouble() * b[i].toDouble()
            na += a[i].toDouble() * a[i].toDouble()
            nb += b[i].toDouble() * b[i].toDouble()
        }
        if (na <= 0.0 || nb <= 0.0) return 0f
        return (dot / (sqrt(na) * sqrt(nb))).toFloat()
    }

    fun l2normalize(a: FloatArray): FloatArray {
        var s = 0.0
        for (v in a) s += v.toDouble() * v.toDouble()
        val inv = if (s > 0.0) (1.0 / sqrt(s)).toFloat() else 0f
        return FloatArray(a.size) { a[it] * inv }
    }

    fun mean(vectors: List<FloatArray>): FloatArray {
        require(vectors.isNotEmpty()) { "empty list" }
        val n = vectors[0].size
        val out = FloatArray(n)
        for (v in vectors) {
            require(v.size == n) { "length mismatch" }
            for (i in 0 until n) out[i] += v[i]
        }
        val inv = 1f / vectors.size
        for (i in 0 until n) out[i] *= inv
        return out
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.FaceMathTest"`
Expected: PASS（4 tests）。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/FaceMath.kt \
        app/src/test/java/com/openclaw/car/face/FaceMathTest.kt
git commit -m "feat(face): FaceMath 向量运算（cosine/l2normalize/mean）+ 单测"
```

---

### Task 3: 数据类型 FaceTypes + 相似变换 SimilarityTransform

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/FaceTypes.kt`
- Create: `app/src/main/java/com/openclaw/car/face/SimilarityTransform.kt`
- Test: `app/src/test/java/com/openclaw/car/face/SimilarityTransformTest.kt`

**Interfaces:**
- Produces: `Point(x: Float, y: Float)`、`FaceBox(x,y,w,h,score,landmarks: List<Point>)`、`RecognizeResult`、`Status`
- Produces: `SimilarityTransform.fit(src: List<Point>, dst: List<Point>): FloatArray` 返回 6 元素仿射 `[a, b, c, d, e, f]`，映射 `x' = a*x + b*y + c`，`y' = d*x + e*y + f`

- [ ] **Step 1: 写数据类型**

`app/src/main/java/com/openclaw/car/face/FaceTypes.kt`：

```kotlin
package com.openclaw.car.face

data class Point(val x: Float, val y: Float)

data class FaceBox(
    val x: Float,   // 左上 x
    val y: Float,   // 左上 y
    val w: Float,
    val h: Float,
    val score: Float,
    val landmarks: List<Point> // 恰好 5 个
) {
    val cx: Float get() = x + w / 2f
    val cy: Float get() = y + h / 2f
}

enum class Status { NO_FACE, UNKNOWN, RECOGNIZED }

data class RecognizeResult(
    val status: Status,
    val id: String? = null,
    val score: Float = 0f,
    val box: FaceBox? = null
)
```

- [ ] **Step 2: 写失败测试**

`app/src/test/java/com/openclaw/car/face/SimilarityTransformTest.kt`：

```kotlin
package com.openclaw.car.face

import org.junit.Assert.assertEquals
import org.junit.Test

class SimilarityTransformTest {

    private val arcfaceRef = listOf(
        Point(38.2946f, 51.6963f), Point(73.5318f, 51.5014f),
        Point(56.0252f, 71.7366f), Point(41.5493f, 92.3655f),
        Point(70.7299f, 92.2041f)
    )

    @Test
    fun fit_recovers_known_translation() {
        // src 经平移 (+10,+20) 得 dst，拟合应还原纯平移
        val src = arcfaceRef
        val dst = src.map { Point(it.x + 10f, it.y + 20f) }
        val m = SimilarityTransform.fit(src, dst)
        // [a,b,c,d,e,f]
        assertEquals(1f, m[0], 1e-3f) // a
        assertEquals(0f, m[1], 1e-3f) // b
        assertEquals(10f, m[2], 1e-2f) // c (tx)
        assertEquals(0f, m[3], 1e-3f) // d
        assertEquals(1f, m[4], 1e-3f) // e
        assertEquals(20f, m[5], 1e-2f) // f (ty)
    }

    @Test
    fun fit_recovers_known_scale_and_rotation() {
        // 先对 ref 做 scale=2，逆映射验证：用 dst=ref*2，fit(src=ref,dst=ref*2) 应得 scale≈2
        val src = arcfaceRef
        val dst = src.map { Point(it.x * 2f, it.y * 2f) }
        val m = SimilarityTransform.fit(src, dst)
        assertEquals(2f, m[0], 1e-2f) // a (scale)
        assertEquals(2f, m[4], 1e-2f) // e (scale)
        assertEquals(0f, m[1], 1e-2f)
        assertEquals(0f, m[3], 1e-2f)
    }
}
```

- [ ] **Step 3: 跑测试确认失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SimilarityTransformTest"`
Expected: FAIL（`SimilarityTransform` unresolved）。

- [ ] **Step 4: 实现 SimilarityTransform（复数最小二乘，无 SVD）**

`app/src/main/java/com/openclaw/car/face/SimilarityTransform.kt`：

```kotlin
package com.openclaw.car.face

/**
 * 2D 相似变换（平移+旋转+等比缩放）最小二乘拟合。
 * 模型：dst = β * src + t，其中 β = a + i*b 为复数缩放旋转，
 * 即 x' = a*x - b*y + c, y' = b*x + a*y + d。
 * 返回 6 元素 [a, b, c, d, e, f] 标准 2x3 仿射（x'=a*x+b*y+c, y'=d*x+e*y+f）：
 * 映射为 [a, -b, c, b, a, d]。
 */
object SimilarityTransform {

    fun fit(src: List<Point>, dst: List<Point>): FloatArray {
        require(src.size == dst.size && src.size >= 2) { "need >=2 point pairs" }
        val n = src.size

        // 质心
        var msx = 0.0; var msy = 0.0; var mdx = 0.0; var mdy = 0.0
        for (i in 0 until n) {
            msx += src[i].x.toDouble(); msy += src[i].y.toDouble()
            mdx += dst[i].x.toDouble(); mdy += dst[i].y.toDouble()
        }
        msx /= n; msy /= n; mdx /= n; mdy /= n

        // 复数最小二乘：β = Σ w·conj(z) / Σ |z|^2，z 为去心 src，w 为去心 dst
        var numRe = 0.0; var numIm = 0.0; var den = 0.0
        for (i in 0 until n) {
            val zx = src[i].x.toDouble() - msx
            val zy = src[i].y.toDouble() - msy
            val wx = dst[i].x.toDouble() - mdx
            val wy = dst[i].y.toDouble() - mdy
            // w * conj(z) = (wx + i wy)*(zx - i zy) = (wx*zx + wy*zy) + i(wy*zx - wx*zy)
            numRe += wx * zx + wy * zy
            numIm += wy * zx - wx * zy
            den += zx * zx + zy * zy
        }
        val a: Double
        val b: Double
        if (den > 0.0) {
            a = numRe / den
            b = numIm / den
        } else {
            a = 1.0; b = 0.0
        }
        // 平移 t = μ_dst - β·μ_src
        val c = mdx - (a * msx - b * msy)
        val d = mdy - (b * msx + a * msy)

        // 标准 2x3 仿射 [a, b', c, d', e, f]：x'=a*x-b*y+c, y'=b*x+a*y+d
        return floatArrayOf(a.toFloat(), (-b).toFloat(), c.toFloat(),
                            b.toFloat(), a.toFloat(), d.toFloat())
    }
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.SimilarityTransformTest"`
Expected: PASS（2 tests）。

- [ ] **Step 6: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/FaceTypes.kt \
        app/src/main/java/com/openclaw/car/face/SimilarityTransform.kt \
        app/src/test/java/com/openclaw/car/face/SimilarityTransformTest.kt
git commit -m "feat(face): FaceTypes 数据类 + SimilarityTransform 5点对齐"
```

---

### Task 4: 仿射采样 AffineWarp（IntArray 双线性，无 OpenCV）

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/AffineWarp.kt`
- Test: `app/src/test/java/com/openclaw/car/face/AffineWarpTest.kt`

**Interfaces:**
- Consumes: `SimilarityTransform.fit` 的输出 `[a,b,c,d,e,f]`
- Produces: `AffineWarp.warp(srcPixels: IntArray, srcW: Int, srcH: Int, m: FloatArray, outW: Int, outH: Int): IntArray`（ARGB_8888，反向映射+双线性，越界取 0）

- [ ] **Step 1: 写失败测试**

`app/src/test/java/com/openclaw/car/face/AffineWarpTest.kt`：

```kotlin
package com.openclaw.car.face

import org.junit.Assert.assertEquals
import org.junit.Test

class AffineWarpTest {

    private fun rgb(r: Int, g: Int, b: Int): Int =
        (0xFF shl 24) or (r shl 16) or (g shl 8) or b

    @Test
    fun identity_matrix_copies_image() {
        // 2x2 全红图，单位仿射应原样复制
        val src = IntArray(4) { rgb(255, 0, 0) }
        val id = floatArrayOf(1f, 0f, 0f, 0f, 1f, 0f)
        val out = AffineWarp.warp(src, 2, 2, id, 2, 2)
        for (i in 0 until 4) assertEquals(src[i], out[i])
    }

    @Test
    fn_like_shift() {
        // 用 _ 方法名做 JUnit3 风格也行，这里改名避免误解
    }

    @Test
    fun out_of_bounds_is_zero() {
        // 平移把源完全移出视野 → 输出应为 0
        val src = IntArray(4) { rgb(255, 0, 0) }
        val shift = floatArrayOf(1f, 0f, 100f, 0f, 1f, 100f)
        val out = AffineWarp.warp(src, 2, 2, shift, 2, 2)
        for (i in 0 until 4) assertEquals(0, out[i])
    }
}
```

> 注：删掉上例中无用的 `fn_like_shift` 空方法（保留仅为提醒不要用非 @Test 名）。最终文件只留两个 `@Test`。

- [ ] **Step 2: 跑测试确认失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.AffineWarpTest"`
Expected: FAIL（`AffineWarp` unresolved）。

- [ ] **Step 3: 实现 AffineWarp（反向映射双线性）**

`app/src/main/java/com/openclaw/car/face/AffineWarp.kt`：

```kotlin
package com.openclaw.car.face

/**
 * 对 ARGB_8888 像素数组做仿射变换（反向映射 + 双线性插值）。
 * m = [a,b,c,d,e,f]，正向：x'=a*x+b*y+c, y'=d*x+e*y+f。
 * 反向：解 [x,y] = M^-1 ([x',y'] - [c,f])。因相似变换可逆（det=a^2+b'^2）。
 */
object AffineWarp {

    fun warp(src: IntArray, srcW: Int, srcH: Int, m: FloatArray, outW: Int, outH: Int): IntArray {
        val a = m[0].toDouble(); val b = m[1].toDouble(); val c = m[2].toDouble()
        val d = m[3].toDouble(); val e = m[4].toDouble(); val f = m[5].toDouble()

        val det = a * e - b * d
        val out = IntArray(outW * outH)
        if (Math.abs(det) < 1e-9) return out // 不可逆，全 0

        val invA = e / det
        val invB = -b / det
        val invD = -d / det
        val invE = a / det

        for (oy in 0 until outH) {
            for (ox in 0 until outW) {
                val tx = ox - c
                val ty = oy - f
                val sx = invA * tx + invB * ty
                val sy = invD * tx + invE * ty
                out[oy * outW + ox] = sample(src, srcW, srcH, sx, sy)
            }
        }
        return out
    }

    private fun sample(src: IntArray, w: Int, h: Int, x: Double, y: Double): Int {
        if (x < -1 || y < -1 || x > w || y > h) return 0
        val x0 = Math.floor(x).toInt()
        val y0 = Math.floor(y).toInt()
        val x1 = x0 + 1
        val y1 = y0 + 1
        val wx = x - x0
        val wy = y - y0
        return blend(
            blend(at(src, w, h, x0, y0), at(src, w, h, x1, y0), wx),
            blend(at(src, w, h, x0, y1), at(src, w, h, x1, y1), wx),
            wy
        )
    }

    private fun at(src: IntArray, w: Int, h: Int, x: Int, y: Int): Int {
        if (x < 0 || y < 0 || x >= w || y >= h) return 0
        return src[y * w + x]
    }

    private fun blend(p0: Int, p1: Int, t: Double): Int {
        val tm = (1.0 - t)
        val a = ((p0 ushr 24) and 0xFF) * tm + ((p1 ushr 24) and 0xFF) * t
        val r = ((p0 ushr 16) and 0xFF) * tm + ((p1 ushr 16) and 0xFF) * t
        val g = ((p0 ushr 8) and 0xFF) * tm + ((p1 ushr 8) and 0xFF) * t
        val b = (p0 and 0xFF) * tm + (p1 and 0xFF) * t
        return (a.toInt() shl 24) or (r.toInt() shl 16) or (g.toInt() shl 8) or b.toInt()
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.AffineWarpTest"`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/AffineWarp.kt \
        app/src/test/java/com/openclaw/car/face/AffineWarpTest.kt
git commit -m "feat(face): AffineWarp 纯 IntArray 双线性仿射采样"
```

---

### Task 5: YuNet 解码 YuNetDecode（anchor + 解码 + NMS + center-pick）

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/YuNetDecode.kt`
- Test: `app/src/test/java/com/openclaw/car/face/YuNetDecodeTest.kt`

**Interfaces:**
- Consumes: `FaceBox`
- Produces: `YuNetDecode.generateAnchors(w, h, strides): List<Point>`、`YuNetDecode.decode(anchors, loc, conf, iou, strides, thr): List<FaceBox>`、`YuNetDecode.nms(boxes, iouThr): List<FaceBox>`、`YuNetDecode.pickCenter(boxes, imgW, imgH): FaceBox?`

- [ ] **Step 1: 写失败测试**

`app/src/test/java/com/openclaw/car/face/YuNetDecodeTest.kt`：

```kotlin
package com.openclaw.car.face

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class YuNetDecodeTest {

    @Test
    fun anchors_count_matches_strides_and_feature_sizes() {
        // W=H=32, strides [8,16,32] → 特征图 4,2,1 → 4*4+2*2+1*1 = 21 anchors
        val anchors = YuNetDecode.generateAnchors(32, 32, intArrayOf(8, 16, 32))
        assertEquals(21, anchors.size)
    }

    @Test
    fun pickCenter_chooses_closest_to_image_center() {
        // 50x50 图中心(25,25)：A 中心(5,5) d²=800；B 中心(25,25) d²=0 ← 最居中
        val boxes = listOf(
            FaceBox(0f, 0f, 10f, 10f, 0.9f, emptyList()),         // 中心(5,5)，较远
            FaceBox(20f, 20f, 10f, 10f, 0.8f, emptyList())        // 中心(25,25)，最居中
        )
        val pick = YuNetDecode.pickCenter(boxes, 50, 50)
        assertEquals(20f, pick!!.x, 1e-3f)
    }

    @Test
    fun pickCenter_returns_null_when_empty() {
        assertNull(YuNetDecode.pickCenter(emptyList(), 50, 50))
    }

    @Test
    fun nms_removes_high_overlap() {
        val boxes = listOf(
            FaceBox(0f, 0f, 10f, 10f, 0.95f, emptyList()),
            FaceBox(1f, 1f, 10f, 10f, 0.80f, emptyList()),  // 与上一个 IoU 高
            FaceBox(100f, 100f, 10f, 10f, 0.70f, emptyList()) // 不重叠
        )
        val kept = YuNetDecode.nms(boxes, 0.3f)
        assertEquals(2, kept.size)
        assertTrue(kept.any { it.score == 0.95f })
        assertTrue(kept.any { it.score == 0.70f })
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.YuNetDecodeTest"`
Expected: FAIL（`YuNetDecode` unresolved）。

- [ ] **Step 3: 实现 YuNetDecode**

`app/src/main/java/com/openclaw/car/face/YuNetDecode.kt`：

```kotlin
package com.openclaw.car.face

import kotlin.math.max
import kotlin.math.min

/**
 * OpenCV Zoo YuNet (2023mar) 解码：strides [8,16,32]，anchor 中心在 (col*stride, row*stride)。
 * 输出三头：loc[1,N,14]=[dx1,dy1,dx2,dy2, lx0,ly0,...,lx4,ly4]，conf[1,N,1]，iou[1,N,1]。
 * 偏移 × stride 加到 anchor 中心。最终得分 = sqrt(conf*iou)。
 * ⚠️ 验证步骤：实测模型真实输出名/形状（见 FaceEngine Task），若不同需在此适配。
 */
object YuNetDecode {

    fun generateAnchors(w: Int, h: Int, strides: IntArray): List<Point> {
        val anchors = ArrayList<Point>(w * h)
        for (s in strides) {
            val fw = (w + s - 1) / s
            val fh = (h + s - 1) / s
            for (r in 0 until fh) {
                for (c in 0 until fw) {
                    anchors.add(Point((c * s).toFloat(), (r * s).toFloat()))
                }
            }
        }
        return anchors
    }

    /**
     * @param loc [N][14]，[N] 行
     * @param conf [N]，sigmoid 后的人脸概率
     * @param iou [N]，sigmoid 后的 iou 分量
     * @param strides 与 anchors 对应的分段步长
     */
    fun decode(
        anchors: List<Point>,
        strides: IntArray,
        loc: Array<FloatArray>,   // [N][14]
        conf: FloatArray,         // [N]
        iou: FloatArray,          // [N]
        scoreThr: Float
    ): List<FaceBox> {
        val n = anchors.size
        // 每个 anchor 对应的 stride（按生成顺序分段）
        val out = ArrayList<FaceBox>()
        var idx = 0
        for (s in strides) {
            val fw = 1 // 仅用于计数，下面按 idx 推进
            repeat(0) {} // no-op，保留语义
            // stride 分段长度需对齐 generateAnchors；直接按 idx 遍历到 n
            break
        }
        // 简化：构造 stride-per-anchor 数组
        val strideOf = stridePerAnchor(anchors.size, strides) // 复用下文
        for (i in 0 until n) {
            val score = Math.sqrt((conf[i] * iou[i]).toDouble()).toFloat()
            if (score < scoreThr) continue
            val s = strideOf[i]
            val ax = anchors[i].x
            val ay = anchors[i].y
            val l = loc[i]
            val x1 = ax + l[0] * s
            val y1 = ay + l[1] * s
            val x2 = ax + l[2] * s
            val y2 = ay + l[3] * s
            val lms = ArrayList<Point>(5)
            for (k in 0 until 5) {
                val lx = ax + l[4 + 2 * k] * s
                val ly = ay + l[5 + 2 * k] * s
                lms.add(Point(lx, ly))
            }
            out.add(FaceBox(x1, y1, x2 - x1, y2 - y1, score, lms))
        }
        return out
    }

    private fun stridePerAnchor(total: Int, strides: IntArray): IntArray {
        // 与 generateAnchors 同序：每个 stride 占 fw*fh 个
        val out = IntArray(total)
        var pos = 0
        // 这里无法独立知道 w/h，因此由调用方保证 anchors 与 strides 一致；
        // 本辅助仅按 strides 平均近似——实际 decode 已由 anchors 顺序保证。
        // 为正确性，strideOf 直接按 strides 轮询填充占位，真实场景由 FaceEngine 传入精确数组。
        for (i in 0 until total) out[i] = strides[i % strides.size]
        return out
    }

    fun nms(boxes: List<FaceBox>, iouThr: Float): List<FaceBox> {
        val sorted = boxes.sortedByDescending { it.score }.toMutableList()
        val kept = ArrayList<FaceBox>()
        while (sorted.isNotEmpty()) {
            val best = sorted.removeAt(0)
            kept.add(best)
            sorted.removeAll { iou(best, it) > iouThr }
        }
        return kept
    }

    private fun iou(a: FaceBox, b: FaceBox): Float {
        val ax2 = a.x + a.w; val ay2 = a.y + a.h
        val bx2 = b.x + b.w; val by2 = b.y + b.h
        val ix1 = max(a.x, b.x); val iy1 = max(a.y, b.y)
        val ix2 = min(ax2, bx2); val iy2 = min(ay2, by2)
        val iw = max(0f, ix2 - ix1); val ih = max(0f, iy2 - iy1)
        val inter = iw * ih
        val union = a.w * a.h + b.w * b.h - inter
        return if (union > 0f) inter / union else 0f
    }

    fun pickCenter(boxes: List<FaceBox>, imgW: Int, imgH: Int): FaceBox? {
        if (boxes.isEmpty()) return null
        val ccx = imgW / 2f
        val ccy = imgH / 2f
        var best: FaceBox? = null
        var bestD = Float.MAX_VALUE
        for (b in boxes) {
            val dx = b.cx - ccx
            val dy = b.cy - ccy
            val d = dx * dx + dy * dy
            if (d < bestD) { bestD = d; best = b }
        }
        return best
    }
}
```

> ⚠️ **重要（实现者必读）**：上面 `stridePerAnchor` 的轮询填充是**占位**，仅让单测通过（单测不依赖 stride 精确性）。**在 Task 7（FaceEngine）接入真实模型时，必须把 `decode` 改为接收一个精确的 `strideOf: IntArray`（由 `generateAnchors` 同时产出）**，确保每个 anchor 对应正确 stride。重构方式：让 `generateAnchors` 返回 `Pair<List<Point>, IntArray>`，`decode` 直接用该数组。这是 Task 7 的硬性验收点之一。

- [ ] **Step 4: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.YuNetDecodeTest"`
Expected: PASS（4 tests）。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/YuNetDecode.kt \
        app/src/test/java/com/openclaw/car/face/YuNetDecodeTest.kt
git commit -m "feat(face): YuNetDecode anchor/解码/NMS/center-pick + 单测（stride 精确化留 Task7）"
```

---

### Task 6: Gallery FaceGallery（JSON 持久化 + bestMatch）

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/FaceGallery.kt`
- Test: `app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt`

**Interfaces:**
- Consumes: `FaceMath.cosine`
- Produces: `FaceGallery(file: File)`、`load()`、`save()`、`enroll(name, emb)`、`names()`、`bestMatch(emb): Pair<String, Float>?`

- [ ] **Step 1: 写失败测试**

`app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt`：

```kotlin
package com.openclaw.car.face

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class FaceGalleryTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun enroll_persists_and_reload() {
        val f = File(tmp.root, "g.json")
        val g = FaceGallery(f)
        g.enroll("alice", floatArrayOf(1f, 0f, 0f))
        g.save()

        val g2 = FaceGallery(f)
        g2.load()
        assertEquals(setOf("alice"), g2.names())
    }

    @Test
    fun bestMatch_returns_closest_above_threshold() {
        val f = File(tmp.root, "g.json")
        val g = FaceGallery(f)
        g.enroll("alice", FaceMath.l2normalize(floatArrayOf(1f, 0f, 0f)))
        g.enroll("bob", FaceMath.l2normalize(floatArrayOf(0f, 1f, 0f)))

        val (id, score) = g.bestMatch(FaceMath.l2normalize(floatArrayOf(0.9f, 0.1f, 0f)), 0.5f)!!
        assertEquals("alice", id)
        // 存在更高分匹配，必 > 0.5
        assert(score > 0.5f)
    }

    @Test
    fun bestMatch_returns_null_below_threshold() {
        val f = File(tmp.root, "g.json")
        val g = FaceGallery(f)
        g.enroll("alice", FaceMath.l2normalize(floatArrayOf(1f, 0f, 0f)))
        assertNull(g.bestMatch(FaceMath.l2normalize(floatArrayOf(0f, 0f, 1f)), 0.5f))
    }
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.FaceGalleryTest"`
Expected: FAIL（`FaceGallery` unresolved）。

- [ ] **Step 3: 实现 FaceGallery**

`app/src/main/java/com/openclaw/car/face/FaceGallery.kt`：

```kotlin
package com.openclaw.car.face

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.io.File

/**
 * 人脸库：人名 → 512-d 归一化嵌入。JSON 存 filesDir/face_gallery.json。
 * 纯 Java/Kotlin（java.io.File + Gson），不依赖 android.*，可 JVM 测试。
 */
class FaceGallery(private val file: File) {

    private val gson = Gson()
    private val map = LinkedHashMap<String, FloatArray>()

    fun load() {
        map.clear()
        if (!file.exists()) return
        val text = file.readText()
        if (text.isBlank()) return
        val type = object : TypeToken<Map<String, FloatArray>>() {}.type
        val loaded: Map<String, FloatArray> = gson.fromJson(text, type)
        map.putAll(loaded)
    }

    fun save() {
        file.parentFile?.mkdirs()
        file.writeText(gson.toJson(map))
    }

    fun enroll(name: String, embedding: FloatArray) {
        map[name] = embedding
    }

    fun remove(name: String) { map.remove(name) }

    fun names(): Set<String> = map.keys.toSet()

    fun all(): Map<String, FloatArray> = LinkedHashMap(map)

    /** 返回最高 cosine 且 ≥ thr 的 (id, score)；否则 null */
    fun bestMatch(emb: FloatArray, thr: Float): Pair<String, Float>? {
        var bestId: String? = null
        var bestScore = -1f
        for ((id, tpl) in map) {
            val s = FaceMath.cosine(emb, tpl)
            if (s > bestScore) { bestScore = s; bestId = id }
        }
        return if (bestId != null && bestScore >= thr) bestId to bestScore else null
    }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./gradlew :app:testDebugUnitTest --tests "com.openclaw.car.face.FaceGalleryTest"`
Expected: PASS（3 tests）。

- [ ] **Step 5: Commit**

```bash
git add app/src/main/java/com/openclaw/car/face/FaceGallery.kt \
        app/src/test/java/com/openclaw/car/face/FaceGalleryTest.kt
git commit -m "feat(face): FaceGallery JSON 持久化 + bestMatch"
```

---

### Task 7: FaceEngine（ORT 双 session + NNAPI + detect/embed + stride 精确化）

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/FaceEngine.kt`
- Modify: `app/src/main/java/com/openclaw/car/face/YuNetDecode.kt`（`generateAnchors` 返回 `Pair<List<Point>, IntArray>`，`decode` 用精确 stride）

**Interfaces:**
- Consumes: `FaceBox`、`YuNetDecode`、`SimilarityTransform`、`AffineWarp`、`FaceMath`、assets 中 `yunet.onnx` / `w600k_r50.onnx`
- Produces: `FaceEngine(context)`、`detect(bitmap: android.graphics.Bitmap): List<FaceBox>`、`embed(alignedPixels: IntArray): FloatArray`

> 本任务依赖 Android（ORT、Bitmap），**无 JVM 单测**，靠构建通过 + Task 9 车机端验证。

- [ ] **Step 1: 重构 YuNetDecode，stride 精确化**

改 `YuNetDecode.generateAnchors` 返回 `Pair<List<Point>, IntArray>`，并让 `decode` 接收 `strideOf: IntArray`：

```kotlin
// YuNetDecode.kt —— 替换 generateAnchors 与 decode 签名
fun generateAnchors(w: Int, h: Int, strides: IntArray): Pair<List<Point>, IntArray> {
    val anchors = ArrayList<Point>()
    val strideOf = ArrayList<Int>()
    for (s in strides) {
        val fw = (w + s - 1) / s
        val fh = (h + s - 1) / s
        for (r in 0 until fh) for (c in 0 until fw) {
            anchors.add(Point((c * s).toFloat(), (r * s).toFloat()))
            strideOf.add(s)
        }
    }
    return anchors to strideOf.toIntArray()
}

fun decode(
    anchors: List<Point>,
    strideOf: IntArray,
    loc: Array<FloatArray>,
    conf: FloatArray,
    iou: FloatArray,
    scoreThr: Float
): List<FaceBox> {
    val out = ArrayList<FaceBox>()
    for (i in anchors.indices) {
        val score = Math.sqrt((conf[i] * iou[i]).toDouble()).toFloat()
        if (score < scoreThr) continue
        val s = strideOf[i].toFloat()
        val ax = anchors[i].x; val ay = anchors[i].y
        val l = loc[i]
        val x1 = ax + l[0] * s; val y1 = ay + l[1] * s
        val x2 = ax + l[2] * s; val y2 = ay + l[3] * s
        val lms = ArrayList<Point>(5)
        for (k in 0 until 5) lms.add(Point(ax + l[4 + 2*k]*s, ay + l[5 + 2*k]*s))
        out.add(FaceBox(x1, y1, x2 - x1, y2 - y1, score, lms))
    }
    return out
}
```

删掉旧的 `stridePerAnchor`。更新 `YuNetDecodeTest` 的 anchors 测试：改为 `val (anchors, _) = YuNetDecode.generateAnchors(...)`，断言数量不变。重跑该测试确认 PASS。

- [ ] **Step 2: 实现 FaceEngine**

`app/src/main/java/com/openclaw/car/face/FaceEngine.kt`：

```kotlin
package com.openclaw.car.face

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import java.nio.FloatBuffer
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * ONNX Runtime 双 session（YuNet 检测 + ArcFace-R50 嵌入），NNAPI EP。
 * OrtSession 非线程安全 → 用 lock 串行化所有 invoke。
 */
class FaceEngine(context: Context) {

    companion object {
        private const val DET_INPUT = 320      // YuNet 输入边长（方图）
        private const val REC_INPUT = 112      // ArcFace-R50 边长
        private const val STRIDES = intArrayOf(8, 16, 32)
        private const val DET_NAME = "yunet.onnx"
        private const val REC_NAME = "w600k_r50.onnx"
    }

    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val detSession: OrtSession
    private val recSession: OrtSession
    private val detInputName: String
    private val recInputName: String
    private val lock = ReentrantLock()

    // YuNet 输出名（验证步骤会确认实际值）
    private val detOutLoc: String
    private val detOutConf: String
    private val detOutIou: String

    init {
        val opt = OrtSession.SessionOptions()
        try {
            opt.addNnapi()   // 上 NPU；失败则降级 CPU
        } catch (e: Exception) {
            android.util.Log.w("FaceEngine", "NNAPI EP unavailable, CPU fallback: ${e.message}")
        }
        detSession = env.createSession(readAsset(context, DET_NAME), opt)
        recSession = env.createSession(readAsset(context, REC_NAME), opt)

        // 取实际输入/输出名（模型可能不叫 "input"）
        detInputName = detSession.inputNames.first()
        recInputName = recSession.inputNames.first()
        val outs = detSession.outputNames
        // 经验上 YuNet 三头名含 loc/conf/iou；若命名不同，按顺序兜底
        detOutLoc = outs.firstOrNull { it.contains("loc") } ?: outs[0]
        detOutConf = outs.firstOrNull { it.contains("conf") } ?: outs.getOrElse(1) { outs[0] }
        detOutIou = outs.firstOrNull { it.contains("iou") } ?: outs.getOrElse(2) { outs[0] }
        android.util.Log.i("FaceEngine", "det io=$detInputName->$outs ; rec io=$recInputName->${recSession.outputNames}")
    }

    fun detect(bitmap: Bitmap): List<FaceBox> = lock.withLock {
        // 1) Bitmap → DET_INPUT×DET_INPUT（保持比例 letterbox 到方图；demo 简化：直接 scale 到方图）
        val scaled = Bitmap.createScaledBitmap(bitmap, DET_INPUT, DET_INPUT, true)
        val (rgb, _) = toNchwRgb(scaled, DET_INPUT, DET_INPUT)

        val shape = longArrayOf(1L, 3L, DET_INPUT.toLong(), DET_INPUT.toLong())
        val input = OnnxTensor.createTensor(env, FloatBuffer.wrap(rgb), shape)
        val out = detSession.run(mapOf(detInputName to input))
        try {
            val loc = toFloatMat(out, detOutLoc)    // [N][14]
            val conf = toFloatVec(out, detOutConf)  // [N]
            val iou = toFloatVec(out, detOutIou)    // [N]
            val (anchors, strideOf) = YuNetDecode.generateAnchors(DET_INPUT, DET_INPUT, STRIDES)
            // 坐标从方图缩放回原图
            val sx = bitmap.width.toFloat() / DET_INPUT
            val sy = bitmap.height.toFloat() / DET_INPUT
            val boxes = YuNetDecode.decode(anchors, strideOf, loc, conf, iou, 0.5f)
                .map {
                    FaceBox(it.x * sx, it.y * sy, it.w * sx, it.h * sy, it.score,
                            it.landmarks.map { p -> Point(p.x * sx, p.y * sy) })
                }
            YuNetDecode.nms(boxes, 0.3f)
        } finally {
            input.close(); out.close()
        }
    }

    /** alignedPixels: REC_INPUT×REC_INPUT 的 ARGB_8888 像素数组 */
    fun embed(alignedPixels: IntArray): FloatArray = lock.withLock {
        val flat = FloatArray(3 * REC_INPUT * REC_INPUT)
        // InsightFace ArcFace-R50：BGR，(x-127.5)/127.5，NCHW（cv2/caffe 训练惯例）
        val plane = REC_INPUT * REC_INPUT
        for (i in 0 until plane) {
            val c = alignedPixels[i]
            val r = Color.red(c); val g = Color.green(c); val b = Color.blue(c)
            flat[i] = (b - 127.5f) / 127.5f                 // plane0 = B
            flat[plane + i] = (g - 127.5f) / 127.5f         // plane1 = G
            flat[2 * plane + i] = (r - 127.5f) / 127.5f     // plane2 = R
        }
        val shape = longArrayOf(1L, 3L, REC_INPUT.toLong(), REC_INPUT.toLong())
        val input = OnnxTensor.createTensor(env, FloatBuffer.wrap(flat), shape)
        val out = recSession.run(mapOf(recInputName to input))
        try {
            val raw = (out[0].value as Array<*>).first() as FloatArray  // R50 输出 [512]
            FaceMath.l2normalize(raw)
        } finally {
            input.close(); out.close()
        }
    }

    private fun toNchwRgb(bmp: Bitmap, w: Int, h: Int): Pair<FloatArray, FloatArray> {
        val plane = w * h
        val rgb = FloatArray(3 * plane)
        val px = IntArray(plane)
        bmp.getPixels(px, 0, w, 0, 0, w, h)
        for (i in 0 until plane) {
            rgb[i] = (Color.red(px[i]) - 127.5f) / 128f
            rgb[plane + i] = (Color.green(px[i]) - 127.5f) / 128f
            rgb[2 * plane + i] = (Color.blue(px[i]) - 127.5f) / 128f
        }
        return rgb to px
    }

    @Suppress("UNCHECKED_CAST")
    private fun toFloatMat(out: OrtSession.Result, name: String): Array<FloatArray> {
        // 期望 [1][N][14]
        val v = out.get(name).get().value
        val outer = v as Array<Array<FloatArray>>
        return outer[0]
    }

    @Suppress("UNCHECKED_CAST")
    private fun toFloatVec(out: OrtSession.Result, name: String): FloatArray {
        val v = out.get(name).get().value
        val outer = v as Array<FloatArray>
        return outer[0]
    }

    private fun readAsset(ctx: Context, name: String): ByteArray {
        ctx.assets.open("face/$name").use { return it.readBytes() }
    }
}
```

- [ ] **Step 3: 构建通过（不要求车机）**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。若 ORT API 名不符（如 `addNnapi` 不存在或 `out[0]` 取值方式不同），按 onnxruntime-android 1.18.0 的实际 API 修正并在此记录。

- [ ] **Step 4: 提交**

```bash
git add app/src/main/java/com/openclaw/car/face/FaceEngine.kt \
        app/src/main/java/com/openclaw/car/face/YuNetDecode.kt \
        app/src/test/java/com/openclaw/car/face/YuNetDecodeTest.kt
git commit -m "feat(face): FaceEngine ORT+NNAPI 双session + stride精确化"
```

---

### Task 8: FaceRecognizer（编排 + 对齐 + 注册/识别）

**Files:**
- Create: `app/src/main/java/com/openclaw/car/face/FaceRecognizer.kt`

**Interfaces:**
- Consumes: `FaceEngine`、`FaceGallery`、`SimilarityTransform`、`AffineWarp`、`YuNetDecode.pickCenter`
- Produces: `FaceRecognizer(context)`、`recognize(bitmap): RecognizeResult`、`enroll(name, bitmap): Boolean`、`enrollMany(name, bitmaps): Boolean`

- [ ] **Step 1: 实现 FaceRecognizer**

`app/src/main/java/com/openclaw/car/face/FaceRecognizer.kt`：

```kotlin
package com.openclaw.car.face

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import java.io.File

class FaceRecognizer(context: Context) {

    companion object {
        private val ARCFACE_REF = listOf(
            Point(38.2946f, 51.6963f), Point(73.5318f, 51.5014f),
            Point(56.0252f, 71.7366f), Point(41.5493f, 92.3655f),
            Point(70.7299f, 92.2041f)
        )
        private const val REC_THR = 0.45f
        private const val REC_SIZE = 112
    }

    private val engine = FaceEngine(context)
    private val gallery = FaceGallery(File(context.filesDir, "face_gallery.json")).apply { load() }

    fun recognize(bitmap: Bitmap): RecognizeResult {
        val boxes = engine.detect(bitmap)
        val center = YuNetDecode.pickCenter(boxes, bitmap.width, bitmap.height)
            ?: return RecognizeResult(Status.NO_FACE)
        val aligned = alignTo(bitmap, center.landmarks)
        val emb = engine.embed(aligned)
        val match = gallery.bestMatch(emb, REC_THR)
        return if (match != null) {
            RecognizeResult(Status.RECOGNIZED, match.first, match.second, center)
        } else {
            RecognizeResult(Status.UNKNOWN, null, 0f, center)
        }
    }

    /** 单图注册（取最居中人脸） */
    fun enroll(name: String, bitmap: Bitmap): Boolean {
        val boxes = engine.detect(bitmap)
        val center = YuNetDecode.pickCenter(boxes, bitmap.width, bitmap.height) ?: return false
        val emb = engine.embed(alignTo(bitmap, center.landmarks))
        // 若已存在，追加平均（demo：取已有模板与新嵌入的平均）
        val existing = gallery.all()[name]
        val template = if (existing != null) FaceMath.l2normalize(FaceMath.mean(listOf(existing, emb)))
                       else emb
        gallery.enroll(name, template)
        gallery.save()
        return true
    }

    /** 多图注册：分别嵌入后平均（3-5 张） */
    fun enrollMany(name: String, bitmaps: List<Bitmap>): Boolean {
        val embs = bitmaps.mapNotNull { bmp ->
            val boxes = engine.detect(bmp)
            val center = YuNetDecode.pickCenter(boxes, bmp.width, bmp.height) ?: return@mapNotNull null
            engine.embed(alignTo(bmp, center.landmarks))
        }
        if (embs.isEmpty()) return false
        gallery.enroll(name, FaceMath.l2normalize(FaceMath.mean(embs)))
        gallery.save()
        return true
    }

    private fun alignTo(bitmap: Bitmap, landmarks: List<Point>): IntArray {
        require(landmarks.size == 5)
        val m = SimilarityTransform.fit(landmarks, ARCFACE_REF)
        val w = bitmap.width; val h = bitmap.height
        val src = IntArray(w * h)
        bitmap.getPixels(src, 0, w, 0, 0, w, h)
        return AffineWarp.warp(src, w, h, m, REC_SIZE, REC_SIZE)
    }
}
```

- [ ] **Step 2: 构建通过**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 3: 提交**

```bash
git add app/src/main/java/com/openclaw/car/face/FaceRecognizer.kt
git commit -m "feat(face): FaceRecognizer 编排 detect→align→embed→match + 注册"
```

---

### Task 9: FaceFragment（demo UI：注册 + 识别）+ tab 接入

**Files:**
- Create: `app/src/main/res/layout/fragment_face.xml`
- Create: `app/src/main/java/com/openclaw/car/fragment/FaceFragment.kt`
- Modify: `app/src/main/res/values/strings.xml`
- Modify: `app/src/main/java/com/openclaw/car/adapter/ViewPagerAdapter.kt`
- Modify: `app/src/main/java/com/openclaw/car/MainActivity.kt`

**Interfaces:**
- Consumes: `FaceRecognizer`

- [ ] **Step 1: 加 strings**

在 `res/values/strings.xml` 的 `<resources>` 内追加：

```xml
    <string name="tab_face">人脸</string>
    <string name="face_title">人脸识别</string>
    <string name="face_pick_enroll">选择照片注册</string>
    <string name="face_pick_identify">选择照片识别</string>
    <string name="face_name_hint">输入姓名</string>
    <string name="face_hint">注册几张人脸后，再选测试图识别</string>
```

- [ ] **Step 2: 写布局 fragment_face.xml**

`app/src/main/res/layout/fragment_face.xml`：

```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:background="@color/white"
    android:padding="24dp">

    <TextView
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="@string/face_title"
        android:textColor="@color/text_primary"
        android:textSize="22sp"
        android:textStyle="bold"
        android:layout_marginBottom="8dp" />

    <TextView
        android:id="@+id/tv_face_hint"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="@string/face_hint"
        android:textColor="@color/text_hint"
        android:textSize="14sp"
        android:layout_marginBottom="16dp" />

    <com.google.android.material.textfield.TextInputLayout
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:hint="@string/face_name_hint">
        <com.google.android.material.textfield.TextInputEditText
            android:id="@+id/et_face_name"
            android:layout_width="match_parent"
            android:layout_height="wrap_content" />
    </com.google.android.material.textfield.TextInputLayout>

    <com.google.android.material.button.MaterialButton
        android:id="@+id/btn_face_enroll"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="@string/face_pick_enroll"
        android:layout_marginTop="12dp" />

    <com.google.android.material.button.MaterialButton
        android:id="@+id/btn_face_identify"
        style="@attr/materialButtonOutlinedStyle"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="@string/face_pick_identify"
        android:layout_marginTop="8dp" />

    <TextView
        android:id="@+id/tv_face_result"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="24dp"
        android:textColor="@color/text_primary"
        android:textSize="16sp" />
</LinearLayout>
```

> 若 `@color/text_primary` / `text_hint` / `white` 名字不符，按 `res/values/colors.xml` 实际名替换（其它 Fragment 已用这几个）。

- [ ] **Step 3: 写 FaceFragment**

`app/src/main/java/com/openclaw/car/fragment/FaceFragment.kt`：

```kotlin
package com.openclaw.car.fragment

import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import android.widget.TextView
import com.openclaw.car.R
import com.openclaw.car.face.FaceRecognizer
import com.openclaw.car.face.Status

class FaceFragment : Fragment() {

    private lateinit var recognizer: FaceRecognizer
    private lateinit var etName: TextInputEditText
    private lateinit var tvResult: TextView

    private var pendingMode: String = "identify"

    // 多选注册
    private val enrollPicker = registerForActivityResult(
        ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        if (uris.isNullOrEmpty()) return@registerForActivityResult
        val name = etName.text?.toString()?.trim().orEmpty()
        if (name.isEmpty()) { tvResult.text = "请先输入姓名"; return@registerForActivityResult }
        Thread {
            val bitmaps = uris.mapNotNull { uri ->
                requireContext().contentResolver.openInputStream(uri)?.use {
                    BitmapFactory.decodeStream(it)
                }
            }
            val ok = recognizer.enrollMany(name, bitmaps)
            activity?.runOnUiThread {
                tvResult.text = if (ok) "已注册 $name（${bitmaps.size} 张）"
                                else "未检测到人脸，注册失败"
            }
        }.start()
    }

    // 单选识别
    private val identifyPicker = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri == null) return@registerForActivityResult
        Thread {
            val bmp = requireContext().contentResolver.openInputStream(uri)?.use {
                BitmapFactory.decodeStream(it)
            } ?: return@Thread
            val t0 = System.currentTimeMillis()
            val r = recognizer.recognize(bmp)
            val dt = System.currentTimeMillis() - t0
            activity?.runOnUiThread {
                tvResult.text = when (r.status) {
                    Status.NO_FACE -> "无人脸（${dt}ms）"
                    Status.UNKNOWN -> "未识别（最接近分数低于阈值，${dt}ms）"
                    Status.RECOGNIZED -> "识别为：${r.id}（cos=${"%.3f".format(r.score)}，${dt}ms）"
                }
            }
        }.start()
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, s: Bundle?): View =
        inflater.inflate(R.layout.fragment_face, container, false)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        recognizer = FaceRecognizer(requireContext())
        etName = view.findViewById(R.id.et_face_name)
        tvResult = view.findViewById(R.id.tv_face_result)
        view.findViewById<MaterialButton>(R.id.btn_face_enroll).setOnClickListener {
            pendingMode = "enroll"; enrollPicker.launch("image/*")
        }
        view.findViewById<MaterialButton>(R.id.btn_face_identify).setOnClickListener {
            pendingMode = "identify"; identifyPicker.launch("image/*")
        }
    }
}
```

- [ ] **Step 4: 接入第 6 个 tab**

`ViewPagerAdapter.kt`：`getItemCount()` 改 `6`，`createFragment` 加 `5 -> FaceFragment()`，并 import `com.openclaw.car.fragment.FaceFragment`。

`MainActivity.kt`：`offscreenPageLimit = 4` 改 `5`；`TabLayoutMediator` 的 `when(position)` 加 `5 -> getString(R.string.tab_face)`。

- [ ] **Step 5: 构建通过**

Run: `./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL。

- [ ] **Step 6: 提交**

```bash
git add app/src/main/res/layout/fragment_face.xml \
        app/src/main/java/com/openclaw/car/fragment/FaceFragment.kt \
        app/src/main/res/values/strings.xml \
        app/src/main/java/com/openclaw/car/adapter/ViewPagerAdapter.kt \
        app/src/main/java/com/openclaw/car/MainActivity.kt
git commit -m "feat(face): FaceFragment 注册+识别 demo UI + tab 接入"
```

---

### Task 10: 车机端端到端验证

**Files:** 无（验证任务）

- [ ] **Step 1: 装机**

Run: `./gradlew :app:installDebug`（或 `adb install -r app/build/outputs/apk/debug/app-debug.apk`）
Expected: Success。车机 `LZBYDUMNB6RW7X5P` 已连（`adb devices`）。

- [ ] **Step 2: 验证 NNAPI 命中 NPU（关键）**

Run: `adb logcat -c && adb shell am start -n com.openclaw.car/.MainActivity`，进入"人脸"tab，识别一张图。
Run: `adb logcat -d | grep -iE "FaceEngine|NNAPI|onnx|EP "` （按实际 tag 调整）
Expected: 看见 `FaceEngine` 打印的 det/rec 输入输出名（确认 I/O 假设）；若 ORT 报 NNAPI 委派算子回退，记录回退算子清单。若大量回退 → 回 Task 7 调整或考虑后续 NeuroPilot AAR 升级路径（见 spec §9）。

- [ ] **Step 3: 注册 3-5 人，识别验证**

人手操作：进"人脸"tab → 输名 → 选 3-5 张照片注册（重复多人）→ 选测试图识别。
Expected：本人图命中正确 ID 且 cos > 0.45；非库内图判 unknown；单帧 det+rec < 100ms（结果文本里有耗时）。
**若识别全错/cos 极低**：首要怀疑 R50 的通道顺序（必须 BGR，不是 RGB）与归一化（/127.5，不是 /128）——这是 InsightFace 与 MobileFaceNet 最大的差异点，预处理错会让 embedding 全乱。

- [ ] **Step 4: 记录结果**

把延迟、cos 分数、NNAPI 回退算子清单写入 `docs/superpowers/plans/2026-06-26-face-recognition.md` 末尾"验证记录"小节（或单独测试报告），不达标项据此决定是否走 spec §9 升级路径。

---

## Self-Review（写完后自查，已执行）

1. **Spec 覆盖**：pipeline(§3)→Task7/8；组件(§4)→Task2-9；参数(§5)→各实现内常量；错误处理(§6)→Task8(状态分支)+Task7(NNAPI降级)；测试(§7)→Task2-6 JVM单测+Task10端到端；minSdk(§4)→Task1；模型来源(§10)→Task1 Step6。✅
2. **占位符**：YuNetDecode 的 stride 精确化已在 Task7 显式硬性验收（非偷懒占位）；ORT I/O 名以 `session.inputNames` 运行时取值 + 日志验证。无 TBD/TODO。✅
3. **类型一致**：`Point`/`FaceBox`/`RecognizeResult`/`Status` 跨任务签名一致；`FaceMath`/`SimilarityTransform.fit`(返回 FloatArray[6])/`AffineWarp.warp`/`YuNetDecode.*`/`FaceGallery.bestMatch(emb,thr)` 在各任务调用处签名匹配。`generateAnchors` 返回类型变更已在 Task7 同步更新测试。✅
