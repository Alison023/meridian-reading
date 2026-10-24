# The Meridian · 外刊精读

> A daily English close-reading reader — five hand-picked stories, paragraph-level Chinese translation, tap-to-define vocabulary.

每天自动摘录 5 篇外刊，按栏目分好，配中文对照译文与外刊高频词标注。为长时间阅读设计：报纸式排版、3D 书页翻页、点词查义、生词本与段落笔记。

## 每天的内容

| 栏目 | 内容 |
| --- | --- |
| World | 国际新闻 |
| Business | 商业与财经 |
| Technology | 科技 |
| Science | 科学 |
| Culture | 文化 |

- 每个栏目每天 1 篇，共 5 篇，保留最近 7 天
- 每篇取 7–9 段（约 250–550 词），自动估算难度（B2 / C1 / C2）与阅读时长
- 正文中原样保留，不做删改；译文为机器翻译，逐段独立

## 阅读功能

- **点词查义**：文中虚线标注的单词可点击，右侧面板给出音标、词性、中文释义与例句；未收录的词会给出提示
- **逐段对照**：每段可单独展开中文译文，也可一键切换双语全文对照
- **字号调节**：15–24px 逐级调节，选择会被记住
- **生词本**：点词面板内收藏，存入浏览器 localStorage；词汇库页可复习
- **段落笔记**：给任意段落加书签与笔记，按文章分别保存
- **阅读进度**：记住上次读到的位置与累计阅读时长，返回首页会回到原滚动位置
- **3D 书页翻页**：页面切换时整页翻动，遵循系统「减少动态效果」设置自动降级为淡入

## 目录结构

```
index.html                 # 单文件站点（HTML + CSS + JS，无框架依赖）
data/articles.json         # 每日数据（管道产出）
data/articles.js           # 同一份数据包成 JS，供 file:// 直接打开
pipeline/build.py          # 抓取 → 分段 → 翻译 → 标注 → 输出
pipeline/vocab.py          # 外刊高频词表（约 500 词，含变形匹配）
pipeline/requirements.txt
.github/workflows/daily.yml # 每天北京时间 08:30 自动更新
```

## 本地使用

不需要服务器，直接双击 `index.html` 即可（数据通过 `data/articles.js` 读取）。

如果更习惯走 HTTP：

```bash
python -m http.server 8788
# 打开 http://localhost:8788/index.html
```

数据缺失时，站点会回退到内置的示例文章，界面功能不受影响。

## 每天更新内容

```bash
pip install -r pipeline/requirements.txt
python pipeline/build.py                 # 抓今天的 5 篇
python pipeline/build.py --date 2026-10-24   # 补指定日期
```

管道流程：

1. 读取各栏目 RSS，按标题过滤掉直播、播客、图集、通讯等不适合精读的条目
2. 用 trafilatura 提取全文，按段落切分并剔除版权、订阅引导等噪音
3. 逐段调用 Bing 网页翻译接口（`cn.bing.com`，失败回退 `www.bing.com`、MyMemory）
4. 用内置高频词表匹配词形（含复数、-ed、-ing 等变形），生成词卡
5. 写入 `data/articles.json` 与 `data/articles.js`，超过 7 天的旧数据自动淘汰

单段翻译失败时留空，不阻塞整篇；页面会隐藏空的译文块。

## 部署

推送到 GitHub 后，在仓库 `Settings → Pages` 选择 `Deploy from a branch`，分支 `main`、目录 `/ (root)` 即可。

`Daily digest` 工作流会在每天 UTC 00:30（北京时间 08:30）运行管道并提交新数据，也可在 Actions 页面手动触发。工作流需要仓库的写权限，`daily.yml` 中已声明 `contents: write`。

## 数据格式

```json
{
  "updated": "2026-10-24T01:20:00+00:00",
  "days": [
    {
      "date": "2026-10-24",
      "articles": [
        {
          "id": "2026-10-24-world",
          "section": "World",
          "sectionZh": "国际",
          "title": "…",
          "dek": "…",
          "source": "NPR",
          "sourceUrl": "https://…",
          "byline": "…",
          "words": 287,
          "readTime": 3,
          "level": "C1",
          "paragraphs": [{ "en": "…", "zh": "…" }],
          "vocab": [{ "w": "authority", "pos": "n.", "zh": "当局", "ex": "…" }]
        }
      ]
    }
  ]
}
```

## 已知限制

- **抓取源只有 NPR**：本项目在一台大陆网络环境下开发，Guardian、BBC、Al Jazeera 均无法直连；NPR 的 RSS 可正常访问，故只用它。改源只需编辑 `pipeline/build.py` 里的 `SECTIONS`
- **译文为机器翻译**：用于理解与对照，不适合作为精译范本；专有名词偶尔会译得不统一
- **字体来自 Google Fonts**：离线时回退到系统衬线字体，排版略紧但可读
- **无后端**：生词本与笔记存在浏览器本地，换设备或清缓存会丢失

## 版权

文章版权归原作者与发布媒体所有，本项目仅做个人学习用途的摘录与链接，正文未作删改，每篇均标注来源并附原文链接。如需引用请回到原站。
