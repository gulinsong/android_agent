#!/usr/bin/env python3
"""用 mtk_converter.PyTorchConverter Python API 转 DiT（参考 SD mlkits pt2tflite.py）。

绕开 mtk_onnx_converter（opset 版本地狱）和 mtk_pytorch_converter CLI（aten::index），
直接从 TorchScript 用 API 转 tflite。先 float 验证路径。
"""
import os
import mtk_converter

PT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/dit_scripted_v2.pt"
OUT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/dit_float.tflite"

# DiT 输入: x(2,64,4) mu(2,2048) t(2,) cond(2,64,4) dt(2,)
INPUTS_SHAPE = [(2, 64, 4), (2, 2048), (2,), (2, 64, 4), (2,)]

print("PyTorchConverter.from_script_module_file...")
converter = mtk_converter.PyTorchConverter.from_script_module_file(PT, INPUTS_SHAPE)
converter.quantize = False  # 先 float
print("convert_to_tflite (float)...")
converter.convert_to_tflite(output_file=OUT)
print(f"✓ 完成: {OUT} ({os.path.getsize(OUT)/1e6:.1f}MB)")
