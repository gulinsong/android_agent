#!/usr/bin/env python3
"""Task 2 TorchScript 路径：trace DiT 为 TorchScript（绕开 onnx opset 版本地狱）。

mtk_converter 老版不支持 onnx opset 18 的新 op（Reshape allowzero / Split num_outputs 等），
改走 mtk_pytorch_converter（TorchScript 输入），不经 onnx importer。
DiT forward 无控制流（纯 tensor op），trace 友好。
"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
from voxcpm import VoxCPM

MODEL_PATH = "/home/tsm/work/models/VoxCPM2"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit"

print("加载 VoxCPM2 (CPU)...")
model = VoxCPM.from_pretrained(MODEL_PATH, load_denoiser=False)
dit = model.tts_model.feat_decoder.estimator
dit.eval().cpu().float()

torch.manual_seed(42)
dummy = (torch.randn(2, 64, 4), torch.randn(2, 2048), torch.rand(2),
         torch.randn(2, 64, 4), torch.zeros(2))

with torch.no_grad():
    pt_out = dit(*dummy)

print("TorchScript trace...")
scripted = torch.jit.trace(dit, dummy, check_trace=False)
pt_path = os.path.join(OUT_DIR, "dit_scripted.pt")
scripted.save(pt_path)
print(f"保存 {pt_path} ({os.path.getsize(pt_path)/1e6:.0f}MB)")

with torch.no_grad():
    traced_out = scripted(*dummy)
cosine = torch.dot(pt_out.flatten(), traced_out.flatten()) / (pt_out.norm() * traced_out.norm())
print(f"trace vs pytorch cosine: {cosine:.6f}")
assert cosine > 0.999
print("✓ TorchScript trace 完成")
