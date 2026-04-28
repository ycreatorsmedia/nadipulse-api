"""
NādiPulse Telugu News API
Scrapes Eenadu, AndhraJyothi, Sakshi every 15 minutes
Serves clean JSON API — deploy free on Render.com
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import threading
from datetime import datetime

app = FastAPI(title="NādiPulse Telugu News API")

# Allow your Vercel site to call this API
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

# In-memory cache
cache = {
    "articles": [],
    "last_updated": None,
    "status": "starting"
}

# ─────────────────────────────────────────
# SCRAPER 1: EENADU
# ─────────────────────────────────────────
def scrape_eenadu():
    articles = []
    try:
        resp = requests.get("https://www.eenadu.net/andhra-pradesh", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all article links with h3 headings
        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h3") or a_tag.find("h2")
            if not h:
                continue
            title = h.get_text(strip=True)
            if len(title) < 15:
                continue
            url = a_tag["href"]
            if not url.startswith("http"):
                url = "https://www.eenadu.net" + url
            if "/telugu-news/" not in url and "/andhra-pradesh" not in url:
                continue

            articles.append({
                "title": title,
                "url": url,
                "source": "Eenadu",
                "bias": "TDP Pro",
                "language": "te",
                "scraped_at": datetime.now().isoformat()
            })

        print(f"  Eenadu: {len(articles)} articles")
    except Exception as e:
        print(f"  Eenadu failed: {e}")
    return articles[:15]


# ─────────────────────────────────────────
# SCRAPER 2: ANDHRA JYOTHI
# ─────────────────────────────────────────
def scrape_andhrajyothi():
    articles = []
    try:
        resp = requests.get("https://www.andhrajyothy.com/andhra-pradesh", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h3") or a_tag.find("h2") or a_tag.find("h4")
            if not h:
                continue
            title = h.get_text(strip=True)
            if len(title) < 15:
                continue
            url = a_tag["href"]
            if not url.startswith("http"):
                url = "https://www.andhrajyothy.com" + url
            if "/andhra-pradesh/" not in url:
                continue

            articles.append({
                "title": title,
                "url": url,
                "source": "Andhra Jyothi",
                "bias": "TDP Pro",
                "language": "te",
                "scraped_at": datetime.now().isoformat()
            })

        print(f"  AndhraJyothi: {len(articles)} articles")
    except Exception as e:
        print(f"  AndhraJyothi failed: {e}")
    return articles[:15]


# ─────────────────────────────────────────
# SCRAPER 3: SAKSHI
# ─────────────────────────────────────────
def scrape_sakshi():
    articles = []
    try:
        resp = requests.get("https://www.sakshi.com/andhra-pradesh-news", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            h = a_tag.find("h4") or a_tag.find("h3") or a_tag.find("h2")
            if not h:
                continue
            title = h.get_text(strip=True)
            if len(title) < 15:
                continue
            url = a_tag["href"]
            if not url.startswith("http"):
                url = "https://www.sakshi.com" + url
            if "/telugu-news/" not in url:
                continue

            articles.append({
                "title": title,
                "url": url,
                "source": "Sakshi",
                "bias": "YSRCP Pro",
                "language": "te",
                "scraped_at": datetime.now().isoformat()
            })

        print(f"  Sakshi: {len(articles)} articles")
    except Exception as e:
        print(f"  Sakshi failed: {e}")
    return articles[:15]


# ─────────────────────────────────────────
# SCRAPER 4: TV9 TELUGU (RSS works)
# ─────────────────────────────────────────
def scrape_tv9():
    articles = []
    try:
        resp = requests.get("https://tv9telugu.com/feed", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "xml")
        for item in soup.find_all("item")[:15]:
            title = item.find("title")
            link = item.find("link")
            if not title: continue
            articles.append({
                "title": title.get_text(strip=True),
                "url": link.get_text(strip=True) if link else "",
                "source": "TV9 Telugu",
                "bias": "Neutral",
                "language": "te",
                "scraped_at": datetime.now().isoformat()
            })
        print(f"  TV9: {len(articles)} articles")
    except Exception as e:
        print(f"  TV9 failed: {e}")
    return articles


# ─────────────────────────────────────────
# SCRAPER 5: NTV (RSS works)
# ─────────────────────────────────────────
def scrape_ntv():
    articles = []
    try:
        resp = requests.get("https://ntvtelugu.com/feed", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "xml")
        for item in soup.find_all("item")[:15]:
            title = item.find("title")
            link = item.find("link")
            if not title: continue
            articles.append({
                "title": title.get_text(strip=True),
                "url": link.get_text(strip=True) if link else "",
                "source": "NTV Telugu",
                "bias": "Neutral",
                "language": "te",
                "scraped_at": datetime.now().isoformat()
            })
        print(f"  NTV: {len(articles)} articles")
    except Exception as e:
        print(f"  NTV failed: {e}")
    return articles


# ─────────────────────────────────────────
# SCRAPER 6: 10TV (RSS works)
# ─────────────────────────────────────────
def scrape_10tv():
    articles = []
    try:
        resp = requests.get("https://10tv.in/feed", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "xml")
        for item in soup.find_all("item")[:15]:
            title = item.find("title")
            link = item.find("link")
            if not title: continue
            articles.append({
                "title": title.get_text(strip=True),
                "url": link.get_text(strip=True) if link else "",
                "source": "10TV",
                "bias": "Neutral",
                "language": "te",
                "scraped_at": datetime.now().isoformat()
            })
        print(f"  10TV: {len(articles)} articles")
    except Exception as e:
        print(f"  10TV failed: {e}")
    return articles


# ─────────────────────────────────────────
# MAIN CRAWL CYCLE
# ─────────────────────────────────────────
def crawl_all():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Crawling all Telugu sources...")
    all_articles = []
    all_articles.extend(scrape_eenadu())
    all_articles.extend(scrape_andhrajyothi())
    all_articles.extend(scrape_sakshi())
    all_articles.extend(scrape_tv9())
    all_articles.extend(scrape_ntv())
    all_articles.extend(scrape_10tv())

    # Deduplicate by title
    seen = set()
    unique = []
    for a in all_articles:
        if a["title"] not in seen and len(a["title"]) > 10:
            seen.add(a["title"])
            unique.append(a)

    cache["articles"] = unique
    cache["last_updated"] = datetime.now().isoformat()
    cache["status"] = "ok"
    print(f"  Done: {len(unique)} unique articles cached")


def background_crawler():
    while True:
        try:
            crawl_all()
        except Exception as e:
            print(f"Crawl error: {e}")
            cache["status"] = f"error: {e}"
        time.sleep(15 * 60)  # 15 minutes


# Start background crawler on startup
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
        "name": "NādiPulse Telugu News API",
        "articles": len(cache["articles"]),
        "last_updated": cache["last_updated"],
        "status": cache["status"],
        "endpoints": ["/news", "/news?source=Sakshi", "/news?bias=YSRCP+Pro", "/health"]
    }

@app.get("/news")
def get_news(source: str = None, bias: str = None, limit: int = 50):
    articles = cache["articles"]
    if source:
        articles = [a for a in articles if source.lower() in a["source"].lower()]
    if bias:
        articles = [a for a in articles if bias.lower() in a["bias"].lower()]
    return {
        "count": len(articles[:limit]),
        "last_updated": cache["last_updated"],
        "articles": articles[:limit]
    }

@app.get("/health")
def health():
    return {"status": cache["status"], "articles": len(cache["articles"]), "last_updated": cache["last_updated"]}
