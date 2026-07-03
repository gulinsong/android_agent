#!/usr/bin/env python3
"""Task 2: 导出 DiT 为 ONNX（opset 14, dynamo=False, SDPA MATH）。

mtk_converter 8.16 老版不支持：
- fused SDPA + GQA（opset 14 symbolic 不支持 enable_gqa=True）
- opset 18 新 op（Reshape allowzero / Split num_outputs）
解法：dynamo=False 旧 exporter + opset 14 + sdpa_kernel(MATH) 拆解 SDPA 为 MatMul。
"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import torch
from torch.nn.attention import sdpa_kernel, SDPBackend
from voxcpm import VoxCPM

MODEL_PATH = "/home/tsm/work/models/VoxCPM2"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit"

print("加载 VoxCPM2 (CPU)...")
model = VoxCPM.from_pretrained(MODEL_PATH, load_denoiser=False)
dit = model.tts_model.feat_decoder.estimator
dit.eval().cpu().float()

N = 2
torch.manual_seed(42)
dummy = (torch.randn(N, 64, 4), torch.randn(N, 2048), torch.rand(N),
         torch.randn(N, 64, 4), torch.zeros(N))

onnx_path = os.path.join(OUT_DIR, "dit.onnx")
print(f"导出 ONNX (opset 14, dynamo=False, SDPA MATH) -> {onnx_path}...")
with torch.no_grad(), sdpa_kernel([SDPBackend.MATH]):
    pt_out = dit(*dummy)
    torch.onnx.export(
        dit, dummy, onnx_path,
        opset_version=14,
        input_names=["x", "mu", "t", "cond", "dt"],
        output_names=["velocity"],
        dynamo=False,
    )
print(f"  ONNX: {os.path.getsize(onnx_path)/1e6:.1f}MB, pytorch out {tuple(pt_out.shape)}")

import onnxruntime as ort
sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
feeds = {k: v.numpy() for k, v in zip(["x", "mu", "t", "cond", "dt"], dummy)}
onnx_out = sess.run(None, feeds)[0]
pf, of = pt_out.numpy().flatten(), onnx_out.flatten()
cosine = float(np.dot(pf, of) / (np.linalg.norm(pf) * np.linalg.norm(of)))
print(f"onnx vs pytorch cosine: {cosine:.6f}")
assert cosine > 0.999
print("✓ ONNX 导出成功")
