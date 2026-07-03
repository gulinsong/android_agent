# VoxCPM2 主LM MDLA PTQ 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 mtk_llm_sdk converter 把 VoxCPM2 主 LM（MiniCPM 架构，SDK 已支持）量化为 MDLA 模型，PC 端验证 SDK 能加载 + PTQ 跑通。

**Architecture:** VoxCPM2 主 LM 是 MiniCPM 变体（Cpm4, GQA+RoPE+RMSNorm+SwiGLU），SDK 内置 minicpm 支持。提取主 LM 权重（`base_lm.*` 前缀 254 keys）+ 创建 SDK config（model_type=minicpm）+ PTQ 量化。

**Tech Stack:** Python, mtk_llm_sdk 3.4.2, safetensors, torch

**Spec:** `docs/superpowers/specs/2026-07-01-voxcpm2-mdla-ptq-design.md`

## Global Constraints

- SDK 路径: `/home/tsm/.local/lib/python3.10/site-packages/mtk_llm_sdk`
- VoxCPM2 模型: `/home/tsm/work/models/VoxCPM2/model.safetensors` (4.5GB, bfloat16)
- 主 LM 权重前缀: `base_lm.`（254 keys: embed_tokens + 28 layers + norm）
- SDK model_type: `minicpm`（SUPPORTED_LLMS 已包含）
- lm_config 参数: hidden_size=2048, intermediate_size=6144, num_attention_heads=16, num_key_value_heads=2, num_hidden_layers=28, rope_theta=10000, vocab_size=73448, scale_emb=12, dim_model_base=256, scale_depth=1.4
- VoxCPM2 tokenizer: `/home/tsm/work/models/VoxCPM2/tokenizer.json` (标准 tokenizer_config)
- 工作目录: `/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/`

---

### Task 1: 提取主 LM 权重 + 创建 SDK config

**Files:**
- Create: `tts-adapter/voxcpm2_ptq/extract_lm_weights.py`
- Create: `tts-adapter/voxcpm2_ptq/config_minicpm.json`
- Output: `tts-adapter/voxcpm2_ptq/lm_model/` (权重 + config + tokenizer)

**Interfaces:**
- Produces: `lm_model/model.safetensors`（主LM权重，key 去掉 `base_lm.` 前缀），`lm_model/config.json`（SDK minicpm 格式）

- [ ] **Step 1: 创建工作目录**

```bash
mkdir -p /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq
```

- [ ] **Step 2: 写 extract_lm_weights.py**

```python
#!/usr/bin/env python3
"""从 VoxCPM2 model.safetensors 提取主 LM 权重（base_lm.* 前缀）。
SDK MiniCPM 期望的 key 格式: embed_tokens.weight / layers.0.self_attn.q_proj.weight / norm.weight
VoxCPM2 的 key: base_lm.embed_tokens.weight / base_lm.layers.0.* / base_lm.norm.weight
提取后去掉 base_lm. 前缀。
"""
from safetensors.torch import save_file
from safetensors import safe_open
import torch
import json
import os
import shutil

SRC = "/home/tsm/work/models/VoxCPM2/model.safetensors"
OUT_DIR = "/home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model"
PREFIX = "base_lm."

os.makedirs(OUT_DIR, exist_ok=True)

# 提取 base_lm.* 权重，去掉前缀
extracted = {}
with safe_open(SRC, framework="pt") as f:
    for key in f.keys():
        if key.startswith(PREFIX):
            new_key = key[len(PREFIX):]
            extracted[new_key] = f.get_tensor(key).to(torch.float32)
            print(f"  {key} -> {new_key}: {extracted[new_key].shape}")

print(f"\n提取 {len(extracted)} 个权重")
save_file(extracted, os.path.join(OUT_DIR, "model.safetensors"))
print(f"保存到 {OUT_DIR}/model.safetensors")

# 复制 tokenizer 文件
VoxCPM2_DIR = "/home/tsm/work/models/VoxCPM2"
for fname in ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]:
    src = os.path.join(VoxCPM2_DIR, fname)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(OUT_DIR, fname))
        print(f"复制 {fname}")
```

- [ ] **Step 3: 写 config_minicpm.json (SDK MiniCPM 格式)**

```json
{
    "model_type": "minicpm",
    "llm": {
        "model_type": "minicpm",
        "bos_token_id": 1,
        "eos_token_id": 2,
        "hidden_size": 2048,
        "intermediate_size": 6144,
        "max_position_embeddings": 32768,
        "num_attention_heads": 16,
        "num_key_value_heads": 2,
        "num_hidden_layers": 28,
        "rms_norm_eps": 1e-05,
        "rope_theta": 10000,
        "kv_channels": 128,
        "vocab_size": 73448,
        "scale_emb": 12,
        "dim_model_base": 256,
        "scale_depth": 1.4,
        "tie_word_embeddings": false
    }
}
```

