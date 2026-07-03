# VoxCPM2 主LM MDLA PTQ 技术验证设计

> 日期: 2026-07-01
> 目标: 用 mtk_llm_sdk converter 把 VoxCPM2 的主 LM（Cpm4 架构）量化为 MDLA 模型，PC 端验证质量和速度

## 一、背景

**当前 TTS**：VoxCPM2 跑在 PC GPU（nanovllm_voxcpm / vllm），app HTTP 调。目标移到车端 APU（mt6991 MDLA）。

**VoxCPM2 架构**（4 个 Transformer 组件，全 GQA + RoPE + RMSNorm + SwiGLU）：
- 主 LM（28层 Cpm4，自回归，需 KV Cache）
- Encoder（12层，文本编码）
- DiT 去噪（12层，非自回归 CFM Euler 10步）
- Residual LM（8层）+ VAE（卷积）

**本 spec 范围**：只做主 LM 的 SDK porting + PTQ。其他组件后续。

**为什么先主 LM**：
- 最大不确定性（Cpm4 不是 SDK 标准 LLM，SDK 认不认？）
- 主 LM 是 autoregressive + KV Cache，最复杂
- 验证 SDK 能量化 Cpm4 → 后续 DiT/Encoder 同构直接跟

## 二、SDK Porting 方案

### 2.1 Cpm4 架构分析

VoxCPM2 的主 LM = **MiniCPM-4**（Cpm4），结构和 Qwen-2 同构：

| 组件 | Cpm4 | Qwen-2 | 是否同构 |
|------|------|--------|---------|
| Attention | Cpm4Attention (GQA, 2 kv_heads) | Qwen2Attention (GQA) | ✅ |
| MLP | Cpm4MLP (SiluAndMul=SwiGLU) | Qwen2MLP (SiLU) | ✅ |
| Norm | RMSNorm | RMSNorm | ✅ |
| Position | RoPE (LongRoPE) | RoPE | ✅ (LongRoPE 是扩展) |
| Decoder | Cpm4DecoderLayer (residual connection) | Qwen2DecoderLayer | ✅ |

**核心结论**：Cpm4 = Qwen-2 变体（LongRoPE + μP scaling）。SDK 支持 Qwen-2 → Cpm4 porting 主要是**权重名映射 + config 适配**。

### 2.2 Porting 步骤

**Step 1: 提取主 LM 权重**
- 从 `model.safetensors`（4.5GB，含全组件）提取主 LM 的权重 key（前缀如 `lm.layers.*` / `lm.embed.*`）
- 单独存为 `lm_model.safetensors`

**Step 2: 写 SDK config**
- 创建 `config_cpm4.json`（SDK 格式）：
  ```json
  {
    "model_type": "cpm4",
    "hidden_size": 2048,
    "intermediate_size": 6144,
    "num_attention_heads": 16,
    "num_key_value_heads": 2,
    "num_hidden_layers": 28,
    "rms_norm_eps": 1e-05,
    "rope_theta": 10000,
    "vocab_size": 73448,
    "bos_token_id": 1,
    "eos_token_id": 2
  }
  ```

**Step 3: 写 `configuration_cpm4.py`**
- 继承 `BaseLLMConfig`
- 定义 `fc_names`（SDK 权重名映射）：
  ```python
  self.fc_names = {
      'attn': {'name': 'self_attn', 'layers': {'q': 'q_proj', 'k': 'k_proj', 'v': 'v_proj', 'o': 'o_proj'}},
      'mlp':  {'name': 'mlp', 'layers': {'gate': 'gate_proj', 'up': 'up_proj', 'down': 'down_proj'}},
      'tail': {'name': '...', 'layers': {...}}
  }
  ```
- 定义 `norm_names`

