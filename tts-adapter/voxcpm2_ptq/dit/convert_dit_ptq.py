#!/usr/bin/env python3
"""PTQ 量化 DiT（8w16a），参考 SD mlkits pt2tflite.py。

v4: 输入接口 (x, mu, t_emb, cond, dt_emb)，t_emb/dt_emb 是外部化的时间嵌入。
calib_gen 内联 SinusoidalPosEmb 数学（cat(sin(scale*t*freqs), cos(...))）造 t_emb。
"""
import os
import json
import math
import numpy as np
import mtk_converter

DIT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit"
PT = os.path.join(DIT_DIR, "dit_scripted_v4.pt")
OUT = os.path.join(DIT_DIR, "dit_quant8w16a_mha_extemb.tflite")

with open(os.path.join(DIT_DIR, "dit_v4_input_shapes.json")) as f:
    INPUTS_SHAPE = json.load(f)["inputs"]
# 期望 [(2,64,4),(2,2048),(2,H),(2,64,4),(2,H)]
T_DIM = INPUTS_SHAPE[2][-1]   # hidden_size（t_emb 最后一维）
print(f"输入 shape: {INPUTS_SHAPE}  t_emb dim={T_DIM}")


def _sinusoidal_np(t, dim, scale=1000.0):
    """复刻 SinusoidalPosEmb：t:(N,) → (N, dim)。"""
    half = dim // 2
    emb = math.log(10000) / (half - 1)
    freqs = np.exp(-np.arange(half, dtype=np.float32) * emb)        # (half,)
    args = scale * t[:, None] * freqs[None, :]                       # (N, half)
    return np.concatenate([np.sin(args), np.cos(args)], axis=-1).astype(np.float32)


def calib_gen():
    """合成校准数据：x/cond latent 小范围，mu hidden 小范围，t∈[0,1] → sinusoidal t_emb。"""
    rng = np.random.default_rng(42)
    for _ in range(16):
        x = rng.standard_normal((2, 64, 4)).astype(np.float32) * 0.5
        mu = rng.standard_normal((2, 2048)).astype(np.float32) * 0.1
        cond = rng.standard_normal((2, 64, 4)).astype(np.float32) * 0.5
        t = rng.random(2).astype(np.float32)            # CFM timestep [0,1]
        dt = (rng.random(2).astype(np.float32) * 0.1)   # delta 小
        t_emb = _sinusoidal_np(t, T_DIM)
        dt_emb = _sinusoidal_np(dt, T_DIM)
        yield [x, mu, t_emb, cond, dt_emb]


converter = mtk_converter.PyTorchConverter.from_script_module_file(PT, INPUTS_SHAPE)
converter.quantize = True
converter.calibration_data_gen = calib_gen
converter.calibration_method = "Histogram"
converter.calibration_histogram_loss_type = "l2_loss"
converter.precision_proportion = {"sym8W_sym16A": 1.0}  # 8bit weight + 16bit activation
converter.prepend_input_quantize_ops = True
converter.append_output_dequantize_ops = True
print("PTQ 量化 DiT v4 (mha + 外部 t_emb, 8w16a)...")
converter.convert_to_tflite(output_file=OUT)
print(f"✓ {OUT} ({os.path.getsize(OUT)/1e6:.1f}MB)")
