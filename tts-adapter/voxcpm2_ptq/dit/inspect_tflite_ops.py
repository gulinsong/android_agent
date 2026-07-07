#!/usr/bin/env python3
"""检查 tflite 的 op 清单，确认是否仍含 MTKEXT_RMS_NORMALIZATION / MTKEXT_SILU。
用法: python inspect_tflite_ops.py <model.tflite>
"""
import sys
from collections import Counter

# 用 tflite_micro / tflite_runtime / mtk_converter 任一可用的解析
path = sys.argv[1]
try:
    import mtk_converter  # noqa
    # mtk_converter 没直接暴露 op list，fallback 到 flatbuffers 自己解析
    raise ImportError
except ImportError:
    pass

# 直接解析 flatbuffer：tflite schema 的 op codes 在 OperatorCode 表
# 简单粗暴：grep 二进制里的 builtin/op 名字
import re
with open(path, "rb") as f:
    data = f.read()

# tflite custom op 名字是明文 C 字符串
# MTK 自定义 op 通常以 MTKEXT_ / TFLITE_Detection 等 前缀
mtkext = re.findall(rb"MTKEXT[_A-Z0-9]+", data)
custom = re.findall(rb"[A-Z][A-Za-z0-9_]{4,}", data)

print(f"文件: {path} ({len(data)/1e6:.0f}MB)")
print()

mtk_counter = Counter(s.decode() for s in mtkext)
print("=== MTKEXT op 出现次数 ===")
if mtk_counter:
    for op, n in mtk_counter.most_common():
        print(f"  {n:4d}  {op}")
else:
    print("  (无 MTKEXT op — patched 干净 ✓)")

# 关注的关键 op（标准 tflite builtin 名字也是明文）
print()
print("=== 关键标准 op 是否存在 ===")
for key in [b"RSQRT", b"TRANSPOSE", b"MEAN", b"SOFTMAX", b"CONV_2D",
            b"FULLY_CONNECTED", b"RESHAPE", b"SIGMOID", b"EXP", b"DIV",
            b"MUL", b"NEG", b"ADD"]:
    n = data.count(key)
    print(f"  {key.decode():18s} {n}")