**Step 4: 写 `modeling_cpm4.py`**
- 从 nanovllm_voxcpm 的 `model.py`（Cpm4Attention / Cpm4MLP / Cpm4DecoderLayer / Cpm4Model）移植
- 适配 SDK base class（BaseModelChunk / BaseModelTail）
- 实现 `get_jit_trace_inputs` + `get_ptq_inputs`（SDK PTQ 需要的接口）

**Step 5: 注册到 SDK**
- `const.py`: SUPPORTED_LLMS 加 "cpm4"
- `utils.py`: resolve_llm_class 加 cpm4 case

**Step 6: PTQ 量化**
```bash
# 校准数据集（VoxCPM2 的 tokenizer + 示例文本）
mtk_make_llm_ptq_calib_dataset converter config_cpm4.json voxcpm2_calib.jsonl

# PTQ（生成量化模型）
mtk_ptq_llm converter config_cpm4.json -d voxcpm2_calib

# 固定 shape（128 token prefill / 1 token decode）
mtk_fix_llm_shape /path/to/quantized/ 128t1024c 1t1024c
```

**Step 7: 验证**
```bash
# float inference（未量化基线）
mtk_inference_float_llm config_cpm4.json prompts.jsonl

# 量化后对比
mtk_inference_float_llm config_cpm4.json prompts.jsonl  # 用量化模型
```

## 三、组件与接口

### 3.1 新增文件

| 文件 | 职责 |
|------|------|
| `mtk_llm_sdk/models/llm/configuration_cpm4.py` | Cpm4 config + fc_names/norm_names 映射 |
| `mtk_llm_sdk/models/llm/modeling_cpm4.py` | Cpm4 模型实现（Attention/MLP/Decoder/Chunk/Tail） |
| `config_cpm4.json` | SDK 格式主 LM 配置 |
| `extract_lm_weights.py` | 从 model.safetensors 提取主 LM 权重 |
| `voxcpm2_calib.jsonl` | 校准数据（VoxCPM2 tokenizer 格式） |

### 3.2 修改文件

| 文件 | 改动 |
|------|------|
| `mtk_llm_sdk/utils/const.py` | SUPPORTED_LLMS 加 "cpm4" |
| `mtk_llm_sdk/utils/utils.py` | resolve_llm_class 加 cpm4 case |

### 3.3 数据流

```
model.safetensors (4.5GB)
    ↓ extract_lm_weights.py
lm_model.safetensors (主LM权重)
    ↓ config_cpm4.json + SDK PTQ
quantized_model/ (MDLA量化模型)
    ↓ mtk_inference_float_llm
质量+速度验证结果
```

## 四、验证标准

| 指标 | 目标 | 方法 |
|------|------|------|
| SDK 能加载 Cpm4 | 不报错 | mtk_ptq_llm 跑通 |
| PTQ 量化成功 | 产出量化模型文件 | mtk_ptq_llm 输出 |
| 质量（token 输出合理） | float vs quantize token 对比 | mtk_inference_float_llm |
| 量化精度 | int8 混合精度，per-FC 控制 | precision config |
| 推理速度估算 | 参考 Qwen-1.5B 在 MDLA 的数据 | SDK benchmark |

## 五、不在本 spec 范围

- DiT / Encoder / VAE / Residual 的转换（后续 spec）
- 端侧推理引擎集成（后续 spec）
- app TTS 替换（后续 spec）
- KV Cache 端侧管理（后续 spec）
- 音色克隆的端侧实现（后续）

## 六、风险

1. **LongRoPE**：Cpm4 用 LongRoPE（rope_scaling long_factor/short_factor），SDK 的 RoPE 实现可能不支持 longrope type → 需检查/适配
2. **μP scaling**（scale_emb=12, scale_depth=1.4）：SDK 可能不处理 → 需在 modeling 里手动加
3. **权重名映射**：Cpm4 的权重 key 和 SDK 期望的格式可能不同（需从 safetensors 读实际 key）
4. **tokenizer**：VoxCPM2 用自定义 tokenizer（tokenization_voxcpm2.py），SDK 可能不认 → 需注册
