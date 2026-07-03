#!/usr/bin/env python3
"""转 feat_encoder（VoxCPMLocEnc）TorchScript，复用 DiT 的 RoPE/GQA patch。

feat_encoder: audio feat (B,T,P,D) → embed (B,T,hidden)，每步调（T=1 编码单 patch）。
非自回归单次前向（MiniCPM encoder, is_causal=False）。和 DiT decoder 同构，patch 直接复用。
"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
from voxcpm import VoxCPM
from voxcpm.modules.minicpm4.model import (
    MiniCPMLongRoPE, MiniCPMAttention, apply_rotary_pos_emb,
)

MODEL_PATH = "/home/tsm/work/models/VoxCPM2"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit"

_orig_rope = MiniCPMLongRoPE.forward
_orig_attn = MiniCPMAttention.forward


def _rope_slice(self, position_ids):
    seq_len = position_ids.shape[-1]
    return self.cos_cached[:seq_len], self.sin_cached[:seq_len]


def _attn_no_gqa(self, hidden_states, position_emb, is_causal):
    bsz, q_len, _ = hidden_states.size()
    q = self.q_proj(hidden_states).view(bsz, q_len, self.num_heads, self.head_dim).transpose(1, 2)
    k = self.k_proj(hidden_states).view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)
    v = self.v_proj(hidden_states).view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)
    if position_emb is not None:
        cos, sin = position_emb
        q, k = apply_rotary_pos_emb(q, k, cos, sin)
    rep = self.num_heads // self.num_key_value_heads
    n_kv = self.num_key_value_heads
    k = k.unsqueeze(2).expand(bsz, n_kv, rep, q_len, self.head_dim).reshape(bsz, n_kv * rep, q_len, self.head_dim)
    v = v.unsqueeze(2).expand(bsz, n_kv, rep, q_len, self.head_dim).reshape(bsz, n_kv * rep, q_len, self.head_dim)
    q, k, v = q.contiguous(), k.contiguous(), v.contiguous()
    attn = torch.nn.functional.scaled_dot_product_attention(q, k, v, is_causal=is_causal, enable_gqa=False)
    attn = attn.transpose(1, 2).contiguous().reshape(bsz, q_len, self.num_heads * self.head_dim)
    return self.o_proj(attn), (k, v)


def main():
    print("加载 VoxCPM2 (CPU)...")
    model = VoxCPM.from_pretrained(MODEL_PATH, load_denoiser=False)
    enc = model.tts_model.feat_encoder
    enc.eval().cpu().float()

    MiniCPMLongRoPE.forward = _rope_slice
    MiniCPMAttention.forward = _attn_no_gqa

    # T=1（每步编码单 patch，最常用）；P=4, D=64
    torch.manual_seed(42)
    dummy = torch.randn(1, 1, 4, 64)

    # 验证 patch 等价
    with torch.no_grad():
        out_patched = enc(dummy)
    MiniCPMLongRoPE.forward = _orig_rope
    MiniCPMAttention.forward = _orig_attn
    with torch.no_grad():
        out_orig = enc(dummy)
    cos = torch.dot(out_patched.flatten(), out_orig.flatten()) / (out_patched.norm() * out_orig.norm())
    print(f"feat_encoder patch vs orig cosine: {cos:.8f}, out shape {tuple(out_patched.shape)}")
    assert cos > 0.9999

    MiniCPMLongRoPE.forward = _rope_slice
    MiniCPMAttention.forward = _attn_no_gqa
    scripted = torch.jit.trace(enc, dummy, check_trace=False)
    pt = os.path.join(OUT_DIR, "feat_encoder.pt")
    scripted.save(pt)
    print(f"trace -> {pt} ({os.path.getsize(pt)/1e6:.0f}MB)")


if __name__ == "__main__":
    main()
