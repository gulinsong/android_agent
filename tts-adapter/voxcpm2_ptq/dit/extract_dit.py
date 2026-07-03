#!/usr/bin/env python3
"""提取 VoxCPM2 DiT（feat_decoder.estimator）为独立 pytorch module。

DiT = VoxCPMLocDiT，非自回归 diffusion transformer（12 层 MiniCPM 同构
+ cond_proj + time_mlp），用于 CFM Euler 10 步去噪。
forward(x, mu, t, cond, dt) -> velocity，x/mu/t/cond/dt 见 local_dit_v2.py。
"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
from voxcpm import VoxCPM

MODEL_PATH = "/home/tsm/work/models/VoxCPM2"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit"

print("加载 VoxCPM2 (load_denoiser=False 跳过 zipenhancer)...")
model = VoxCPM.from_pretrained(MODEL_PATH, load_denoiser=False)
tts = model.tts_model
print(f"  tts_model: {type(tts).__name__}")
print(f"  feat_decoder: {type(tts.feat_decoder).__name__}")

dit = tts.feat_decoder.estimator
print(f"  DiT class: {type(dit).__name__}")
dit.eval()
dit.cpu().float()  # bfloat16 → float32（onnx/tflite 标准 dtype）

# 验证 forward: x(N,64,4) mu(N,2048) t(N,) cond(N,64,4) dt(N,) -> velocity(N,64,4)
N = 2  # CFG batch（条件 + 无条件）
x = torch.randn(N, 64, 4)
mu = torch.randn(N, 2048)
t = torch.rand(N)
cond = torch.randn(N, 64, 4)
dt = torch.zeros(N)
with torch.no_grad():
    out = dit(x, mu, t, cond, dt)
print(f"输出 shape: {tuple(out.shape)} (期望 ({N}, 64, 4))")
assert tuple(out.shape) == (N, 64, 4), f"shape 不符: {out.shape}"

sd_path = os.path.join(OUT_DIR, "dit_model.pt")
torch.save(dit.state_dict(), sd_path)
n_params = sum(p.numel() for p in dit.parameters())
size_mb = os.path.getsize(sd_path) / 1e6
print(f"保存 DiT state_dict ({n_params/1e6:.1f}M params, {size_mb:.0f}MB) -> {sd_path}")
print("✓ Task 1 完成：DiT 提取成功，forward 验证通过")
