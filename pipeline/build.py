#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The Meridian 每日摘录管道（本地版）：
RSS 订阅 -> 全文提取 -> 段落切分 -> 机翻 -> 词表标注 -> data/articles.json + data/articles.js

用法:
    python pipeline/build.py              # 抓今天的 5 篇
    python pipeline/build.py --date 2026-10-24

说明：本机网络可直连 NPR / phys.org / ScienceDaily / Ars Technica，
其他外媒（Guardian、BBC、Al Jazeera）与 Google 翻译均被阻断，故只用可达源。
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path

import feedparser
import requests
import trafilatura

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vocab import VOCAB, FORM2BASE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
JSON_FILE = DATA_DIR / "articles.json"
JS_FILE = DATA_DIR / "articles.js"
KEEP_DAYS = 7
MIN_WORDS, TARGET_WORDS, MAX_PARAS = 240, 520, 9

SECTIONS = [
    ("World", "国际", [
        "https://feeds.npr.org/1004/rss.xml",
    ]),
    ("Business", "商业 · 财经", [
        "https://feeds.npr.org/1006/rss.xml",
    ]),
    ("Technology", "科技", [
        "https://feeds.npr.org/1019/rss.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
    ]),
    ("Science", "科学", [
        "https://feeds.npr.org/1025/rss.xml",
        "https://www.sciencedaily.com/rss/all.xml",
    ]),
    ("Culture", "文化", [
        "https://feeds.npr.org/1008/rss.xml",
    ]),
]

SKIP_PAT = re.compile(
    r"live blog|live updates|podcast|video|gallery|in pictures|audio|"
    r"picture essay|quiz|crossword|newsletter|up first|briefing", re.I)
