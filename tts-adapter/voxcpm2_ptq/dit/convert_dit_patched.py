#!/usr/bin/env python3
"""patch RoPE + attention 后 trace DiT（绕开 mtk 不支持的 op）。

两处等价改写（数值不变）：
1. RoPE: cos_cached[position_ids] → cos_cached[:seq_len]
   （position_ids=arange(seq_len) 连续，slice == index）
2. Attention: SDPA(enable_gqa=True) → repeat_interleave KV + SDPA(enable_gqa=False)
   （GQA 就是对 KV repeat 的语法糖，手动 repeat 等价）
绕开 aten::index + GQA matmul broadcast，让 mtk PyTorchConverter 能转。
"""
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
from voxcpm import VoxCPM
from voxcpm.modules.minicpm4.model import (
    MiniCPMLongRoPE, MiniCPMAttention, MiniCPMRMSNorm, apply_rotary_pos_emb,
)

MODEL_PATH = "/home/tsm/work/models/VoxCPM2"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/dit"

_orig_rope_forward = MiniCPMLongRoPE.forward
_orig_attn_forward = MiniCPMAttention.forward
_orig_silu_forward = torch.nn.SiLU.forward
_orig_rmsnorm_forward = MiniCPMRMSNorm.forward


def _rmsnorm_forward(self, hidden_states):
    # 手动 RMSNorm（x*x 替代 pow(2)，避免 mtk_converter 识别为 MTKEXT_RMS_NORMALIZATION）
    old = hidden_states.dtype
    h32 = hidden_states.to(torch.float32)
    variance = (h32 * h32).mean(dim=-1, keepdim=True)
    return (hidden_states * torch.rsqrt(variance + self.variance_epsilon)).to(old) * self.weight


def _silu_sigmoid_mul(self, x):
    # SiLU(x) = x/(1+e^-x)，用 exp+div 写避免 mtk_converter 识别 sigmoid+mul 模式
    # 融合成 MTKEXT_SILU（车机 NNAPI delegate 不认 custom op）
    return x / (1.0 + torch.exp(-x))


def _rope_forward_slice(self, position_ids):
    seq_len = position_ids.shape[-1]
    return self.cos_cached[:seq_len], self.sin_cached[:seq_len]


def _attn_forward_no_gqa(self, hidden_states, position_emb, is_causal):
    bsz, q_len, _ = hidden_states.size()
    q = self.q_proj(hidden_states).view(bsz, q_len, self.num_heads, self.head_dim).transpose(1, 2)
    k = self.k_proj(hidden_states).view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)
    v = self.v_proj(hidden_states).view(bsz, q_len, self.num_key_value_heads, self.head_dim).transpose(1, 2)
    if position_emb is not None:
        cos, sin = position_emb
        q, k = apply_rotary_pos_emb(q, k, cos, sin)
    rep = self.num_heads // self.num_key_value_heads
    n_kv = self.num_key_value_heads
    # repeat KV via expand+reshape（mtk 不支持 repeat_interleave）
    # (bsz,n_kv,seq,hd) → unsqueeze(2) → expand → reshape == repeat_interleave
    k = k.unsqueeze(2).expand(bsz, n_kv, rep, q_len, self.head_dim).reshape(bsz, n_kv * rep, q_len, self.head_dim)
    v = v.unsqueeze(2).expand(bsz, n_kv, rep, q_len, self.head_dim).reshape(bsz, n_kv * rep, q_len, self.head_dim)
    q, k, v = q.contiguous(), k.contiguous(), v.contiguous()
    attn = torch.nn.functional.scaled_dot_product_attention(
        q, k, v, is_causal=is_causal, enable_gqa=False)
    attn = attn.transpose(1, 2).contiguous().reshape(bsz, q_len, self.num_heads * self.head_dim)
    return self.o_proj(attn), (k, v)


def main():
    print("加载 VoxCPM2 (CPU)...")
    model = VoxCPM.from_pretrained(MODEL_PATH, load_denoiser=False)
    dit = model.tts_model.feat_decoder.estimator
    dit.eval().cpu().float()
    # 加载（warm up）后再 patch —— class 级 monkey-patch 会影响 base_lm，
    # 必须等 from_pretrained 的 warm up 跑完（其 KV cache 期望 2 kv_heads）
    MiniCPMLongRoPE.forward = _rope_forward_slice
    MiniCPMAttention.forward = _attn_forward_no_gqa
    torch.nn.SiLU.forward = _silu_sigmoid_mul
    MiniCPMRMSNorm.forward = _rmsnorm_forward

    torch.manual_seed(42)
    dummy = (torch.randn(2, 64, 4), torch.randn(2, 2048), torch.rand(2),
             torch.randn(2, 64, 4), torch.zeros(2))

    # 验证 patch 等价
    with torch.no_grad():
        out_patched = dit(*dummy)
    MiniCPMLongRoPE.forward = _orig_rope_forward
    MiniCPMAttention.forward = _orig_attn_forward
    torch.nn.SiLU.forward = _orig_silu_forward
    MiniCPMRMSNorm.forward = _orig_rmsnorm_forward
    with torch.no_grad():
        out_orig = dit(*dummy)
    cos = torch.dot(out_patched.flatten(), out_orig.flatten()) / (out_patched.norm() * out_orig.norm())
    print(f"patch(slice+noGQA+silu+rmsnorm) vs orig cosine: {cos:.8f}")
    assert cos > 0.9999, f"patch 不等价: {cos}"

    # 重新 patch + trace
    MiniCPMLongRoPE.forward = _rope_forward_slice
    MiniCPMAttention.forward = _attn_forward_no_gqa
    torch.nn.SiLU.forward = _silu_sigmoid_mul
    MiniCPMRMSNorm.forward = _rmsnorm_forward
    scripted = torch.jit.trace(dit, dummy, check_trace=False)
    pt_path = os.path.join(OUT_DIR, "dit_scripted_v2.pt")
    scripted.save(pt_path)
    print(f"trace -> {pt_path} ({os.path.getsize(pt_path)/1e6:.0f}MB)")
    print("✓ patch + trace 完成（RoPE slice + attention no-GQA）")


if __name__ == "__main__":
    main()
