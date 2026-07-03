# VoxCPM2 端侧 MDLA 部署文档

> 设备: BYD Di300 (MediaTek mt6991, Android 14), APU = MDLA
> 目标: 把 VoxCPM2 TTS 从 PC GPU 迁到车端 APU
> 日期: 2026-07-03
> 进展: 主LM PTQ ✅ (6.1G→1G) | DiT float tflite ✅ | Encoder/VAE 待转

## 一、背景

### VoxCPM2 架构（4 组件，tokenizer-free diffusion autoregressive）

```
文本 → base_lm(主LM, 28层 MiniCPM) → hidden
                                        ↓ lm_to_dit_proj
                  residual_lm(8层) → hidden → res_to_dit_proj
                                        ↓ 拼接 mu(2048)
       随机噪声 z(64,4) → DiT(12层 MiniCPM + CFM Euler 10步去噪) → 预测特征
                                        ↓
                            AudioVAE → 48kHz 音频
```

- **主LM**（`base_lm`）: 自回归，token in，需 KV cache → 走 `mtk_llm_sdk`
- **DiT**（`feat_decoder.estimator`）: 非自回归 diffusion，hidden in，单次前向 → 走 `mtk_converter`（通用）
- 主LM/DiT 核心 decoder 都是 **MiniCPMModel**（同构 transformer），但用法/协议不同，工具链不同

### 工具链选择（关键决策）

| 组件 | 工具 | 原因 |
|---|---|---|
| 主LM | `mtk_llm_sdk` | 自回归 LLM，SDK 有完整 PTQ 流程（make_calib→ptq→fix_shape） |
| DiT | `mtk_converter.PyTorchConverter` | 非自回归 diffusion，LLM SDK 流程不匹配；通用 TorchScript→tflite |

## 推理流程与端侧集成关键发现（2026-07-03 读 `voxcpm2.py:_inference`）

### 推理是 autoregressive over audio patches（非一次前向）

每次循环产出 1 个 audio patch：
```
prefill: feat_encoder(初始feat) → feat_embed; base_lm.embed_tokens(text) → text_embed
         combined = text_embed + feat_embed; base_lm(combined) → lm_hidden; residual_lm → residual_hidden
for i in range(max_len):                      # 音频 patch 数（音频长度 × 6.25 Hz）
    dit_hidden = cat(lm_to_dit_proj(lm_hidden), res_to_dit_proj(residual_hidden))
    pred_feat = DiT(dit_hidden, noise, t, cond)   # CFM Euler 10 步
    curr_embed = feat_encoder(pred_feat)          # 编码生成 patch
    base_lm/residual_lm 前进一步（KV cache）用 curr_embed → 更新 lm_hidden, residual_hidden
最后: VAE.decode(所有 pred_feat) → 音频
```
**端侧算力** = max_len × (base_lm + residual_lm + DiT 10步 + feat_encoder)。10 秒音频 ≈ 62 patch。

### 必需组件清单

| 组件 | 角色 | 工具链 | 状态 |
|---|---|---|---|
| base_lm（主LM） | text→hidden，autoregressive | mtk_llm_sdk | ✅（但协议疑点，见下） |
| residual_lm | 残差 hidden，autoregressive，**no_rope**，无 embed/lm_head | mtk_llm_sdk? | ❌ 协议疑点 |
| feat_encoder | audio feat→embed，**每步调**，非自回归 transformer | mtk_converter+DiT patch | ✅ float 793MB（复用 DiT patch，cosine 1.0） |
| DiT | hidden+noise→latent，10步 Euler | mtk_converter | ✅ |
| VAE decoder | pred_feat→音频波形 | mtk_converter? | ❌ 大坑 |
| projections | lm_to_dit_proj / res_to_dit_proj / fusion_concat_proj / enc_to_lm_proj（Linear） | 简单 | ❌ 小 |

### ⚠️ base_lm tflite 协议疑点（端侧集成关键阻塞，待解决）

