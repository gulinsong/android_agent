#!/usr/bin/env python3
"""从 VoxCPM2 model.safetensors 提取主 LM 权重，转为 mtk_llm_sdk MiniCPM 格式。

SDK MiniCPM 期望 HF 标准 key:
    model.embed_tokens.weight / model.layers.0.* / model.norm.weight
VoxCPM2 原始 key:
    base_lm.embed_tokens.weight / base_lm.layers.0.* / base_lm.norm.weight
映射规则: base_lm.<X> -> model.<X>

VoxCPM2 主LM 无独立 lm_head (TTS LM 不预测 vocab token，hidden state 直接送 DiT)，
用 embed_tokens 克隆一份满足 SDK minicpm 的 lm_head 要求
(PTQ 校准只需激活分布，lm_head 精度不影响)。
"""
from safetensors.torch import save_file
from safetensors import safe_open
import torch
import os
import shutil

SRC = "/home/tsm/work/models/VoxCPM2/model.safetensors"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model"
PREFIX = "base_lm."

os.makedirs(OUT_DIR, exist_ok=True)

# 提取 base_lm.* 权重，重映射为 model.* (HF MiniCPM 标准)
extracted = {}
with safe_open(SRC, framework="pt") as f:
    for key in f.keys():
        if key.startswith(PREFIX):
            new_key = "model." + key[len(PREFIX):]
            extracted[new_key] = f.get_tensor(key).to(torch.float32)

# VoxCPM2 主LM 无独立 lm_head，用 embed_tokens 克隆一份满足 SDK
extracted["lm_head.weight"] = extracted["model.embed_tokens.weight"].clone()

print(f"提取 {len(extracted)} 个权重 (含 lm_head clone)")
save_file(extracted, os.path.join(OUT_DIR, "model.safetensors"))
print(f"保存到 {OUT_DIR}/model.safetensors")

# 复制 tokenizer 文件
VoxCPM2_DIR = "/home/tsm/work/models/VoxCPM2"
for fname in ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]:
    src = os.path.join(VoxCPM2_DIR, fname)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(OUT_DIR, fname))
        print(f"复制 {fname}")
