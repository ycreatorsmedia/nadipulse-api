"""
NādiPulse Telugu News API v3
- Extracts actual publish dates from articles
- Political articles only
- Rolling 24-hour window
- IST timestamps
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import threading
from datetime import datetime, timezone, timedelta
import re

app = FastAPI(title="NādiPulse Telugu News API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "te-IN,te;q=0.9,en;q=0.8",
}

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST)

def now_ist_str():
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")

def format_ist(dt):
    """Format datetime as IST string"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")

cache = {
    "articles": [],
    "last_updated": None,
    "last_updated_display": None,
    "status": "starting"
}

# ─────────────────────────────────────────
# POLITICAL FILTER
# ─────────────────────────────────────────
POLITICAL_KEYWORDS = [
    "రాజకీయ","ప్రభుత్వ","మంత్రి","ముఖ్యమంత్రి","అసెంబ్లీ","పార్లమెంట్",
    "ఎన్నిక","వైఎస్ఆర్సీపీ","టీడీపీ","బీజేపీ","జనసేన","కాంగ్రెస్",
    "జగన్","చంద్రబాబు","పవన్","లోకేశ్","విపక్షం","అధికార",
    "ఎమ్మెల్యే","ఎంపీ","సీఎం","మంత్రివర్గ","బడ్జెట్","పథకం","సంక్షేమ",
    "ఆరోపణ","విమర్శ","పాలన","పార్టీ","ఓటు","నియోజకవర్గ",
    "government","minister","chief minister","assembly","parliament",
    "election","YSRCP","TDP","BJP","Janasena","Congress",
    "jagan","chandrababu","pawan","lokesh","opposition","ruling",
    "MLA","MP","CM","cabinet","budget","scheme","welfare","policy",
    "allegation","criticism","political","party","vote","constituency",
    "governance","andhra pradesh government","telugu desam","ysr congress",
]

EXCLUDE_KEYWORDS = [
    "cricket","ipl","football","tennis","match","score","wicket",
    "batting","bowling","stadium","tournament","champion","trophy",
    "movie","film","actor","actress","director","cinema","box office",
    "release","trailer","teaser","ott","series",
    "ఐపీఎల్","క్రికెట్","మ్యాచ్","స్కోర్",
    "సినిమా","మూవీ","హీరో","హీరోయిన్","నటుడు","విడుదల",
    "recipe","cooking","fashion","beauty","horoscope","astrology",
    "రాశిఫలం","వాస్తు","వంటకం","అందం","ఫ్యాషన్",
    "accident road","fire broke","flood","earthquake","weather",
]

def is_political(title, description=""):
    text = (title + " " + (description or "")).lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in text:
            return False
    for kw in POLITICAL_KEYWORDS:
        if kw.lower() in text:
            return True
    return False

# ─────────────────────────────────────────
# PARTY SENTIMENT CLASSIFICATION
# ─────────────────────────────────────────
def classify_party(title, description=""):
    text = (title + " " + (description or "")).lower()

    has_ysrcp = any(k in text for k in [
        "jagan","ysrcp","ysr congress","జగన్","వైఎస్ఆర్సీపీ",
        "విపక్షం","opposition leader","former cm jagan"
    ])
    has_tdp = any(k in text for k in [
        "chandrababu","tdp","telugu desam","naidu","lokesh","pawan kalyan",
        "janasena","చంద్రబాబు","టీడీపీ","లోకేశ్","పవన్","జనసేన",
        "ruling government","ap government","cm naidu"
    ])

    if has_ysrcp and has_tdp:
        return {"party": "Both", "sentiment": "Neutral"}
    elif has_ysrcp:
        return {"party": "YSRCP", "sentiment": "Neutral"}
    elif has_tdp:
        return {"party": "TDP/Alliance", "sentiment": "Neutral"}
    return {"party": "None", "sentiment": "Neutral"}

