// AI 日报：抓取 AI/科技新闻源标题（node http，Android 兼容）
// gateway exec 调用: node /data/local/tmp/ai-news.js [条数]

const https = require('https');
const count = parseInt(process.argv[2] || '8');
const BASE = 'https://rsshub.rssforever.com';

const sources = [
  ['/solidot', 'Solidot 科技'],
  ['/leiphone', '雷峰网 AI'],
  ['/huggingface/daily-papers', 'HuggingFace 论文'],
  ['/36kr/newsflashes', '36kr 快讯'],
];

function fetch(path, name) {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(`【${name}】\n(超时)\n`), 8000);
    https.get(`${BASE}${path}`, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        clearTimeout(timeout);
        const titles = data.match(/<title>[^<]*<\/title>/g) || [];
        const items = titles.slice(1, count + 1).map(t => t.replace(/<\/?title>/g, ''));
        resolve(`【${name}】\n${items.join('\n') || '(无数据)'}\n`);
      });
    }).on('error', (e) => {
      clearTimeout(timeout);
      resolve(`【${name}】\n(错误: ${e.message})\n`);
    });
  });
}

(async () => {
  console.log(`=== AI 日报 ${new Date().toLocaleString('zh-CN')} ===\n`);
  for (const [path, name] of sources) {
    const result = await fetch(path, name);
    console.log(result);
  }
  console.log('=== 数据源: RSSHub(rssforever.com) ===');
})();
