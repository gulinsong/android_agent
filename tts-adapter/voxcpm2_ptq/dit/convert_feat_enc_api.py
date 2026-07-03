#!/usr/bin/env python3
"""PyTorchConverter 转 feat_encoder tflite（float）。"""
import os
import mtk_converter

PT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/feat_encoder.pt"
OUT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/feat_encoder.tflite"

# feat_encoder 输入 (B=1, T=1, P=4, D=64)
INPUTS_SHAPE = [(1, 1, 4, 64)]

converter = mtk_converter.PyTorchConverter.from_script_module_file(PT, INPUTS_SHAPE)
converter.quantize = False
print("convert feat_encoder (float)...")
converter.convert_to_tflite(output_file=OUT)
print(f"✓ {OUT} ({os.path.getsize(OUT)/1e6:.1f}MB)")