- mtk_llm_sdk 产出 **token-in** tflite（含 `embed_tokens` + `lm_head`，token→embed→layers→logits）
- VoxCPM2 实际 `base_lm(inputs_embeds=combined_embed)`：combined = `text_embed + feat_embed`（**hidden-in**，外部已 embed，跳过 embed_tokens）
- **不匹配**：tflite 的 token-in 和实际 hidden-in 用法矛盾
- 调研（2026-07-03）：mtk_llm_sdk 的 **mllm 路径**（CLIP/InternVL/LLaVA）支持 `image_embed concat text_embed → LLM layers`（即 hidden-in）。make_calib 有 `image_folder`/`extra_input_embeds`/`concat_image_text_embedding`/`DEFAULT_IMAGE_TOKEN`。VoxCPM2 的 combined_embed（text_embed+feat_embed）类比 image_embed，理论上 base_lm 能走 mllm 模式（feat_embed 当 image_embed）。但需 hack vision_config（指向 feat_encoder 或假配置）+ 校准数据含 feat_embed，复杂。**留端侧集成时解决，先转协议清晰的组件（feat_encoder/DiT）**。
- 当前主LM inference 验证（生成 token）**没覆盖**真实 hidden-in 用法

### residual_lm

73 keys（8 层 MiniCPM，hidden 2048，GQA 2 kv_heads，**no_rope**，无 embed_tokens/lm_head）。hidden-in autoregressive，同 base_lm 协议疑点。`no_rope` 省 RoPE patch。

### VAE decoder 大坑

`audiovae.pth`（312 keys）用 `weight_norm(Conv1d)` + `CausalConv1d`（自定义 padding）+ `Snake1d` 激活（`x+(α+ε)⁻¹·sin(αx)²`）+ 残差单元 + chunk 处理。和 face 标准 CNN（Conv2d+ReLU）完全不同，转换需 fuse weight norm + 处理 snake/causal/chunk，大调试。**可能需 onnxruntime-android 替代（不上 MDLA）**。

### clone vs 非 clone

- **clone**（Controllable/Ultimate Cloning）：输入含参考音频，feat_encoder 编码其 feat → 影响音色。车机固定音色通常用此（预存参考音频）。
- **非 clone**（Voice Design）：纯文本（可带音色描述），feat 空/占位。
- **feat_encoder 无论 clone 与否都必需**（每步编码生成 patch 反馈 base_lm，是 autoregressive over patches 的关键）。

---

## 二、环境准备

### 2.1 两个 conda 环境

```bash
# voxcpm2: 加载 VoxCPM2 模型、提取权重、TorchScript trace（python3.11 + GPU）
conda create -n voxcpm2 python=3.11
conda activate voxcpm2
pip install voxcpm  # HuggingFace VoxCPM2 推理库

# voxcpm2_ptq: mtk_converter PTQ（python3.10）
conda create -n voxcpm2_ptq python=3.10
conda activate voxcpm2_ptq
# 装 neuropilot-sdk-basic-8.0.11/offline_tool/ 里的 wheel
pip install mtk_converter-8.16.0_packages.zip  # 解压后按 cp310 装
pip install ./mtk/neuropilot-sdk-basic-8.0.11-build20260211/offline_tool/mtk_quantization-8.2.1-py3-none-any.whl
```

### 2.2 torchaudio stub（voxcpm2_ptq 必装，否则 transformers 导入崩）

voxcpm2_ptq conda 的 torch 是 2.12.1+cpu，但继承 user site 的 torchaudio 2.11.0（编译 vs torch 2.11+CUDA13，双重不匹配）。transformers 的 `loss_rnnt` 间接 import 触发崩溃。

**解决**：在 voxcpm2_ptq 的 site-packages 放 `sitecustomize.py`，启动时注入 stub：

```python
# /home/tsm/miniconda3/envs/voxcpm2_ptq/lib/python3.10/site-packages/sitecustomize.py
import sys, types
from importlib.machinery import ModuleSpec
if "torchaudio" not in sys.modules:
    _stub = types.ModuleType("torchaudio")
    _stub.__version__ = "2.11.0"
    _stub.__file__ = "<torchaudio-stub>"
    _stub.__spec__ = ModuleSpec("torchaudio", loader=None)  # find_spec 必需
    _stub.__path__ = []  # 标记为包
    sys.modules["torchaudio"] = _stub
```

PTQ 不用 torchaudio 任何功能，纯为绕过 `is_torchaudio_available()` 守卫。

---

## 三、主LM PTQ 详细步骤

工作目录：`tts-adapter/voxcpm2_ptq/`

### Step 1: 提取主LM 权重

