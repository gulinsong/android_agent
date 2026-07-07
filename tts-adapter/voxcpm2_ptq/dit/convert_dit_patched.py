#!/usr/bin/env python3
"""patch RoPE + SiLU + RMSNorm + GQA-unfold + 外部化 timestep embedding 后 trace DiT。

五处等价改写（数值不变或近无损），逐个绕开 mtk/MDLA 不支持的 op：
1. RoPE: cos_cached[position_ids] → cos_cached[:seq_len]
   （绕开 aten::index）
2. SiLU: x*sigmoid(x) → x/(1+e^-x) 用 exp+div 写
   （绕开 mtk_converter 识别为 MTKEXT_SILU custom op）
3. RMSNorm: pow(x,2) → x*x
   （绕开 mtk_converter 识别为 MTKEXT_RMS_NORMALIZATION custom op）
4. Attention GQA: SDPA(enable_gqa=True) → 把 KV repeat 烘焙进 k_proj/v_proj 权重 + 标准 MHA
   （绕开 5D expand → MTKEXT_TILE "rank should be in [0,4]"；烘焙后全程 4D，零 Tile op）
5. Timestep embedding 外部化: SinusoidalPosEmb(t) 移出模型，t_emb 作为输入喂入
   （绕开 MDLA 不支持的 SIN/COS + 广播 MUL；参考 SD：pt2tflite.py 喂 t_emb 而非 raw t）
   time_mlp(Linear+SiLU+Linear) 留图内（FC 已支持，SiLU patch 2 已处理）。

每步都对应 SD 官方例子已验证的模式（PTQ recipe / mvpu2.5+relax-fp32 profile / 外部 t_emb）。
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


def _attn_forward_mha(self, hidden_states, position_emb, is_causal):
    """标准 MHA forward（GQA 已烘焙进 k_proj/v_proj 权重，self.num_key_value_heads 已改=num_heads）。
    无 expand/repeat，全程 4D，不产生 MTKEXT_TILE。"""
    bsz, q_len, _ = hidden_states.size()
    q = self.q_proj(hidden_states).view(bsz, q_len, self.num_heads, self.head_dim).transpose(1, 2)
    k = self.k_proj(hidden_states).view(bsz, q_len, self.num_heads, self.head_dim).transpose(1, 2)
    v = self.v_proj(hidden_states).view(bsz, q_len, self.num_heads, self.head_dim).transpose(1, 2)
    if position_emb is not None:
        cos, sin = position_emb
        q, k = apply_rotary_pos_emb(q, k, cos, sin)
    q, k, v = q.contiguous(), k.contiguous(), v.contiguous()
    attn = torch.nn.functional.scaled_dot_product_attention(
        q, k, v, is_causal=is_causal, enable_gqa=False)
    attn = attn.transpose(1, 2).contiguous().reshape(bsz, q_len, self.num_heads * self.head_dim)
    return self.o_proj(attn), (k, v)


def unfold_gqa(module):
    """递归遍历所有 MiniCPMAttention，把 KV repeat 烘焙进 k_proj/v_proj 权重 → 真 MHA。
    仅在加载时做一次（repeat_interleave 作用在权重 tensor 上，不进 trace 图）。
    等价：new_head h 的权重 = old kv_head (h//rep) 的权重。"""
    rep = module.num_heads // module.num_key_value_heads
    n_kv = module.num_key_value_heads
    hd = module.head_dim
    hidden = module.hidden_size
    with torch.no_grad():
        for proj in (module.k_proj, module.v_proj):
            old_w = proj.weight.data  # (n_kv*hd, hidden)
            old_w = old_w.view(n_kv, hd, hidden)            # (n_kv, hd, hidden)
            new_w = old_w.repeat_interleave(rep, dim=0)      # (n_kv*rep=num_heads, hd, hidden)
            new_w = new_w.reshape(module.num_heads * hd, hidden)  # (num_heads*hd, hidden)
            proj.weight = torch.nn.Parameter(new_w.contiguous())
            # 扩 out_features，让 view(num_heads) 成立
            proj.out_features = module.num_heads * hd
    module.num_key_value_heads = module.num_heads  # 视图层也统一，forward 直接 view num_heads


class DiTExternalTimeEmb(torch.nn.Module):
    """DiT wrapper：SinusoidalPosEmb 外部化，t_emb/dt_emb 作为输入。
    等价于原 VoxCPMLocDiT.forward，仅把 self.time_embeddings(t) 这步移到图外。
    runtime 时 CPU 预算 t_emb = cat(sin(scale*t*freqs), cos(scale*t*freqs)) 喂入。"""

    def __init__(self, dit):
        super().__init__()
        self.dit = dit  # 含 in_proj/cond_proj/out_proj/time_mlp/delta_time_mlp/decoder

    def forward(self, x, mu, t_emb, cond, dt_emb):
        dit = self.dit
        x = dit.in_proj(x.transpose(1, 2).contiguous())
        cond = dit.cond_proj(cond.transpose(1, 2).contiguous())
        prefix = cond.size(1)
        # 跳过 time_embeddings（已外部化），直接 time_mlp
        t = dit.time_mlp(t_emb.to(x.dtype))
        dt = dit.delta_time_mlp(dt_emb.to(x.dtype))
        t = t + dt
        mu = mu.view(x.size(0), -1, x.size(-1))
        x = torch.cat([mu, t.unsqueeze(1), cond, x], dim=1)
        hidden, _ = dit.decoder(x, is_causal=False)
        hidden = hidden[:, prefix + mu.size(1) + 1:, :]
        hidden = dit.out_proj(hidden)
        return hidden.transpose(1, 2).contiguous()


def main():
    import json
    print("加载 VoxCPM2 (CPU)...")
    model = VoxCPM.from_pretrained(MODEL_PATH, load_denoiser=False)
    dit = model.tts_model.feat_decoder.estimator
    dit.eval().cpu().float()

    torch.manual_seed(42)
    x = torch.randn(2, 64, 4)
    mu = torch.randn(2, 2048)
    t = torch.rand(2)
    cond = torch.randn(2, 64, 4)
    dt = torch.zeros(2)
    dummy_raw = (x, mu, t, cond, dt)  # 原始接口：raw t/dt

    # 1. 先跑原始 DiT 拿参考输出（全原版）
    with torch.no_grad():
        out_orig = dit(*dummy_raw)

    # 2. patch（warm up 后）+ unfold GQA
    MiniCPMLongRoPE.forward = _rope_forward_slice
    MiniCPMAttention.forward = _attn_forward_mha
    torch.nn.SiLU.forward = _silu_sigmoid_mul
    MiniCPMRMSNorm.forward = _rmsnorm_forward

    n_attn = 0
    for m in dit.modules():
        if isinstance(m, MiniCPMAttention):
            unfold_gqa(m)
            n_attn += 1
    print(f"unfold GQA → {n_attn} 个 attention 改为 MHA（权重烘焙）")

    # 3. 外部化 timestep embedding：CPU 预算 t_emb/dt_emb（用 dit 原 SinusoidalPosEmb）
    with torch.no_grad():
        t_emb = dit.time_embeddings(t).detach()    # (2, hidden_size)
        dt_emb = dit.time_embeddings(dt).detach()  # (2, hidden_size)
    print(f"外部化 timestep embedding → t_emb {tuple(t_emb.shape)}, dt_emb {tuple(dt_emb.shape)}")

    # 4. wrap（跳过 time_embeddings）并验证等价
    wrapper = DiTExternalTimeEmb(dit).eval()
    with torch.no_grad():
        out_wrap = wrapper(x, mu, t_emb, cond, dt_emb)
    cos = torch.dot(out_wrap.flatten(), out_orig.flatten()) / (out_wrap.norm() * out_orig.norm())
    print(f"wrapper(外部t_emb+mha+silu+rmsnorm+unfold) vs orig cosine: {cos:.8f}")
    assert cos > 0.9999, f"wrapper 不等价: {cos}"

    # 5. trace wrapper（输入: x, mu, t_emb, cond, dt_emb）
    wrapper_dummy = (x, mu, t_emb, cond, dt_emb)
    scripted = torch.jit.trace(wrapper, wrapper_dummy, check_trace=False)
    pt_path = os.path.join(OUT_DIR, "dit_scripted_v4.pt")
    scripted.save(pt_path)
    print(f"trace -> {pt_path} ({os.path.getsize(pt_path)/1e6:.0f}MB)")

    # 6. 导出输入 shape 给 PTQ 脚本
    shapes = {"inputs": [list(t_.shape) for t_ in wrapper_dummy]}
    with open(os.path.join(OUT_DIR, "dit_v4_input_shapes.json"), "w") as f:
        json.dump(shapes, f)
    print(f"输入 shape → dit_v4_input_shapes.json: {shapes['inputs']}")
    print("✓ 5 patch + trace 完成（RoPE slice / SiLU / RMSNorm / GQA 烘焙 / timestep 外部化）")


if __name__ == "__main__":
    main()
