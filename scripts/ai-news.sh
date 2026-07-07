#!/bin/sh
# AI 日报：抓取 AI/科技新闻源标题（sed 提取，Android 兼容）
# gateway exec 调用 → LLM 总结

COUNT="${1:-8}"
BASE="https://rsshub.rssforever.com"

echo "=== AI 日报 $(date '+%Y-%m-%d %H:%M') ==="
echo ""

fetch() {
  url="$1"; name="$2"
  echo "【$name】"
  timeout 8 curl -s "$url" 2>/dev/null | sed -n 's/.*<title>\([^<]*\)<\/title>.*/\1/p' | tail -n +2 | head -n "$COUNT"
  echo ""
}

fetch "$BASE/solidot" "Solidot 科技"
fetch "$BASE/leiphone" "雷峰网 AI"
fetch "$BASE/huggingface/daily-papers" "HuggingFace 论文"
fetch "$BASE/36kr/newsflashes" "36kr 快讯"

echo "=== 数据源: RSSHub(rssforever.com) ==="