**目的**：从 VoxCPM2 完整 `model.safetensors`（4.5GB，含全组件）提取主LM，转为 SDK MiniCPM 标准 key。

**命令**：
```bash
cd tts-adapter/voxcpm2_ptq
python extract_lm_weights.py
```

**原理**：
- SDK `MinicpmConfig` 期望 HF 标准 key：`model.embed_tokens.weight` / `model.layers.N.*` / `model.norm.weight`
- VoxCPM2 原始：`base_lm.embed_tokens.weight` / `base_lm.layers.N.*`
- 映射规则：`base_lm.<X>` → `model.<X>`
- **VoxCPM2 主LM 无独立 lm_head**（TTS LM 不预测 vocab token，hidden 直接送 DiT）→ 用 `embed_tokens` clone 一份满足 SDK 建模（PTQ 校准只需激活分布，lm_head 精度不影响）

**验证**：输出 `提取 255 个权重 (含 lm_head clone)`，保存到 `lm_model/model.safetensors`（float32, ~6GB）

### Step 2: 创建 SDK config

**目的**：扁平 minicpm config（不能 `llm` 嵌套）。

**命令**：config 已在 `lm_model/config.json`（由 `config_minicpm.json` 复制）。

**关键参数**（来自 VoxCPM2 `config.json` 的 `lm_config`，金标准）：
```json
{
    "model_type": "minicpm",
    "bos_token_id": 1, "eos_token_id": 2,        // <s>→1, </s>→2（和 MiniCPM 标准一致）
    "hidden_size": 2048, "intermediate_size": 6144,
    "num_attention_heads": 16, "num_key_value_heads": 2,  // GQA
    "num_hidden_layers": 28, "kv_channels": 128,
    "vocab_size": 73448, "rope_theta": 10000,
    "scale_emb": 12, "dim_model_base": 256, "scale_depth": 1.4,
    "tie_word_embeddings": false
}
```

**坑**：最初用 `{"model_type":"minicpm", "llm":{...}}` 嵌套 → `KeyError: vocab_size is required`。SDK 直接读 `config["vocab_size"]`，必须扁平。

**LongRoPE 暂不含**：VoxCPM2 用 `rope_scaling longrope`，但短句校准/推理（<64 token）无影响，先省。后续长序列再补。

### Step 3: 安装 mtk_quantization（解除 PTQ 硬阻塞）

**目的**：mtk_llm_sdk 的 PTQ 链（`ptq.py → rotate.py → qalft.py`）硬依赖 `mtk_quantization`（MTK 专有，不在 pypi/wheel/zip）。

**命令**（见 2.1）：`pip install mtk_quantization-8.2.1-py3-none-any.whl` 到 voxcpm2_ptq。

**验证**：`python -c "import mtk_quantization; print(mtk_quantization.__version__)"` → `8.2.1`

### Step 4: 造校准数据（PTQ 校准激活）

**目的**：PTQ hessian 优化需 representative 前向激活。

**坑**：SDK minicpm 走 **slow LlamaTokenizer**（需 sentencepiece `tokenizer.model`），VoxCPM2 只有 fast `tokenizer.json` → `get_spm_processor` 崩。

**解决**：用 tokens 字符串输入绕过 tokenizer 加载（外部用 `transformers.LlamaTokenizerFast` 预 tokenize，VoxCPM2 tokenizer 底层就是它）。

```python
# gen_calib_tokens.py（用 fast tokenizer 把中文短句 tokenize 成 tokens 字符串）
from transformers import LlamaTokenizerFast
tok = LlamaTokenizerFast.from_pretrained("lm_model")
texts = ["你好，今天天气怎么样？", "帮我导航到最近的加油站。", ...]  # 16 条车机场景
for t in texts:
    prompt = f"<|im_start|>user\n{t}<|im_end|>\n<|im_start|>assistant\n"  # ChatML
    ids = tok.encode(prompt)
    f.write(json.dumps({"tokens": " ".join(map(str, ids))}) + "\n")  # 空格分隔字符串
```

**关键**：`{"tokens": "1 233 456 ..."}`（空格分隔字符串，**不是 list**）。SDK `sanity_checks` 要求字段是 `text` 或 `tokens`，tokens 必须是字符串（`"Tokens should either be space or comma separated"`）。

