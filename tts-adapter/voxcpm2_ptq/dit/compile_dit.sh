#!/bin/bash
# AOT 编译 DiT quantized tflite → dla（MT6991）。
# 关键：用 SD text_encoder.fp.sh 的 transformer profile（mdla5.5,mvpu2.5 + relax-fp32），
# 不是 unet profile。transformer 的 RoPE sin/cos 要 MVPU，且 relax-fp32 容许残留 fp32 op。
# 配合 convert_dit_patched.py 的 5 patch（RoPE slice / SiLU / RMSNorm / GQA unfold / timestep 外部化）。
set -e

MODEL="${1:-dit_quant8w16a_mha_extemb.tflite}"
REPO="/home/tsm/work/android_agent"
SDK_DIR="$REPO/mtk/neuropilot-sdk-basic-8.0.11-build20260211/neuron_sdk"
NCC="$SDK_DIR/host/bin/ncc-tflite"
SDK_LIB="$SDK_DIR/host/lib"

if [ ! -f "$MODEL" ]; then echo "❌ tflite 不存在: $MODEL"; exit 1; fi

OUT="${MODEL%.tflite}.dla"
echo ">>> AOT 编译 $MODEL → $OUT (MT6991, transformer profile)"

export LD_LIBRARY_PATH="$SDK_LIB:$LD_LIBRARY_PATH"

# transformer profile（mdla5.5 + mvpu2.5 + relax-fp32）+ SD 通用优化 flag
"$NCC" \
    --arch=mdla5.5,mvpu2.5 \
    -O3 \
    --l1-size-kb=7168 \
    --num-mdla=4 \
    --show-memory-summary \
    --relax-fp32 \
    --rewrite-elw-to-gather \
    --opt-accuracy \
    --opt-footprint \
    --fc-to-conv \
    --stable-linearize \
    --gno-non-4d-tiling \
    --mlo \
    -d "$OUT" \
    "$MODEL" \
    2>&1 | tee "compile.$(basename ${MODEL%.tflite}).log"

echo ""
if [ -f "$OUT" ]; then
    echo "✓✓✓ DLA 生成成功: $OUT ($(du -h "$OUT" | cut -f1))"
    echo "→ DiT transformer 可上 MDLA（端侧可行，推翻旧结论）"
else
    echo "✗ DLA 未生成，见上方真实 op 报错"
fi