# ─────────────────────────────────────────
# PARSE PUBLISH DATE FROM RSS ITEM
# ─────────────────────────────────────────
def parse_pub_date(pub_date_str):
    """Parse RSS pubDate to IST datetime"""
    if not pub_date_str:
        return now_ist()
    try:
        # Try common RSS date formats
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(pub_date_str.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(IST)
            except:
                continue
    except:
        pass
    return now_ist()

# ─────────────────────────────────────────
# SCRAPERS WITH ACTUAL PUBLISH DATES
# ─────────────────────────────────────────
def scrape_rss_with_dates(rss_url, source_name):
    """Scrape RSS feed and get actual publish dates"""
    articles = []
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item") or soup.find_all("entry")

        now = now_ist()
        cutoff = now - timedelta(hours=24)

        for item in items[:30]:
            title_tag = item.find("title")
            link_tag = item.find("link")
            pub_tag = item.find("pubDate") or item.find("published") or item.find("updated")

            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            if len(title) < 15:
                continue

            # Get actual publish date
            pub_date = parse_pub_date(pub_tag.get_text(strip=True) if pub_tag else None)

            # Skip if older than 24 hours
            if pub_date < cutoff:
                continue

            # Political filter
            if not is_political(title):
                continue

            link = ""
            if link_tag:
                link = link_tag.get_text(strip=True) or link_tag.get("href", "")

            party_info = classify_party(title)

            articles.append({
                "title": title,
                "url": link,
                "source": source_name,
                "published_at": format_ist(pub_date),       # actual article publish time
                "published_display": pub_date.strftime("%d %b %Y, %I:%M %p IST"),
                "scraped_at": now_ist_str(),
                **party_info
            })

        print(f"  {source_name}: {len(articles)} political articles (last 24h)")
    except Exception as e:
        print(f"  {source_name} RSS failed: {e}")
    return articles


def scrape_page_with_dates(url, source_name):
    """Scrape HTML page — use scraped_at as published_at since no date on page"""
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        seen = set()
        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h3") or a_tag.find("h2") or a_tag.find("h4")
            if not h:
                continue
            title = h.get_text(strip=True)
            if len(title) < 15 or title in seen:
                continue
            seen.add(title)

            href = a_tag["href"]
            if not href.startswith("http"):
                base = "/".join(url.split("/")[:3])
                href = base + href

            if not is_political(title):
                continue

            # For HTML scraped pages, try to find date in URL or nearby elements
            # Eenadu URLs contain date in article ID, Sakshi has dates near articles
            pub_date = now_ist()  # default to now

            party_info = classify_party(title)

            articles.append({
                "title": title,
                "url": href,
                "source": source_name,
                "published_at": format_ist(pub_date),
                "published_display": pub_date.strftime("%d %b %Y, %I:%M %p IST"),
                "scraped_at": now_ist_str(),
                **party_info
            })

            if len(articles) >= 15:
                break

        print(f"  {source_name}: {len(articles)} political articles")
    except Exception as e:
        print(f"  {source_name} failed: {e}")
    return articles


# ─────────────────────────────────────────
# ALL SOURCES
# ─────────────────────────────────────────
def crawl_all():
    print(f"\n[{now_ist().strftime('%d %b %H:%M:%S IST')}] Crawling AP political news (last 24h)...")
    all_articles = []

    # RSS sources (have actual publish dates)
    all_articles.extend(scrape_rss_with_dates("https://tv9telugu.com/feed", "TV9 Telugu"))
    all_articles.extend(scrape_rss_with_dates("https://ntvtelugu.com/feed", "NTV Telugu"))
    all_articles.extend(scrape_rss_with_dates("https://10tv.in/feed", "10TV"))

    # HTML scrape sources (no RSS dates but fresh content)
    all_articles.extend(scrape_page_with_dates("https://www.eenadu.net/andhra-pradesh", "Eenadu"))
    all_articles.extend(scrape_page_with_dates("https://www.andhrajyothy.com/andhra-pradesh", "Andhra Jyothi"))
    all_articles.extend(scrape_page_with_dates("https://www.sakshi.com/andhra-pradesh-news", "Sakshi"))

    # Deduplicate
    seen = set()
    unique = []
    for a in all_articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)

    # Sort by published_at (newest first)
    unique.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    cache["articles"] = unique
    cache["last_updated"] = now_ist_str()
    cache["last_updated_display"] = now_ist().strftime("%d %b %Y, %I:%M %p IST")
    cache["status"] = "ok"
    print(f"  Done: {len(unique)} political articles (last 24h)")


def background_crawler():
    while True:
        try:
            crawl_all()
        except Exception as e:
            print(f"Crawl error: {e}")
        time.sleep(15 * 60)


@app.on_event("startup")
async def startup_event():
    thread = threading.Thread(target=background_crawler, daemon=True)
    thread.start()


# ─────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────
@app.get("/")
def root():
    return {
        "name": "NādiPulse Telugu Political News API v3",
        "articles": len(cache["articles"]),
        "last_updated": cache.get("last_updated"),
        "last_updated_display": cache.get("last_updated_display"),
        "status": cache["status"],
        "window": "Last 24 hours"
    }

@app.get("/news")
def get_news(party: str = None, limit: int = 100):
    articles = cache["articles"]
    if party:
        articles = [a for a in articles if party.lower() in (a.get("party") or "").lower()]
    return {
        "count": len(articles[:limit]),
        "last_updated": cache.get("last_updated"),
        "last_updated_display": cache.get("last_updated_display"),
        "articles": articles[:limit]
    }

@app.get("/health")
def health():
    return {
        "status": cache["status"],
        "articles": len(cache["articles"]),
        "last_updated": cache.get("last_updated"),
        "last_updated_display": cache.get("last_updated_display"),
        "window": "Last 24 hours"
    }