**生成校准数据集**（voxcpm2_ptq）：
```bash
mtk_make_llm_ptq_calib_dataset converter \
    lm_model/config.json \
    calib_tokens.jsonl \
    -b 16 -m 64
# → calibration_datasets/lm_model/（29 个 chunk，每层激活）
```

**验证**：`Saving calibration data ...` + 5 分钟跑完。

### Step 5: PTQ 量化

**命令**（voxcpm2_ptq）：
```bash
mtk_ptq_llm converter \
    lm_model/config.json \
    -d /home/tsm/work/android_agent/calibration_datasets/lm_model \
    -p sym4W_sym16A \
    -w hessian \
    --pad_lm_head
```

**参数**：
- `-p sym4W_sym16A`：4bit 对称权重 + 16bit 对称激活（参考 GAI-Toolkit `1b_2_ptq_4w16a.sh`）
- `-w hessian`：Hessian 权重优化（最慢但质量最好，~24 分钟）
- `--pad_lm_head`：pad lm_head 到硬件友好 size

**产出**：`tflite/lm_model_sym4W_sym16A_Overall_hessian/`（28 个 tflite chunk + 287MB embedding_int16.bin，~1GB）

**验证**：`PTQ-ed layer 28` + exit 0。

### Step 6: 固定 shape + 推理验证

**fix_shape**（固定 prefill/decode shape）：
```bash
mtk_fix_llm_shape tflite/lm_model_sym4W_sym16A_Overall_hessian 128t1024c 1t1024c -n 1
# → _128t1024c (prefill 729MB) + _1t1024c (decode)
```

**inference 验证**（用 tokens 输入，绕过 tokenizer）：
```bash
mtk_inference_llm_tflite lm_model/config.json \
    tflite/lm_model_sym4W_sym16A_Overall_hessian_128t1024c \
    inference_tokens.jsonl -m 32 --save
```

**结果**：模型加载 + prefill + autoregressive decode 生成 token，全链路 PASS。

⚠️ **生成 token 重复是预期**：VoxCPM2 是 tokenizer-free diffusion autoregressive，主LM **不经 lm_head 生成 vocab token**（输出 hidden 直接送 DiT）。lm_head 是 embed clone，token 生成无语义。**PTQ 校准激活来自 layers forward（不涉 lm_head），量化有效**。真质量验证需完整 pipeline。

---

## 四、DiT 转换详细步骤

工作目录：`tts-adapter/voxcpm2_ptq/dit/`

### Step 1: 提取 DiT 为独立 module

**目的**：从 VoxCPM2 取 `feat_decoder.estimator`（VoxCPMLocDiT，12 层 MiniCPM + cond_proj + time_mlp）。

**命令**（voxcpm2 环境）：
```bash
cd tts-adapter/voxcpm2_ptq/dit
CUDA_VISIBLE_DEVICES='' python extract_dit.py
```

**DiT forward 协议**（`local_dit_v2.py`）：
```
forward(x, mu, t, cond, dt) → velocity
  x: (N,64,4) 噪声 | mu: (N,2048) 主LM+residual hidden
  t: (N,) timestep | cond: (N,64,4) 前一 patch | dt: (N,) delta
内部: in_proj/cond_proj(64→1024) + time_mlp + 拼接 (N,11,1024) → 12层 → out_proj → (N,64,4)
```

**坑**：
- GPU OOM（voxcpm2 环境 GPU 被占）→ `CUDA_VISIBLE_DEVICES=''` 强制 CPU
- 权重 bfloat16 vs 输入 float32 dtype 错 → `dit.cpu().float()` 转 float32

**验证**：输出 shape (2,64,4) ✓，212M params，保存 `dit_model.pt`（848MB float32）。

### Step 2: 等价 patch（绕开 mtk 不支持的 op）

**两死局**（直接路径都失败，详见附录）：
- `mtk_onnx_converter`：opset 18 新 op 逐个不支持（无底洞）
- `mtk_llm_sdk`：假设 autoregressive（causal+KV cache+双 chunk），DiT 是 diffusion

**正解**：`mtk_converter.PyTorchConverter.from_script_module_file`（TorchScript 直接转，不经 onnx）。但 mtk 8.16 对 MiniCPM 两个 op 不支持，需等价 patch（`convert_dit_patched.py`）：

#### Patch 1: RoPE slice（绕开 aten::index）

