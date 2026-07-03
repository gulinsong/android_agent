# VoxCPM2 主LM MDLA PTQ 验证结果

> 日期: 2026-07-03
> 结论: **PASS** — mtk_llm_sdk 能量化 VoxCPM2 主LM（Cpm4/MiniCPM 架构）并推理

## 环境

- conda: `voxcpm2_ptq`
- mtk_converter 8.16.0, mtk_llm_sdk 2.5.3, **mtk_quantization 8.2.1**（来自 neuropilot-sdk-basic-8.0.11 offline_tool）
- torch 2.12.1+cpu
- VoxCPM2 主LM: MiniCPM 架构, 28 层, GQA(2 kv_heads), hidden=2048, vocab=73448

## 验证项（全 PASS）

| 步骤 | 命令 | 耗时 | 状态 |
|------|------|------|------|
| 校准数据 | `mtk_make_llm_ptq_calib_dataset converter config.json calib_tokens.jsonl -b 16 -m 64` | 5min | PASS |
| PTQ 量化 | `mtk_ptq_llm converter config.json -d <calib> -p sym4W_sym16A -w hessian --pad_lm_head` | 24min | PASS |
| 固定 shape | `mtk_fix_llm_shape <tflite_dir> 128t1024c 1t1024c -n 1` | 4min | PASS |
| 推理验证 | `mtk_inference_llm_tflite config.json <_128t1024c dir> inference_tokens.jsonl -m 32 --save` | 8min44s | PASS |

## 量化效果

- 原始 float32: 6.1GB
- 量化后 (sym4W_sym16A): 1GB（28 个 tflite chunk × 24MB + 287MB embedding_int16.bin）
- 压缩比: ~6x

## 关键：4 个集成 bug 及修复（后续复用必读）

### 1. config 必须扁平，不能 `llm` 嵌套
SDK `MinicpmConfig` 直接读 `config["vocab_size"]`，嵌套在 `config["llm"]` 下会 KeyError。
→ 所有架构参数放顶层（HF 标准 MiniCPM 格式）。

### 2. SDK tokenizer 是 slow LlamaTokenizer（需 sentencepiece），VoxCPM2 只有 fast tokenizer.json
→ **绕过**：用 tokens 格式输入（`{"tokens": "1 233 456 ..."}`，空格分隔字符串）。
  外部用 `transformers.LlamaTokenizerFast` 预 tokenize（VoxCPM2 tokenizer 底层就是 LlamaTokenizerFast，能加载）。
  make_calib / inference 的 inputs 都支持 "text or tokens"。

### 3. torchaudio 加载失败（user site 污染）
voxcpm2_ptq conda 继承 user site 的 torchaudio 2.11.0（编译 vs torch 2.11+CUDA13），
与 conda 的 torch 2.12.1+cpu 双重不匹配。transformers 的 loss_rnnt 间接 import 触发。
→ 在 conda site-packages 放 `sitecustomize.py`，启动时把 stub torchaudio 注入 `sys.modules`
  （设 `__spec__` + `__path__`），让 `is_torchaudio_available()` 守卫通过。PTQ 不用 torchaudio 任何功能。

### 4. 权重 key 映射 + VoxCPM2 无独立 lm_head
- SDK 期望 HF 标准: `model.embed_tokens.weight` / `model.layers.N.*` / `model.norm.weight`
- VoxCPM2 原始: `base_lm.*` → 重映射 `base_lm.<X>` → `model.<X>`
- VoxCPM2 主LM **无 lm_head**（TTS LM 不预测 vocab token，hidden 直接送 DiT）
  → 用 `embed_tokens` clone 一份当 lm_head（PTQ 校准只需激活分布）。
  → `extract_lm_weights.py` 已更新反映此逻辑。

## 已知限制 / 架构理解修正

- **inference token 重复 ≠ 量化质量问题（重要）**：VoxCPM2 是 "tokenizer-free diffusion autoregressive"（架构 LocEnc→TSLM→RALM→LocDiT）。主LM（TSLM）**不经 lm_head 生成 vocab token**——它输出 hidden → `lm_to_dit_proj` → DiT。这就是为什么权重里没有 lm_head（只有 stop_head）。我加的 embed clone 纯粹为满足 SDK minicpm 的建模假设；inference 用它生成 vocab token 是 SDK 假设，不代表 VoxCPM2 真实输出。**PTQ 校准激活来自 layers forward（不涉 lm_head），所以量化本身有效**。token 重复是 inference 概念错，不是量化退化。
- **真质量验证**需要完整 pipeline：主LM hidden → DiT → VAE → 音频。即 DiT/VAE 也要转，或 PC 上用 nanovllm 替换主LM 为量化版比对音频。
- **LongRoPE 暂不含**：VoxCPM2 用 rope_scaling longrope，config 暂未含（短句校准/推理 <64 token 无影响）。
- **CPU 推理慢**：torch 2.12.1+cpu，8min/2条。GPU 或端侧 MDLA 会快。

## 下一步

- DiT / Encoder / VAE / Residual 转换（同构 Transformer，复用主 LM 流程）
- 端侧推理引擎集成（mt6991 MDLA，build_runner 编译 C++ runner）
- 评估 lm_head clone 对 TTS 质量的影响（可能需训练真 lm_head 或直接用 hidden state）

## 产出位置

- 量化模型: `/home/tsm/work/android_agent/tflite/lm_model_sym4W_sym16A_Overall_hessian{,_128t1024c,_1t1024c}/`
- 工作目录: `tts-adapter/voxcpm2_ptq/`（config, extract 脚本, calib 数据, preformatter）
- 校准数据: `/home/tsm/work/android_agent/calibration_datasets/lm_model/`
