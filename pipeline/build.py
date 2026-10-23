#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The Meridian 每日摘录管道：
RSS 订阅 -> 全文提取 -> 段落切分 -> 机翻(谷歌/ MyMemory 兜底) -> 词表标注 -> data/articles.json

用法:
    python pipeline/build.py              # 抓今天的 5 篇
    python pipeline/build.py --date 2026-10-24
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
DATA_FILE = ROOT / "data" / "articles.json"
KEEP_DAYS = 7
MIN_WORDS, TARGET_WORDS, MAX_PARAS = 360, 650, 10

SECTIONS = [
    ("World", "国际", [
        "https://www.theguardian.com/world/rss",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
    ]),
    ("Business", "商业 · 财经", [
        "https://www.theguardian.com/uk/business/rss",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ]),
    ("Technology", "科技", [
        "https://www.theguardian.com/uk/technology/rss",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
    ]),
    ("Science", "科学", [
        "https://www.theguardian.com/science/rss",
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ]),
    ("Culture", "文化", [
        "https://www.theguardian.com/uk/culture/rss",
        "https://www.aljazeera.com/xml/rss/all.xml",
    ]),
]

SKIP_PAT = re.compile(
    r"live blog|live updates|podcast|video|gallery|in pictures|audio|"
    r"picture essay|quiz|crossword|newsletter sign", re.I)
PARA_BAD = re.compile(
    r"sign up|subscribe|newsletter|follow us|all rights reserved|"
    r"this article was amended|click here|read more", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TheMeridianBot/1.0"}


# ---------------------------------------------------------------- 翻译
def translate_gtx(text):
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text},
        headers=UA, timeout=25)
    r.raise_for_status()
    return "".join(seg[0] for seg in r.json()[0] if seg[0])


def translate_mymemory(text):
    parts = split_sentences(text) if len(text) > 450 else [text]
    out = []
    for p in parts:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": p, "langpair": "en|zh-CN"},
            headers=UA, timeout=25)
        r.raise_for_status()
        out.append(r.json()["responseData"]["translatedText"])
        time.sleep(0.4)
    return "".join(out)


def translate(text):
    for fn in (translate_gtx, translate_mymemory):
        try:
            zh = fn(text).strip()
            if zh and zh.lower() != text.lower():
                return zh
        except Exception as e:
            print(f"    translate via {fn.__name__} failed: {e}")
    return ""


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ---------------------------------------------------------------- 抓取
def strip_html(raw):
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", unescape(txt)).strip()


def fetch_fulltext(url, entry):
    try:
        html_doc = trafilatura.fetch_url(url)
        if html_doc:
            return trafilatura.extract(
                html_doc, include_comments=False, include_tables=False,
                favor_recall=True) or ""
    except Exception:
        pass
    # RSS 正文兜底（Guardian 的 description 常含全文）
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
        if len(chosen) >= MAX_PARAS or words >= TARGET_WORDS + 250:
            break
        chosen.append(p)
        words += len(p.split())
        if words >= TARGET_WORDS and len(chosen) >= 6:
            break
    return chosen, words


def source_name(feed, url):
    t = (feed.feed.get("title") or "").lower()
    if "guardian" in t or "theguardian" in url:
        return "The Guardian"
    if "bbc" in t or "bbci" in url:
        return "BBC News"
    if "aljazeera" in url or "al jazeera" in t:
        return "Al Jazeera"
    return feed.feed.get("title") or "RSS"


def fetch_section(section, section_zh, feeds, limit=1):
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
            text = fetch_fulltext(link, entry)
            paras = clean_paragraphs(text)
            chosen, words = pick_paragraphs(paras)
            if words < MIN_WORDS or len(chosen) < 4:
                continue
            byline = entry.get("author") or ""
            got.append({
                "section": section, "sectionZh": section_zh,
                "title": title, "url": link,
                "source": source_name(feed, link),
                "byline": byline,
                "paragraphs_en": chosen, "words": words,
            })
            print(f"  [{section}] {title[:70]}  ({words}w, {len(chosen)}p) <- {source_name(feed, link)}")
    return got


# ---------------------------------------------------------------- 词汇标注
WORD_RE = re.compile(r"[A-Za-z][a-z]+(?:[-'][a-z]+)?")


def annotate(text_all):
    found = {}  # base -> {"forms": set, "pos0": idx}
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


# ---------------------------------------------------------------- 主流程
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


def build_day(date_str):
    articles = []
    for section, section_zh, feeds in SECTIONS:
        print(f"Fetching {section} ...")
        for raw in fetch_section(section, section_zh, feeds):
            text_all = " ".join(raw["paragraphs_en"])
            level, level_en = level_of(text_all)
            paras = []
            for p in raw["paragraphs_en"]:
                zh = translate(p)
                paras.append({"en": p, "zh": zh})
                time.sleep(0.25)
            vocab = annotate(text_all)
            dek = raw["paragraphs_en"][0]
            if len(dek) > 200:
                dek = dek[:197].rsplit(" ", 1)[0] + "…"
            articles.append({
                "id": f"{date_str}-{section.lower()}",
                "section": section, "sectionZh": section_zh,
                "title": raw["title"], "dek": dek,
                "source": raw["source"], "sourceUrl": raw["url"],
                "byline": raw["byline"],
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

    day = build_day(args.date)
    if not day["articles"]:
        print("No articles fetched; keep existing data.")
        sys.exit(1)

    days = []
    if DATA_FILE.exists():
        try:
            days = json.loads(DATA_FILE.read_text(encoding="utf-8")).get("days", [])
        except Exception:
            days = []
    days = [d for d in days if d.get("date") != args.date]
    days.insert(0, day)
    days = days[:KEEP_DAYS]

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(
        {"updated": datetime.now(timezone.utc).isoformat(), "days": days},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {DATA_FILE} · {len(day['articles'])} articles · {len(days)} days kept")


if __name__ == "__main__":
    main()
