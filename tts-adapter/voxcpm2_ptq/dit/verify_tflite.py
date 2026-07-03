#!/usr/bin/env python3
"""验证 dit_float.tflite vs pytorch(patch) 输出一致性 + 测速。"""
import os, time
import numpy as np
import torch

PT = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/dit_scripted_v2.pt"
TFLITE = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit/dit_float.tflite"

# pytorch 参考
scripted = torch.jit.load(PT).eval()
torch.manual_seed(42)
dummy = [torch.randn(2, 64, 4), torch.randn(2, 2048), torch.rand(2),
         torch.randn(2, 64, 4), torch.zeros(2)]
with torch.no_grad():
    pt_out = scripted(*dummy)
pt_arr = pt_out.numpy()

# tflite
try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    import tensorflow as tf
    Interpreter = lambda m: tf.lite.Interpreter(model_path=m)

interp = Interpreter(TFLITE)
interp.allocate_tensors()
in_d = interp.get_input_details()
out_d = interp.get_output_details()
print(f"tflite inputs: {[(d['name'], list(d['shape'])) for d in in_d]}")
print(f"tflite outputs: {[(d['name'], list(d['shape'])) for d in out_d]}")

for i, t in enumerate(dummy):
    interp.set_tensor(in_d[i]["index"], t.numpy().astype(np.float32))
interp.invoke()
tfl_arr = interp.get_tensor(out_d[0]["index"])

cos = float(np.dot(pt_arr.flatten(), tfl_arr.flatten()) /
            (np.linalg.norm(pt_arr) * np.linalg.norm(tfl_arr)))
max_diff = float(np.max(np.abs(pt_arr - tfl_arr)))
print(f"\nfloat tflite vs pytorch: cosine={cos:.6f}, max_abs_diff={max_diff:.6e}")
print(f"shape pt={pt_arr.shape} tfl={tfl_arr.shape}")

# 测速（单步 DiT，CPU）
t0 = time.time()
for _ in range(3):
    for i, t in enumerate(dummy):
        interp.set_tensor(in_d[i]["index"], t.numpy().astype(np.float32))
    interp.invoke()
dt = (time.time() - t0) / 3
print(f"\n单步 DiT CPU 耗时: {dt*1000:.0f}ms（10步 Euler + CFG ≈ {dt*10*2*1000:.0f}ms 估算）")