PARA_BAD = re.compile(
    r"sign up|subscribe|newsletter|follow us|all rights reserved|"
    r"sponsor message|this article was amended|click here|read more|"
    r"© copyright|npr terms|support npr", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MeridianBot/1.0"}


# ---------------------------------------------------------------- 翻译
def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def chunk_text(text, limit=450):
    """MyMemory 单次请求有长度上限，按句聚合到 limit 以内。"""
    chunks, buf = [], ""
    for s in split_sentences(text) or [text]:
        while len(s) > limit:
            chunks.append(s[:limit])
            s = s[limit:]
        if len(buf) + len(s) + 1 <= limit:
            buf = (buf + " " + s).strip()
        else:
            if buf:
                chunks.append(buf)
            buf = s
    if buf:
        chunks.append(buf)
    return chunks


def translate_mymemory(text):
    out = []
    for piece in chunk_text(text):
        body = ""
        for attempt in range(2):
            try:
                r = requests.get(
                    "https://api.mymemory.translated.net/get",
                    params={"q": piece, "langpair": "en|zh-CN"},
                    headers=UA, timeout=40)
                if r.status_code == 200:
                    j = r.json()
                    if str(j.get("responseStatus")) == "200":
                        body = j["responseData"]["translatedText"]
                        break
            except Exception:
                pass
            time.sleep(1.5 + attempt)
        if not body:
            return ""
        out.append(body)
        time.sleep(0.3)
    return "".join(out)


# ---------------------------------------------------------------- Bing 翻译（主用，国内可直连）
class BingTranslator:
    """Bing 网页版翻译接口：免密钥，国内走 cn.bing.com，境外 Actions 走 www.bing.com。"""

    HOSTS = ("cn.bing.com", "www.bing.com")

    def __init__(self):
        self.host = None
        self.sess = None
        self.ig = self.key = self.token = None

    def refresh(self, host):
        self.sess = requests.Session()
        page = self.sess.get(f"https://{host}/translator", headers=UA, timeout=20)
        txt = page.text
        ig = re.search(r'IG:"([0-9A-Fa-f]+)"', txt)
        helper = re.search(r'params_AbusePreventionHelper\s*=\s*\[(\d+),"([^"]+)"', txt)
        if not (ig and helper):
            raise RuntimeError(f"token parse failed on {host}")
        self.host, self.ig = host, ig.group(1)
        self.key, self.token = helper.group(1), helper.group(2)

    def translate(self, text):
        order = ([self.host] if self.host else []) + list(self.HOSTS)
        for host in order:
            for _ in range(2):
                try:
                    if self.host != host or not self.ig:
                        self.refresh(host)
                    url = (f"https://{host}/ttranslatev3?isVertical=1"
                           f"&&IG={self.ig}&IID=translator.5023.1")
                    r = self.sess.post(
                        url,
                        data={"fromLang": "en", "to": "zh-Hans", "text": text,
                              "token": self.token, "key": self.key},
                        headers={**UA, "Referer": f"https://{host}/translator",
                                 "Origin": f"https://{host}",
                                 "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                        timeout=30)
                    if r.status_code == 200 and r.text.strip():
                        return r.json()[0]["translations"][0]["text"]
                except Exception:
                    pass
                self.ig = None
                time.sleep(0.8)
        raise RuntimeError("bing translate empty")

    def translate_long(self, text, limit=1800):
        if len(text) <= limit:
            return self.translate(text)
        parts = chunk_text(text, limit - 50)
        return "".join(self.translate(p) for p in parts)


BING = BingTranslator()


def translate(text):
    try:
        zh = BING.translate_long(text).strip()
        if zh and zh.lower() != text.lower():
            time.sleep(0.15)
            return zh
    except Exception as e:
        print(f"    bing failed: {e}")
    try:
        zh = translate_mymemory(text).strip()
        if zh and zh.lower() != text.lower():
            return zh
    except Exception as e:
        print(f"    mymemory failed: {e}")
    return ""


# ---------------------------------------------------------------- 抓取
def strip_html(raw):
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", unescape(txt)).strip()


def fetch_fulltext(url, entry):
    try:
        html_doc = trafilatura.fetch_url(url)
        if html_doc:
            text = trafilatura.extract(
                html_doc, include_comments=False, include_tables=False,
                favor_recall=True)
            if text and len(text) > 400:
                return text
    except Exception:
        pass
    for key in ("content", "summary", "description"):
        val = entry.get(key)
        if not val:
            continue
        if isinstance(val, list):
            val = val[0].get("value", "")
        return strip_html(val)
    return ""


def clean_paragraphs(text):
    paras = []
    for chunk in re.split(r"\n+", text):
        p = re.sub(r"\s+", " ", chunk).strip()
        if len(p) < 60 or not re.search(r"[A-Za-z]", p):
            continue
        if PARA_BAD.search(p):
            continue
        paras.append(p)
    return paras


def pick_paragraphs(paras):
    chosen, words = [], 0
    for p in paras:
        if len(chosen) >= MAX_PARAS:
            break
        chosen.append(p)
        words += len(p.split())
        if words >= TARGET_WORDS and len(chosen) >= 5:
            break
    return chosen, words


def source_name(feed, url):
    t = (feed.feed.get("title") or "").lower()
    if "npr" in t or "npr.org" in url:
        return "NPR"
    if "ars" in t or "arstechnica" in url:
        return "Ars Technica"
    if "science" in t and "daily" in t or "sciencedaily" in url:
        return "ScienceDaily"
    return feed.feed.get("title") or "RSS"


def fetch_section(section, section_zh, feeds, used_titles, seen_urls=None, limit=1):
    got = []
    for feed_url in feeds:
        if len(got) >= limit:
            break
        try:
            feed = feedparser.parse(feed_url, request_headers=UA)
        except Exception as e:
            print(f"  feed error {feed_url}: {e}")
            continue
        for entry in feed.entries:
            if len(got) >= limit:
                break
            title = strip_html(entry.get("title", ""))
            link = entry.get("link", "")
            if not title or not link or SKIP_PAT.search(title) or SKIP_PAT.search(link):
                continue
            if title.lower() in used_titles:
                continue
            # 跳过近几天已用过的文章，避免同一篇连续两日出现
            if seen_urls is not None and link in seen_urls:
                continue
            text = fetch_fulltext(link, entry)
            chosen, words = pick_paragraphs(clean_paragraphs(text))
            # NPR 常把标题原样作为首段，去掉以免正文与标题重复
            if len(chosen) > 3 and title.strip().lower() in chosen[0].strip().lower():
                chosen = chosen[1:]
                words = sum(len(p.split()) for p in chosen)
            if words < MIN_WORDS or len(chosen) < 3:
                continue
            used_titles.add(title.lower())
            if seen_urls is not None:
                seen_urls.add(link)
            got.append({
                "section": section, "sectionZh": section_zh,
                "title": title, "url": link,
                "source": source_name(feed, link),
                "byline": entry.get("author") or "",
                "paragraphs_en": chosen, "words": words,
            })
            print(f"  [{section}] {title[:66]}  ({words}w, {len(chosen)}p) <- {source_name(feed, link)}")
    return got


# ---------------------------------------------------------------- 词汇标注
WORD_RE = re.compile(r"[A-Za-z][a-z]+(?:[-'][a-z]+)?")


def annotate(text_all):
    found = {}
    for m in WORD_RE.finditer(text_all.lower()):
        base = FORM2BASE.get(m.group(0))
        if base and base in VOCAB:
            slot = found.setdefault(base, {"forms": set(), "pos0": m.start()})
            slot["forms"].add(m.group(0))
    sents = split_sentences(text_all)
    items = []
    for base, info in sorted(found.items(), key=lambda kv: kv[1]["pos0"]):
        pos, zh = VOCAB[base]
        ex = ""
        pat = re.compile(r"\b(" + "|".join(re.escape(f) for f in info["forms"]) + r")\b", re.I)
        for s in sents:
            if pat.search(s):
                ex = s.strip()
                break
        items.append({"w": base, "pos": pos, "zh": zh, "ex": ex,
                      "forms": sorted(info["forms"] - {base})})
        if len(items) >= 12:
            break
    return items


def level_of(text_all):
    sents = split_sentences(text_all)
    if not sents:
        return "C1", "Advanced"
    avg = len(text_all.split()) / len(sents)
    if avg < 15:
        return "B2", "Upper-intermediate"
    if avg < 20:
        return "C1", "Advanced"
    return "C2", "Proficient"


# ---------------------------------------------------------------- 主流程
def build_day(date_str, seen_urls=None):
    articles, used_titles = [], set()
    for section, section_zh, feeds in SECTIONS:
        print(f"Fetching {section} ...")
        for raw in fetch_section(section, section_zh, feeds, used_titles, seen_urls):
            text_all = " ".join(raw["paragraphs_en"])
            level, level_en = level_of(text_all)
            paras = []
            for p in raw["paragraphs_en"]:
                paras.append({"en": p, "zh": translate(p)})
            vocab = annotate(text_all)
            dek = ""
            for p in raw["paragraphs_en"]:
                if raw["title"].strip().lower() in p.strip().lower():
                    continue
                dek = p
                break
            if not dek:
                dek = raw["paragraphs_en"][0]
            if len(dek) > 200:
                dek = dek[:197].rsplit(" ", 1)[0] + "…"
            articles.append({
                "id": f"{date_str}-{section.lower()}",
                "section": section, "sectionZh": section_zh,
                "title": raw["title"], "dek": dek,
                "source": raw["source"], "sourceUrl": raw["url"],
                "byline": raw["byline"],
                "dateLabel": date_str,
                "words": raw["words"],
                "readTime": max(3, round(raw["words"] / 200)),
                "level": level, "levelEn": level_en,
                "paragraphs": paras,
                "vocab": vocab,
                "homeWords": [v["w"] for v in vocab[:5]],
                "keyVocab": [v["w"] for v in vocab[:8]],
            })
    return {"date": date_str, "articles": articles}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    days = []
    if JSON_FILE.exists():
        try:
            days = json.loads(JSON_FILE.read_text(encoding="utf-8")).get("days", [])
        except Exception:
            days = []
    # 去掉当天旧数据，只拿更早日期的 URL 做去重，重跑当天不会被自己挡住
    days = [d for d in days if d.get("date") != args.date]
    seen_urls = {
        a.get("sourceUrl")
        for d in days for a in d.get("articles", [])
        if a.get("sourceUrl")
    }

    day = build_day(args.date, seen_urls)
    if not day["articles"]:
        print("No articles fetched; keep existing data.")
        sys.exit(1)

    days.insert(0, day)
    days = days[:KEEP_DAYS]
    payload = {"updated": datetime.now(timezone.utc).isoformat(), "days": days}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    JSON_FILE.write_text(text, encoding="utf-8")
    # 同步产出一份 JS，便于直接双击 index.html 打开（file:// 不支持 fetch）
    JS_FILE.write_text(
        "window.__MERIDIAN_DATA__ = " + text + ";\n", encoding="utf-8")
    print(f"Wrote {JSON_FILE.name} + {JS_FILE.name} · "
          f"{len(day['articles'])} articles · {len(days)} days kept")


if __name__ == "__main__":
    main()
