"""
NādiPulse Telugu News API v2
- Political articles only (no sports, film, crime)
- IST timestamps
- Sentiment-based party classification (not source-based)
- Keep-alive endpoint
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import threading
from datetime import datetime, timezone, timedelta

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
    return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S")

def ist_display():
    return datetime.now(IST).strftime("%d %b %Y %H:%M IST")

# Cache
cache = {"articles": [], "last_updated": None, "status": "starting", "total_crawled": 0}

# ─────────────────────────────────────────
# POLITICAL FILTER — only keep political articles
# ─────────────────────────────────────────
POLITICAL_KEYWORDS = [
    # Telugu political terms
    "రాజకీయ","ప్రభుత్వ","మంత్రి","ముఖ్యమంత్రి","అసెంబ్లీ","పార్లమెంట్",
    "ఎన్నిక","వైఎస్ఆర్సీపీ","టీడీపీ","బీజేపీ","జనసేన","కాంగ్రెస్",
    "జగన్","చంద్రబాబు","పవన్","లోకేశ్","విపక్షం","అధికార",
    "ఎమ్మెల్యే","ఎంపీ","సీఎం","డిప్యూటీ","మంత్రివర్గ","బడ్జెట్",
    "నిధులు","పథకం","సంక్షేమ","విధానం","ఆరోపణ","విమర్శ",
    # English political terms
    "government","minister","chief minister","assembly","parliament",
    "election","YSRCP","TDP","BJP","Janasena","Congress",
    "jagan","chandrababu","pawan","lokesh","opposition","ruling",
    "MLA","MP","CM","deputy","cabinet","budget","scheme","welfare",
    "policy","allegation","criticism","BJP","political","party",
    "vote","constituency","governance","andhra pradesh government",
    "telugu desam","ysr congress","gst","revenue","tax",
]

EXCLUDE_KEYWORDS = [
    # Sports
    "cricket","ipl","football","tennis","match","score","wicket",
    "batting","bowling","stadium","tournament","champion","trophy",
    "ఐపీఎల్","క్రికెట్","మ్యాచ్","స్కోర్","టోర్నమెంట్",
    # Films
    "movie","film","actor","actress","director","cinema","box office",
    "release","trailer","teaser","ott","series","telugu film",
    "సినిమా","మూవీ","హీరో","హీరోయిన్","దర్శకుడు","నటుడు","విడుదల",
    # Accidents/Crime (unless political)
    "accident","road accident","fire","flood","earthquake",
    # Lifestyle
    "recipe","cooking","fashion","beauty","health tips","horoscope",
    "astrology","vastu","marriage","wedding","celebrity couple",
    "రాశిఫలం","వాస్తు","వంటకం","అందం","ఫ్యాషన్",
]

def is_political(title, description=""):
    text = (title + " " + (description or "")).lower()

    # Check exclusions first
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in text:
            return False

    # Must have at least one political keyword
    for kw in POLITICAL_KEYWORDS:
        if kw.lower() in text:
            return True

    return False


# ─────────────────────────────────────────
# SENTIMENT-BASED PARTY CLASSIFICATION
# ─────────────────────────────────────────
def classify_party_sentiment(title, description=""):
    text = (title + " " + (description or "")).lower()

    result = {
        "party": "None",
        "sentiment": "Neutral",
        "classification": "General"
    }

    # YSRCP/Jagan positive signals
    ysrcp_positive = ["జగన్ అభివృద్ధి","jagan development","ysrcp scheme",
                      "jagan good","ysrcp welfare","జగన్ పాలన","వైఎస్ఆర్ పథకం"]
    # YSRCP/Jagan negative signals
    ysrcp_negative = ["జగన్ వైఫల్యం","jagan failure","ysrcp corruption",
                      "jagan scam","జగన్ అవినీతి","జగన్ విఫలం",
                      "విమర్శించారు జగన్","attacks jagan","jagan wrong"]
    # TDP positive signals
    tdp_positive = ["చంద్రబాబు అభివృద్ధి","chandrababu development",
                    "tdp welfare","naidu good","చంద్రబాబు పాలన","tdp scheme"]
    # TDP negative signals
    tdp_negative = ["చంద్రబాబు వైఫల్యం","chandrababu failure","tdp corruption",
                    "naidu scam","చంద్రబాబు అవినీతి","attacks chandrababu",
                    "chandrababu wrong","tdp misrule"]

    # Detect party
    has_ysrcp = any(k in text for k in ["jagan","ysrcp","ysr","జగన్","వైఎస్ఆర్సీపీ","విపక్షం"])
    has_tdp = any(k in text for k in ["chandrababu","tdp","naidu","lokesh","pawan","చంద్రబాబు","టీడీపీ","లోకేశ్","పవన్"])

    if has_ysrcp and has_tdp:
        result["party"] = "Both"
        result["classification"] = "Counter/Debate"
    elif has_ysrcp:
        result["party"] = "YSRCP"
        if any(k in text for k in ysrcp_positive):
            result["sentiment"] = "Positive"
            result["classification"] = "YSRCP Positive"
        elif any(k in text for k in ysrcp_negative):
            result["sentiment"] = "Negative"
            result["classification"] = "YSRCP Negative"
        else:
            result["sentiment"] = "Neutral"
            result["classification"] = "YSRCP Mention"
    elif has_tdp:
        result["party"] = "TDP/Alliance"
        if any(k in text for k in tdp_positive):
            result["sentiment"] = "Positive"
            result["classification"] = "TDP Positive"
        elif any(k in text for k in tdp_negative):
            result["sentiment"] = "Negative"
            result["classification"] = "TDP Negative"
        else:
            result["sentiment"] = "Neutral"
            result["classification"] = "TDP Mention"

    return result


# ─────────────────────────────────────────
# SCRAPERS
# ─────────────────────────────────────────
def scrape_eenadu():
    articles = []
    try:
        resp = requests.get("https://www.eenadu.net/andhra-pradesh", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h3") or a_tag.find("h2")
            if not h: continue
            title = h.get_text(strip=True)
            if len(title) < 15: continue
            url = a_tag["href"]
            if not url.startswith("http"):
                url = "https://www.eenadu.net" + url
            if "/telugu-news/" not in url and "/andhra-pradesh" not in url: continue
            if not is_political(title): continue
            sentiment = classify_party_sentiment(title)
            articles.append({"title": title, "url": url, "source": "Eenadu",
                             "scraped_at": now_ist(), **sentiment})
        print(f"  Eenadu: {len(articles)} political articles")
    except Exception as e:
        print(f"  Eenadu failed: {e}")
    return articles[:15]


def scrape_andhrajyothi():
    articles = []
    try:
        resp = requests.get("https://www.andhrajyothy.com/andhra-pradesh", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h3") or a_tag.find("h2") or a_tag.find("h4")
            if not h: continue
            title = h.get_text(strip=True)
            if len(title) < 15: continue
            url = a_tag["href"]
            if not url.startswith("http"):
                url = "https://www.andhrajyothy.com" + url
            if "/andhra-pradesh/" not in url: continue
            if not is_political(title): continue
            sentiment = classify_party_sentiment(title)
            articles.append({"title": title, "url": url, "source": "Andhra Jyothi",
                             "scraped_at": now_ist(), **sentiment})
        print(f"  AndhraJyothi: {len(articles)} political articles")
    except Exception as e:
        print(f"  AndhraJyothi failed: {e}")
    return articles[:15]


def scrape_sakshi():
    articles = []
    try:
        resp = requests.get("https://www.sakshi.com/andhra-pradesh-news", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h4") or a_tag.find("h3") or a_tag.find("h2")
            if not h: continue
            title = h.get_text(strip=True)
            if len(title) < 15: continue
            url = a_tag["href"]
            if not url.startswith("http"):
                url = "https://www.sakshi.com" + url
            if "/telugu-news/" not in url: continue
            if not is_political(title): continue
            sentiment = classify_party_sentiment(title)
            articles.append({"title": title, "url": url, "source": "Sakshi",
                             "scraped_at": now_ist(), **sentiment})
        print(f"  Sakshi: {len(articles)} political articles")
    except Exception as e:
        print(f"  Sakshi failed: {e}")
    return articles[:15]


def scrape_rss(url, source_name):
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "xml")
        for item in soup.find_all("item")[:20]:
            title_tag = item.find("title")
            link_tag = item.find("link")
            if not title_tag: continue
            title = title_tag.get_text(strip=True)
            link = link_tag.get_text(strip=True) if link_tag else ""
            if not is_political(title): continue
            sentiment = classify_party_sentiment(title)
            articles.append({"title": title, "url": link, "source": source_name,
                             "scraped_at": now_ist(), **sentiment})
        print(f"  {source_name}: {len(articles)} political articles")
    except Exception as e:
        print(f"  {source_name} failed: {e}")
    return articles


# ─────────────────────────────────────────
# MAIN CRAWL
# ─────────────────────────────────────────
def crawl_all():
    print(f"\n[{datetime.now(IST).strftime('%H:%M:%S IST')}] Crawling AP political news...")
    all_articles = []
    all_articles.extend(scrape_eenadu())
    all_articles.extend(scrape_andhrajyothi())
    all_articles.extend(scrape_sakshi())
    all_articles.extend(scrape_rss("https://tv9telugu.com/feed", "TV9 Telugu"))
    all_articles.extend(scrape_rss("https://ntvtelugu.com/feed", "NTV Telugu"))
    all_articles.extend(scrape_rss("https://10tv.in/feed", "10TV"))

    # Deduplicate
    seen = set()
    unique = []
    for a in all_articles:
        if a["title"] not in seen and len(a["title"]) > 10:
            seen.add(a["title"])
            unique.append(a)

    cache["articles"] = unique
    cache["last_updated"] = now_ist()
    cache["last_updated_display"] = ist_display()
    cache["status"] = "ok"
    cache["total_crawled"] = len(unique)
    print(f"  Done: {len(unique)} political articles cached")


def background_crawler():
    while True:
        try:
            crawl_all()
        except Exception as e:
            print(f"Crawl error: {e}")
            cache["status"] = f"error: {e}"
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
        "name": "NādiPulse Telugu Political News API",
        "articles": len(cache["articles"]),
        "last_updated": cache.get("last_updated"),
        "last_updated_display": cache.get("last_updated_display"),
        "status": cache["status"],
    }

@app.get("/news")
def get_news(party: str = None, sentiment: str = None, limit: int = 100):
    articles = cache["articles"]
    if party:
        articles = [a for a in articles if party.lower() in a.get("party","").lower()]
    if sentiment:
        articles = [a for a in articles if sentiment.lower() in a.get("sentiment","").lower()]
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
        "last_updated_display": cache.get("last_updated_display")
    }