**问题**：`MiniCPMLongRoPE.forward` 用 `cos_cached[position_ids]`（aten::index，mtk 不支持）。

**等价改写**（`model.py:369` `position_ids = torch.arange(seq_len)` 连续）：
```python
# 原: cos = self.cos_cached[position_ids]
# 改: cos = self.cos_cached[:seq_len]  （slice，mtk 支持）
# 等价因 position_ids=arange(N)，cos_cached[arange(N)] ≡ cos_cached[:N]
def _rope_forward_slice(self, position_ids):
    seq_len = position_ids.shape[-1]
    return self.cos_cached[:seq_len], self.sin_cached[:seq_len]
```

#### Patch 2: Attention expand+reshape（绕开 GQA broadcast）

**问题**：`SDPA(enable_gqa=True)` 让 Q(16 heads)·K(2 kv_heads) broadcast，mtk 的 matmul shape 推断崩。`repeat_interleave` 也不支持。

**等价改写**（手动 repeat KV，用 expand+reshape）：
```python
rep = self.num_heads // self.num_key_value_heads  # 16/2 = 8
n_kv = self.num_key_value_heads
# (bsz, n_kv, seq, hd) → unsqueeze → expand → reshape == repeat_interleave
k = k.unsqueeze(2).expand(bsz, n_kv, rep, q_len, self.head_dim).reshape(bsz, n_kv*rep, q_len, self.head_dim)
v = v.unsqueeze(2).expand(bsz, n_kv, rep, q_len, self.head_dim).reshape(bsz, n_kv*rep, q_len, self.head_dim)
attn = SDPA(q, k, v, is_causal=is_causal, enable_gqa=False)
```

**等价性验证**：patch vs orig cosine **0.99999994**（数值无损）。

⚠️ **patch 必须在 `VoxCPM.from_pretrained` 之后做**——class 级 monkey-patch 会影响 base_lm 的 warm up（其 KV cache 期望 2 kv_heads，patch repeat 后 16 heads 冲突）。

### Step 3: TorchScript trace

**命令**（voxcpm2，patch 后）：
```bash
CUDA_VISIBLE_DEVICES='' python convert_dit_patched.py
# 加载 → patch → 验证等价 → torch.jit.trace → dit_scripted_v2.pt
```

**原理**：trace 记录固定 shape 的 forward op 序列。DiT forward 无控制流（纯 tensor op），trace 友好。

**验证**：trace cosine 1.0，保存 `dit_scripted_v2.pt`（882MB）。

### Step 4: PyTorchConverter 转 tflite

**命令**（voxcpm2_ptq）：
```bash
python convert_dit_api.py
```

**核心 API**（参考 SD mlkits `pt2tflite.py`）：
```python
converter = mtk_converter.PyTorchConverter.from_script_module_file(
    "dit_scripted_v2.pt",
    [(2,64,4), (2,2048), (2,), (2,64,4), (2,)]  # 输入 shape: x,mu,t,cond,dt
)
converter.quantize = False  # float（PTQ 设 True + calibration_data_gen）
converter.convert_to_tflite(output_file="dit_float.tflite")
```

**产出**：`dit_float.tflite` 848MB（546 operators，含 MTKEXT 自定义 op）

**PTQ 模式**（若 float 太慢，参考 SD `pt2tflite.py`）：
```python
converter.quantize = True
converter.calibration_data_gen = data_gen_dit  # generator yield [x, mu, t, cond, dt]
converter.calibration_method = 'Histogram'
converter.precision_proportion = {'sym8W_sym16A': 1.0}  # 8w16a（diffusion 友好）
converter.prepend_input_quantize_ops = True
converter.append_output_dequantize_ops = True
```

### Step 5: 验证

- ✅ patch vs orig cosine 0.99999994
- ✅ convert 成功（546 ops）
- ❌ PC 无法跑 tflite：含 MTKEXT op（mtk 优化的 SiLU 等），需 NeuroPilot delegate；`neuron_sdk/mt6991/neuronrt` 是 ARM aarch64（PC x86 跑不了）
- → **tflite 数值/速度留车机端验证**（NnApiDelegate + mtk-mdla_shim，复用 `FaceEngine.applyAccel` 模式）

---

## 四点五、feat_encoder 转换（复用 DiT patch，2026-07-03）

