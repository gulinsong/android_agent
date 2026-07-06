#!/usr/bin/env python3
"""PTQ 量化 DiT（8w16a），参考 SD mlkits pt2tflite.py。

float tflite MDLA 不支持（ncc-tflite 报 Cannot support Float32），必须量化。
合成校准数据先验证 PTQ + AOT 流程能跑通（质量留后续真实采样 hook estimator 输入）。
"""
import os
import numpy as np
import mtk_converter

PT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/dit_scripted_v2.pt"
OUT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/dit_quant8w16a.tflite"

INPUTS_SHAPE = [(2, 64, 4), (2, 2048), (2,), (2, 64, 4), (2,)]


def calib_gen():
    """合成校准数据（合理范围：mu 是 hidden 小范围，latent/timestep 中范围）。
    后续改真实采样（跑 VoxCPM2.generate hook estimator 输入）提质量。"""
    rng = np.random.default_rng(42)
    for _ in range(16):
        yield [
            rng.standard_normal((2, 64, 4)).astype(np.float32) * 0.5,   # x latent
            rng.standard_normal((2, 2048)).astype(np.float32) * 0.1,    # mu hidden
            rng.random(2).astype(np.float32),                           # t timestep 0-1
            rng.standard_normal((2, 64, 4)).astype(np.float32) * 0.5,   # cond latent
            np.zeros(2, dtype=np.float32),                              # dt
        ]


converter = mtk_converter.PyTorchConverter.from_script_module_file(PT, INPUTS_SHAPE)
converter.quantize = True
converter.calibration_data_gen = calib_gen
converter.calibration_method = "Histogram"
converter.calibration_histogram_loss_type = "l2_loss"
converter.precision_proportion = {"sym8W_sym16A": 1.0}  # 8bit weight + 16bit activation
converter.prepend_input_quantize_ops = True
converter.append_output_dequantize_ops = True
print("PTQ 量化 DiT (8w16a, 合成校准)...")
converter.convert_to_tflite(output_file=OUT)
print(f"✓ {OUT} ({os.path.getsize(OUT)/1e6:.1f}MB)")
