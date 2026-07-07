# VoxCPM2 DiT MDLA 部署进展

> 日期: 2026-07-03（初），2026-07-06（突破修正）
> 结论: **DiT 已成功 AOT 编译成 MDLA dla（233MB），端侧可行**，推翻旧"不可行"

## ⭐ 2026-07-06 突破：DiT 成功编译成 MDLA dla

旧结论（float tflite 留车机 NnApiDelegate 验证）走错了路径。正确路径（参考 SD `compile.text_encoder.fp.sh` + `inference/jni/` NeuronRT）：

`dit_quant8w16a_mha_extemb.tflite` (265MB, 8w16a, 659 ops) → `ncc-tflite --arch=mdla5.5,mvpu2.5 --relax-fp32 ...` → **`dit_quant8w16a_mha_extemb.dla` (233MB) ✓ Patch done!**（DRAM MDLA 221M / L1 1.2M）

5 个 patch（`convert_dit_patched.py`，cosine 0.99999994）：①RoPE slice ②SiLU→x/(1+e^-x) ③RMSNorm x*x ④**GQA unfold**（KV repeat 烘焙进 k_proj/v_proj 权重→真 MHA，绕 MTKEXT_TILE 5D rank 限制）⑤**timestep embedding 外部化**（t_emb 作输入，绕 MDLA 不支持的 SIN/COS/MUL）。

关键：**编译用 transformer profile（mdla5.5,mvpu2.5+relax-fp32），不是 unet 的纯 mdla5.5**；执行用 **NeuronRT（libneuron_runtime）加载 .dla，不是 NnApiDelegate/NNAPI**（旧 SIGSEGV 就是用了 NNAPI）。复现：`convert_dit_patched.py`→`convert_dit_ptq.py`→`compile_dit.sh`。详见 `docs/voxcpm2-mdla-deploy.md` 末尾"重大修正"节。

---

## 2026-07-03 初版（float tflite 转换突破，历史保留）



## 背景：两死局

DiT 是非自回归 diffusion transformer（12 层 MiniCPM 同构 + cond_proj + time_mlp + CFM Euler 10 步）。两条直接路径都失败：
- **mtk_onnx_converter**：opset 18 新 op 逐个不支持（Reshape allowzero → Split num_outputs → SDPA enable_gqa → ...），无底洞
- **mtk_llm_sdk**：整套流程假设 autoregressive LM（causal + KV cache + prefill/gen chunk），DiT 是 diffusion 单次前向，流程层不匹配

## 正解：mtk_converter.PyTorchConverter + TorchScript（参考 SD mlkits pt2tflite.py）

参照 `GAI-Deployment-Toolkit-v2.0.6_stable-diffusion-v2-1-mlkits-v0.1`：
```python
converter = mtk_converter.PyTorchConverter.from_script_module_file(dit.pt, INPUTS_SHAPE)
converter.quantize = False  # float
converter.convert_to_tflite(output_file='dit_float.tflite')
```
**不经 onnx importer**，绕开 opset/IR/allowzero 地狱。但 mtk 8.16 对 MiniCPM 两个 op 不支持，需等价 patch。

## 两个等价 patch（关键复用知识）

DiT 的 decoder = `MiniCPMModel`（和主LM 同构）。mtk 8.16 不支持其中两个 op，等价改写绕开（cosine 0.99999994，数值无损）：

### 1. RoPE: `cos_cached[position_ids]` → `cos_cached[:seq_len]`
- `aten::index` mtk 不支持
- `model.py:369` `position_ids = torch.arange(seq_len)` 连续，所以 `cos_cached[arange(N)] ≡ cos_cached[:N]`
- **真等价**（slice 代替 index）

### 2. Attention GQA: `SDPA(enable_gqa=True)` → `expand+reshape KV` + `SDPA(enable_gqa=False)`
- GQA 的 Q(16h)·K(2h) broadcast 让 mtk 的 matmul shape 推断失败
- `repeat_interleave` mtk 也不支持，改用 `expand+reshape`：
  ```python
  k = k.unsqueeze(2).expand(bsz, n_kv, rep, seq, hd).reshape(bsz, n_kv*rep, seq, hd)
  ```
- **真等价**（GQA 就是对 KV repeat 的语法糖）

⚠️ patch 必须在 `VoxCPM.from_pretrained` 之后做——class 级 monkey-patch 会影响 base_lm 的 warm up（其 KV cache 期望 2 kv_heads，repeat 后 16 heads 冲突）。

## 产出

- `dit_float.tflite` 848MB（212M params × float32，546 ops）
- 含 MTKEXT 自定义 op（mtk 优化的 SiLU 等），需 NeuroPilot runtime

## 验证状态

- ✅ patch(slice+noGQA) vs orig(index+GQA) cosine **0.99999994**（数值无损）
- ✅ convert 成功（546 operators 转出）
- ❌ PC 无法跑 dit_float.tflite：MTKEXT op 需 NeuroPilot delegate，且 `neuron_sdk/mt6991/bin/neuronrt` 是 ARM aarch64（PC x86 跑不了）
- → **tflite 数值/速度验证留车机端**（NnApiDelegate + mtk-mdla_shim，复用 face 流程）

## 流程命令

```bash
# voxcpm2 环境（python3.11，有 voxcpm）：patch + trace
CUDA_VISIBLE_DEVICES='' python convert_dit_patched.py   # → dit_scripted_v2.pt

# voxcpm2_ptq 环境（python3.10，有 mtk_converter）：PyTorchConverter 转 tflite
python convert_dit_api.py                                # → dit_float.tflite
```

## 下一步

1. **车机部署验证**：float tflite 上车机（NnApiDelegate mtk-mdla_shim + fp16），测单步 DiT 耗时 × 10 步 Euler × 2 CFG。若 <1s 可接受。
2. **若 float 太慢 → PTQ**：参考 SD mlkits `pt2tflite.py`，校准数据 hook DiT estimator 输入（latent+timestep+mu+cond），8w16a 量化。需先造校准数据（Task 3，跑 VoxCPM2.generate 采样）。
3. **质量验证**：DiT float/PTQ tflite + 主LM 量化 tflite + VAE/Encoder，完整 TTS pipeline 听音频。

## 不在范围
- Android 集成（Euler 10 步循环 + CFG，复用 FaceEngine.applyAccel）
- Encoder / VAE / Residual LM 转换
- PTQ 校准数据生成（Task 3，待 float 测速后决定）