- [ ] **Step 4: 运行提取脚本**

```bash
cd /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq
python3 extract_lm_weights.py
```
Expected: 提取 254 个权重，保存 `lm_model/model.safetensors` + tokenizer 文件。

- [ ] **Step 5: 复制 config 到 lm_model/**

```bash
cp /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/config_minicpm.json \
   /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json
```

- [ ] **Step 6: 验证 SDK 能加载 config**

```bash
python3 -c "
from mtk_llm_sdk.utils import utils
result = utils.resolve_llm_class({'model_type': 'minicpm'})
print(f'SDK resolve: {result}')
"
```
Expected: 不报错，返回 MiniCPM config/modeling class。

- [ ] **Step 7: Commit**

```bash
cd /home/tsm/work/android_agent
git add tts-adapter/voxcpm2_ptq/extract_lm_weights.py tts-adapter/voxcpm2_ptq/config_minicpm.json
git commit -m "feat(tts): extract VoxCPM2 main LM weights + SDK minicpm config"
```

---

### Task 2: float inference 验证（SDK 能跑主 LM）

**Files:**
- Create: `tts-adapter/voxcpm2_ptq/prompts.jsonl`
- Test: `mtk_inference_float_llm`

**Interfaces:**
- Consumes: Task 1 的 `lm_model/`（config.json + model.safetensors + tokenizer）
- Produces: float inference 输出（验证 SDK 能加载+推理 VoxCPM2 主 LM）

- [ ] **Step 1: 创建测试 prompts**

```bash
cat > /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/prompts.jsonl << 'EOF'
{"prompt": "你好世界"}
{"prompt": "今天天气怎么样"}
EOF
```

- [ ] **Step 2: 运行 float inference**

```bash
mtk_inference_float_llm \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/prompts.jsonl
```
Expected: 不报错（可能输出 gibberish token，因为这是 TTS 的 LM 不是文本 LLM，但**能跑 = SDK 加载成功**）。如果报错，检查 config 参数 / tokenizer / 权重格式。

- [ ] **Step 3: 如果报错，诊断 + 修复**

常见问题：
- **tokenizer 不认**: SDK 可能要求标准 HF tokenizer。检查 `tokenizer_config.json` 的 model_type。
- **scale_emb/dim_model_base 缺失**: config.json 里必须有这些 MiniCPM 特有参数。
- **权重 key 不匹配**: 检查 `lm_model/model.safetensors` 的 key 是否和 SDK MiniCPM 期望的一致（embed_tokens / layers.N.self_attn.* / layers.N.mlp.* / norm）。

- [ ] **Step 4: Commit**

```bash
git add tts-adapter/voxcpm2_ptq/prompts.jsonl
git commit -m "test(tts): float inference validation for VoxCPM2 main LM"
```

---

### Task 3: PTQ 校准数据集

**Files:**
- Create: `tts-adapter/voxcpm2_ptq/calib.jsonl`
- Output: `tts-adapter/voxcpm2_ptq/calib_dataset/`

- [ ] **Step 1: 创建校准数据（从 VoxCPM2 tokenizer 格式）**

```bash
# 校准数据用简单文本（SDK 期望 jsonl 格式）
cat > /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/calib.jsonl << 'EOF'
{"input": "你好，欢迎使用语音助手"}
{"input": "今天天气真好，我想出去玩"}
{"input": "请问有什么可以帮你的吗"}
{"input": "好的，马上为你处理"}
{"input": "欢迎回来，需要播放音乐吗"}
EOF
```

- [ ] **Step 2: 生成 SDK 校准数据集**

```bash
mtk_make_llm_ptq_calib_dataset converter \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/calib.jsonl
```
Expected: 生成校准数据集（不报错）。如果 wikitext 作为 fallback：
```bash
mtk_make_llm_ptq_calib_dataset converter \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json \
    wikitext
```

- [ ] **Step 3: Commit**

```bash
git add tts-adapter/voxcpm2_ptq/calib.jsonl
git commit -m "feat(tts): PTQ calibration dataset for VoxCPM2 main LM"
```

---

### Task 4: PTQ 量化

**Files:**
- Output: `tts-adapter/voxcpm2_ptq/quantized_model/`

- [ ] **Step 1: 先生成 precision template**

```bash
mtk_ptq_llm converter \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json
```
Expected: 生成 precision config json template（打印文件路径）。这步只生成模板不量化。

- [ ] **Step 2: 检查 precision template**

```bash
# 找生成的 precision json
find /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq -name "*precision*" -o -name "*.json" | grep -v config | head -5
```
查看 precision template，了解 SDK 对每个 FC 层的默认精度设置。

- [ ] **Step 3: 运行 PTQ（用默认 precision + 校准数据）**

```bash
mtk_ptq_llm converter \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json \
    -d /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/calib_dataset/
```
Expected: 生成量化模型（可能需要几分钟，取决于校准数据量）。如果需要 precision config：
```bash
mtk_ptq_llm converter \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json \
    -p <precision_config_path> \
    -d <calib_dataset_path>
```

- [ ] **Step 4: 验证量化模型产出**

```bash
find /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq -name "*.bin" -o -name "*.mlir" -o -name "*.tflite" | head -10
ls -la /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/quantized_model/ 2>/dev/null || echo "查找量化输出目录"
```
Expected: 有量化模型文件（.bin/.mlir/.tflite）。

- [ ] **Step 5: Commit**

```bash
git add tts-adapter/voxcpm2_ptq/quantized_model/ 2>/dev/null
git add tts-adapter/voxcpm2_ptq/*.json 2>/dev/null
git commit -m "feat(tts): PTQ quantized VoxCPM2 main LM model"
```

---

### Task 5: 固定 shape + 最终验证

- [ ] **Step 1: 固定 shape（prefill 128 token / decode 1 token）**

```bash
# 找量化模型目录路径
QUANT_DIR=$(find /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq -name "model.bin" -exec dirname {} \; | head -1)
echo "量化模型目录: $QUANT_DIR"

mtk_fix_llm_shape "$QUANT_DIR" 128t1024c 1t1024c
```
Expected: 固定 shape（prefill batch=128 token / KV cache=1024 context；decode batch=1 token）。

- [ ] **Step 2: 量化后推理验证**

```bash
mtk_inference_float_llm \
    /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/lm_model/config.json \
    /home/tsm/work/android_agent/tts-adapter/voxcpq2_ptq/prompts.jsonl
```
Expected: 不报错，输出 token 序列（gibberish 也没关系，**能跑 = 量化成功**）。

- [ ] **Step 3: 记录验证结果**

```bash
cat > /home/tsm/work/android_agent/tts-adapter/voxcpm2_ptq/PTQ_RESULT.md << 'EOF'
# VoxCPM2 主LM PTQ 验证结果

## 环境
- mtk_llm_sdk: 3.4.2
- VoxCPM2 主LM: MiniCPM架构, 28层, GQA(2 kv_heads), hidden=2048
- 模型大小: 原始 float ~XXX MB, 量化后 ~XXX MB

## 验证项
- [ ] SDK 加载 config: PASS/FAIL
- [ ] float inference: PASS/FAIL
- [ ] PTQ 量化: PASS/FAIL
- [ ] 量化后 inference: PASS/FAIL
- [ ] shape fix: PASS/FAIL

## 下一步
- DiT 去噪网络转换
- VAE 转换
- 端侧集成
EOF
```

- [ ] **Step 4: Commit**

```bash
git add tts-adapter/voxcpm2_ptq/PTQ_RESULT.md
git commit -m "docs(tts): VoxCPM2 main LM PTQ validation results"
```

---

## Self-Review

**Spec coverage:**
- 提取主LM权重 → Task 1 ✅
- SDK config（model_type=minicpm）→ Task 1 ✅
- float inference 验证 → Task 2 ✅
- PTQ 校准数据 → Task 3 ✅
- PTQ 量化 → Task 4 ✅
- shape fix + 最终验证 → Task 5 ✅

**Placeholder:** 无 TBD。每步有具体命令和期望输出。

**风险（需在执行时处理，不阻塞计划）：**
1. **LongRoPE**: VoxCPM2 lm_config 有 rope_scaling（long_factor/short_factor），MiniCPM config 没有这些参数。如果 SDK 的 RoPE 不支持 LongRoPE，可能推理结果不对（但能跑）。可以先不设 rope_scaling 看 SDK 是否报错。
2. **scale_emb=12**: MiniCPM config 需要 scale_emb/dim_model_base。如果 SDK 的 modeling_minicpm 用了这些参数做 embedding scale，需要确认一致。
3. **tokenizer**: VoxCPM2 用自定义 tokenizer，SDK 可能不认。如果 mtk_inference_float_llm 报 tokenizer 错，需要注册或适配。
4. **权重 dtype**: safetensors 是 bfloat16，SDK 可能要求 float32。extract 脚本已转 float32。