`VoxCPMLocEnc`（feat_encoder）：audio feat (B,T,P,D) → embed (B,T,hidden)。`in_proj` + `special_token`（CLS-like）+ MiniCPM encoder（**is_causal=False**）。和 DiT decoder 同构（MiniCPM），**DiT 的 RoPE slice + GQA expand patch 直接复用，无新 patch**——验证了 patch 方案对同构 transformer 通用。

**转换**（`convert_feat_enc.py` patch+trace + `convert_feat_enc_api.py` convert）：T=1（每步编码单 patch，最常用），输入 (1,1,4,64)。

**验证**：patch vs orig cosine **1.00000012**（等价）。产出 `feat_encoder.tflite` 793MB（521 ops）。

⚠️ **T 可变**：每步 T=1（编码单 patch），prefill（clone 模式编码参考音频）T=T_init。当前转 T=1 版；prefill 需另转 T=T_init 版或循环 T=1。

---

## 五、关键坑与 workaround 总览

### 主LM（mtk_llm_sdk 路径）

| # | 坑 | 现象 | 解决 |
|---|---|---|---|
| 1 | config 嵌套 | `KeyError: vocab_size` | 扁平化（顶层，非 `llm.` 下） |
| 2 | SDK slow tokenizer 无 SP | `get_spm_processor` 崩 | tokens 字符串输入绕过（外部 fast tokenize） |
| 3 | torchaudio CUDA13 不匹配 | `libcudart.so.13` / `_torchaudio.abi3.so` | sitecustomize 注入 stub |
| 4 | 权重 key + 无 lm_head | `KeyError: model.embed_tokens.weight` | `base_lm.→model.` + embed clone lm_head |

### DiT（mtk_converter 路径）

| # | 坑 | 现象 | 解决 |
|---|---|---|---|
| 5 | onnx opset 18 地狱 | Reshape allowzero / Split num_outputs / SDPA GQA 逐个崩 | 放弃 onnx，走 PyTorchConverter+TorchScript |
| 6 | mtk_llm_sdk 流程不匹配 | autoregressive 假设（causal+KV cache+双chunk） | 改用通用 mtk_converter |
| 7 | aten::index | RoPE `cos_cached[position_ids]` | slice 等价（position 连续） |
| 8 | GQA matmul broadcast | SDPA enable_gqa shape 推断崩 | expand+reshape KV + no gqa |
| 9 | aten::repeat_interleave | mtk 不支持 | 用 expand+reshape 替代 |

### 通用
- **face 模型能走 mtk_onnx_converter 是因为 CNN（op 简单）**；transformer（attention/RoPE）老版 mtk 8.16 支持差，必须 PyTorchConverter + patch
- **PC 验证不了 mtk tflite**（MTKEXT op + ARM runtime）→ PC 验证 pytorch/onnx，tflite 留车机

---

## 六、参考

- 主LM 成果：`tts-adapter/voxcpm2_ptq/PTQ_RESULT.md`
- DiT 成果：`tts-adapter/voxcpm2_ptq/dit/DIT_RESULT.md`
- SD diffusion 流程模板：`mtk/GAI-Deployment-Toolkit-v2.0.6_stable-diffusion-v2-1-mlkits-v0.1/`
- face 端侧部署（NnApiDelegate/MDLA 模式）：`docs/face-model-deployment.md`
- MiniCPM PTQ 模板：`mtk/GAI-Deployment-Toolkit-v2.0.6_minicpm-1b-2b-v0.1/post_training_quantize/`
- mtk_quantization wheel：`mtk/neuropilot-sdk-basic-8.0.11-build20260211/offline_tool/`

## 七、下一步

1. **DiT float 车机测速**：NnApiDelegate(mtk-mdla_shim, fp16) 跑单步 DiT，估算 10步 Euler × 2 CFG 总耗时
2. **主LM PC 替换验证**（路径 B）：nanovllm 把主LM 换量化版，跑完整 TTS 听音频，判量化损伤
3. **DiT PTQ**（若 float 慢）：造校准数据（hook estimator 输入）+ 8w16a
4. **Encoder/VAE 转换**：复用 PyTorchConverter + patch 经验
5. **Android 集成**：Euler 循环 + CFG + NnApiDelegate（复用 FaceEngine.applyAccel）
