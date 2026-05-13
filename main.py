"""
NādiPulse AP Political News API v6
Enhancements over v5:
1. Sakshi: NewsData.io domain filter + clean title extraction
2. Party official sources: YSRCP (ysrcongress.com) + TDP (telugudesam.org)
3. source_type / source_party / source_bias metadata on every article
4. Viral/reach scoring system
5. Story clustering → /top-stories endpoint
6. /top-stories/summarise endpoint for AI 4-line summaries
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup
import time, threading, hashlib, re, os
from datetime import datetime, timezone, timedelta

app = FastAPI(title="NādiPulse News API v6")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "te-IN,te;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}
NEWSDATA_KEY = "pub_6e4903bc366f46d5b8cbbcc2f9593f9f"
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY", "")

IST = timezone(timedelta(hours=5, minutes=30))
def now_ist(): return datetime.now(IST)
def now_ist_str(): return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
def fmt_ist(dt):
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
def display_ist(dt):
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")

cache = {
    "articles": [], "english": [], "party_official": [],
    "top_stories": [], "last_updated": None,
    "top_stories_updated": None, "status": "starting"
}

# ── AP FILTER ────────────────────────────────────────────────
AP_REQUIRED = [
    "andhra pradesh","andhra","ap government","ap cm","ap assembly",
    "ఆంధ్రప్రదేశ్","ఆంధ్ర",
    "ysrcp","ysr congress","telugu desam","tdp","janasena","jsp",
    "వైఎస్ఆర్సీపీ","టీడీపీ","జనసేన",
    "chandrababu","naidu","nara lokesh","lokesh","pawan kalyan","pawan",
    "jagan","jaganmohan","ys jagan",
    "ambati","sajjala","buggana","botsa","vijayasai","seediri","peddireddy","roja",
    "cbn","cm naidu","cm chandrababu",
    "జగన్","చంద్రబాబు","నాయుడు","లోకేశ్","పవన్","నారా",
    "అంబటి","సజ్జల","బుగ్గన","బొత్స","రోజా","సీడిరి",
    "amaravati","visakhapatnam","vizag","vijayawada","tirupati","guntur",
    "kurnool","nellore","kadapa","anantapur","ongole","rajahmundry",
    "kakinada","eluru","srikakulam","vizianagaram",
    "అమరావతి","విశాఖపట్నం","విజయవాడ","తిరుపతి","గుంటూరు",
    "polavaram","aarogyasri","rythu bharosa",
    "పోలవరం","ఆరోగ్యశ్రీ","రైతు భరోసా",
    "ap high court","rayalaseema","uttarandhra","రాయలసీమ",
]
EXCLUDE_STATES = [
    "tamil nadu","tamilnadu","tvk","vijay actor","palani","dmk","mk stalin",
    "west bengal","bengal","kolkata","mamata","trinamool",
    "assam","himanta","arunachal","nagaland","manipur","meghalaya",
    "karnataka","bengaluru","siddaramaiah","kumaraswamy",
    "maharashtra","mumbai","shinde","fadnavis","baramati","sunetra pawar",
    "gujarat","rajasthan","madhya pradesh","chhattisgarh","jharkhand","odisha",
    "punjab","haryana","uttar pradesh","yogi","bihar","nitish",
    "kerala","pinarayi","telangana","hyderabad","revanth reddy","brs","kcr","ktr",
    "delhi","kejriwal","james cameron","disney","cricket","ipl","football",
    "movie","film release","box office","ott release",
    "তমিলনাড়ু","తమిళనాడు","తమిళ","బెంగాల్","కేరళ","కర్నాటక","మహారాష్ట్ర","తెలంగాణ",
]
EXCLUDE_CONTENT = ["recipe","cooking","fashion","beauty","horoscope","astrology","vastu","రాశిఫలం","వాస్తు"]
POLITICAL_KW = [
    "government","minister","chief minister","assembly","parliament","election",
    "political","party","MLA","MP","CM","cabinet","budget","scheme","welfare",
    "policy","allegation","governance","ruling","opposition","rally","protest","announce",
    "రాజకీయ","ప్రభుత్వ","మంత్రి","అసెంబ్లీ","పార్టీ","ఎమ్మెల్యే","బడ్జెట్",
]
VIRAL_KW = [
    "scam","corruption","arrested","fir","raid","resign","protest","controversy",
    "expose","leaked","allegation","fraud","crore","lakh crore",
    "high court","supreme court","cbi","ed","income tax",
    "అవినీతి","అరెస్ట్","రాజీనామా","నిరసన","కుంభకోణం","ఆరోపణ",
]

def is_political(title, desc="", is_party_official=False):
    text = (title+" "+(desc or "")).lower()
    if any(k.lower() in text for k in EXCLUDE_CONTENT): return False
    if is_party_official: return len(title) > 10
    has_ap = any(k.lower() in text for k in AP_REQUIRED)
    if not has_ap: return False
    other_state = any(k.lower() in text for k in EXCLUDE_STATES)
    if other_state:
        ap_override = any(k in text for k in ["andhra","ysrcp","chandrababu","naidu","jagan","pawan","tdp","amaravati","ఆంధ్ర","జగన్","చంద్రబాబు","పవన్","నాయుడు"])
        if not ap_override: return False
    return any(k.lower() in text for k in POLITICAL_KW) or has_ap

# ── ALIASES / TAGGING ────────────────────────────────────────
LEADER_ALIASES = {
    "chandrababu naidu":"Chandrababu","nara chandrababu":"Chandrababu",
    "n chandrababu":"Chandrababu","chandrababu":"Chandrababu","cbn":"Chandrababu",
    "cm naidu":"Chandrababu","naidu":"Chandrababu","cm chandrababu":"Chandrababu",
    "చంద్రబాబు నాయుడు":"Chandrababu","చంద్రబాబు":"Chandrababu","నాయుడు":"Chandrababu",
    "nara lokesh":"Lokesh","lokesh":"Lokesh","లోకేశ్":"Lokesh","నారా లోకేశ్":"Lokesh",
    "jagan mohan reddy":"Jagan","ys jagan":"Jagan","jagan":"Jagan",
    "జగన్ మోహన్":"Jagan","జగన్":"Jagan",
    "pawan kalyan":"Pawan Kalyan","pawankalyan":"Pawan Kalyan","pawan":"Pawan Kalyan",
    "పవన్ కల్యాణ్":"Pawan Kalyan","పవన్":"Pawan Kalyan",
    "ambati rambabu":"Ambati Rambabu","ambati":"Ambati Rambabu","అంబటి":"Ambati Rambabu",
    "sajjala":"Sajjala","సజ్జల":"Sajjala","buggana":"Buggana","బుగ్గన":"Buggana",
    "botsa":"Botsa","బొత్స":"Botsa","vijayasai":"Vijayasai Reddy","విజయసాయి":"Vijayasai Reddy",
    "roja":"Roja","రోజా":"Roja","peddireddy":"Peddireddy","పెద్దిరెడ్డి":"Peddireddy",
}
YSRCP_CHK = ["jagan","ys jagan","ambati","sajjala","buggana","botsa","vijayasai","seediri","peddireddy","roja","జగన్","అంబటి","సజ్జల","ysrcp","ysr congress","వైఎస్ఆర్సీపీ"]
TDP_CHK = ["chandrababu","naidu","nara lokesh","lokesh","cbn","చంద్రబాబు","నాయుడు","లోకేశ్","tdp","telugu desam","టీడీపీ"]
BJP_CHK = ["kishan reddy","bandi sanjay","bjp","ap bjp","బీజేపీ"]
JSP_CHK = ["pawan kalyan","pawan","janasena","jsp","పవన్","జనసేన"]
TOPICS = {
    "Aarogyasri":["aarogyasri","ఆరోగ్యశ్రీ","health scheme"],
    "Amaravati":["amaravati","అమరావతి","capital city","రాజధాని"],
    "Farm Loan":["farm loan","రైతు","agriculture loan","crop loan","rythu"],
    "Fuel Crisis":["petrol","diesel","fuel","పెట్రోల్","డీజిల్","shortage"],
    "Google/IT":["google","data center","it sector","tech park"],
    "Law & Order":["arrest","fir","police","court","హైకోర్టు","supreme court","raid"],
    "Elections":["election","poll","by-poll","ఎన్నిక","campaign","bypoll"],
    "Welfare":["welfare","scheme","pension","పింఛన్","పథకం","beneficiary"],
    "Budget":["budget","funds","నిధులు","బడ్జెట్","revenue"],
    "Education":["school","college","university","students","విద్య"],
    "Corruption":["corruption","scam","fraud","అవినీతి","కుంభకోణం"],
    "Governance":["governance","administration","policy","పాలన","అభివృద్ధి"],
    "Polavaram":["polavaram","పోలవరం","dam"],
    "Land/Property":["land","property","patta","భూమి","land grab","acres"],
    "Opposition":["opposition","counter","slam","criticize","condemn"],
}

def detect_spokesperson(text):
    t = text.lower()
    for alias, name in LEADER_ALIASES.items():
        if alias.lower() in t: return name
    return "None"

def detect_party(text):
    t = text.lower()
    p = []
    if any(k in t for k in YSRCP_CHK): p.append("YSRCP")
    if any(k in t for k in TDP_CHK): p.append("TDP")
    if any(k in t for k in BJP_CHK): p.append("BJP")
    if any(k in t for k in JSP_CHK): p.append("JSP")
    return "/".join(p) if p else "General"

def detect_topic(text):
    t = text.lower()
    for topic, kws in TOPICS.items():
        if any(k.lower() in t for k in kws): return topic
    return "Governance"

def detect_sentiment(text):
    t = text.lower()
    if any(k in t for k in ["attack","criticize","condemn","scam","fraud","failure","corrupt","అవినీతి","విమర్శ","ఆరోపణ","వైఫల్యం"]): return "Negative"
    if any(k in t for k in ["develop","inaugurat","launch","scheme","achieve","అభివృద్ధి","ప్రారంభ","పథకం","విజయ"]): return "Positive"
    return "Neutral"

def viral_score(title, desc, src_count=1):
    text = (title+" "+(desc or "")).lower()
    s = min(40, sum(5 for k in VIRAL_KW if k in text))
    s += min(30, src_count*10)
    prominent = ["jagan","chandrababu","naidu","pawan kalyan","lokesh","జగన్","చంద్రబాబు","పవన్"]
    s += min(20, sum(5 for k in prominent if k in text))
    if desc and len(desc)>100: s += 10
    return min(100, s)

def viral_label(score):
    return "High" if score>=70 else ("Medium" if score>=40 else "Low")

def ahash(title):
    clean = re.sub(r'[^\w\s]','',title.lower().strip())
    return hashlib.md5(clean.encode('utf-8')).hexdigest()[:12]

def tag_article(title, desc="", source_type="news", source_party=None, source_bias=None):
    text = title+" "+(desc or "")
    vs = viral_score(title, desc)
    return {
        "party": detect_party(text),
        "spokesperson": detect_spokesperson(text),
        "topic": detect_topic(text),
        "sentiment": detect_sentiment(text),
        "source_type": source_type,
        "source_party": source_party or "",
        "source_bias": source_bias or "neutral",
        "viral_score": vs,
        "viral_label": viral_label(vs),
        "article_hash": ahash(title),
    }

# ── DATE PARSER ──────────────────────────────────────────────
def parse_pub(s):
    if not s: return now_ist()
    # Clean the string first
    s = s.strip()
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",   # RSS standard: Mon, 11 May 2026 10:44:00 +0530
        "%a, %d %b %Y %H:%M:%S GMT",   # RSS UTC
        "%Y-%m-%dT%H:%M:%S%z",         # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",          # ISO 8601 UTC
        "%Y-%m-%d %H:%M:%S",           # Simple datetime
        "%d-%m-%Y %I:%M %p",           # YSRCP: 11-05-2026 10:44 PM
        "%d-%m-%Y %H:%M:%S",           # YSRCP alternate
        "%d-%m-%Y",                     # Date only
        "%B %d, %Y",                   # May 11, 2026
        "%b %d, %Y",                   # May 11, 2026 short
        "%d %B %Y",                    # 11 May 2026
        "%Y/%m/%d %H:%M:%S",
    ]:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=IST)
            return dt.astimezone(IST)
        except: pass
    return now_ist()

# ── SCRAPERS ─────────────────────────────────────────────────
def scrape_rss(url, source, lang="te", source_type="news", source_party=None, source_bias=None):
    out, seen = [], set()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item") or soup.find_all("entry")
        cutoff = now_ist() - timedelta(hours=24)
        for item in items[:25]:
            try:
                ttag = item.find("title"); ltag = item.find("link")
                ptag = item.find("pubDate") or item.find("published")
                dtag = item.find("description") or item.find("summary")
                if not ttag: continue
                title = ttag.get_text(strip=True)
                if len(title) < 15: continue
                h = ahash(title)
                if h in seen: continue
                seen.add(h)
                desc = BeautifulSoup(dtag.get_text(), "html.parser").get_text(strip=True)[:200] if dtag else ""
                is_party = source_type == "party_official"
                if not is_political(title, desc, is_party_official=is_party): continue
                pub = parse_pub(ptag.get_text(strip=True) if ptag else None)
                if pub < cutoff: continue
                link = ltag.get_text(strip=True) if ltag else ""
                tags = tag_article(title, desc, source_type, source_party, source_bias)
                out.append({"title":title,"url":link,"source":source,"description":desc[:200],
                    "language":lang,"published_at":fmt_ist(pub),"published_display":display_ist(pub),
                    "scraped_at":now_ist_str(),**tags})
            except: continue
        print(f"  {source}: {len(out)} articles")
    except Exception as e:
        print(f"  RSS {source}: {e}")
    return out

def scrape_html(url, source, base_url, path_filter, source_type="news", source_party=None, source_bias=None):
    out, seen = [], set()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            try:
                h_tag = a.find(["h2","h3","h4"])
                if not h_tag: continue
                title = h_tag.get_text(strip=True)
                if len(title)<15 or title in seen: continue
                seen.add(title)
                href = a["href"]
                if not href.startswith("http"): href = base_url+href
                if path_filter and path_filter not in href: continue
                if not is_political(title): continue
                p = a.find("p") or a.find_next_sibling("p")
                desc = " ".join(p.get_text(strip=True).split())[:200] if p else ""
                tags = tag_article(title, desc, source_type, source_party, source_bias)
                out.append({"title":title,"url":href,"source":source,"description":desc,
                    "language":"te","published_at":now_ist_str(),"published_display":display_ist(now_ist()),
                    "scraped_at":now_ist_str(),**tags})
                if len(out)>=15: break
            except: continue
        print(f"  {source}: {len(out)} articles")
    except Exception as e:
        print(f"  HTML {source}: {e}")
    return out

# ── SAKSHI via NewsData.io ────────────────────────────────────
# Sakshi.com returns HTTP 403 for all direct server requests.
# NewsData.io has Sakshi indexed via their crawler.
# We use domainurl filter to get Sakshi articles specifically.
def scrape_sakshi():
    out, seen = [], set()
    now = now_ist(); cutoff = now - timedelta(hours=24)
    apis = [
        f"https://newsdata.io/api/1/news?apikey={NEWSDATA_KEY}&domainurl=sakshi.com&language=te&size=10",
        f"https://newsdata.io/api/1/news?apikey={NEWSDATA_KEY}&domainurl=sakshi.com&country=in&size=10",
    ]
    for api_url in apis:
        try:
            r = requests.get(api_url, timeout=15)
            d = r.json()
            if d.get("status") != "success":
                print(f"  Sakshi NewsData: {d.get('message','unknown error')}")
                continue
            for item in d.get("results",[]):
                try:
                    # TITLE: Take first sentence only to avoid body bleeding into title
                    raw = (item.get("title") or "").strip()
                    title = re.split(r'\.\s+[A-Z\u0c00-\u0c7f]', raw)[0].strip()[:150]
                    if len(title)<15 or title in seen: continue
                    seen.add(title)
                    desc = (item.get("description") or "").strip()[:200]
                    link = item.get("link") or ""
                    pub = parse_pub(item.get("pubDate") or "")
                    if pub < cutoff: continue
                    if not is_political(title, desc): continue
                    tags = tag_article(title, desc, "news", None, "pro_ysrcp")
                    out.append({"title":title,"url":link,"source":"Sakshi","description":desc,
                        "language":"te","published_at":fmt_ist(pub),"published_display":display_ist(pub),
                        "scraped_at":now_ist_str(),**tags})
                except Exception as e:
                    continue
            if out: print(f"  Sakshi (NewsData): {len(out)} articles"); break
        except Exception as e:
            print(f"  Sakshi error: {e}")
    if not out: print("  Sakshi: 0 articles")
    return out

# ── YSRCP OFFICIAL ───────────────────────────────────────────
def scrape_ysrcp_official():
    out, seen = [], set()
    try:
        r = requests.get("https://www.ysrcongress.com/english/news", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        cutoff = now_ist() - timedelta(hours=48)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/top-stories/" not in href and "/en/news/" not in href: continue
            if not href.startswith("http"): href = "https://www.ysrcongress.com"+href
            em = a.find("em")
            title = (em.get_text(strip=True) if em else a.get_text(strip=True))
            title = " ".join(title.split())[:150]
            if len(title)<15 or title in seen: continue
            seen.add(title)
            parent = a.parent
            desc = ""
            if parent:
                full = parent.get_text(separator=" ", strip=True)
                desc = full.replace(title,"").strip()[:200]
            date_text = ""
            if parent:
                ptext = parent.get_text()
                # Try full datetime first: "11-05-2026 10:44 PM"
                dm = re.findall(r'\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}\s*[AP]M', ptext)
                if not dm:
                    # Try date only: "11-05-2026"
                    dm = re.findall(r'\d{2}-\d{2}-\d{4}', ptext)
                date_text = dm[0] if dm else ""
            pub = parse_pub(date_text) if date_text else now_ist()
            if pub < cutoff: continue
            tags = tag_article(title, desc, "party_official", "YSRCP", "pro_ysrcp")
            out.append({"title":title,"url":href,"source":"YSRCP Official","description":desc,
                "language":"en","published_at":fmt_ist(pub),"published_display":display_ist(pub),
                "scraped_at":now_ist_str(),**tags})
            if len(out)>=15: break
        print(f"  YSRCP Official: {len(out)} articles")
    except Exception as e:
        print(f"  YSRCP Official error: {e}")
    return out

# ── TDP OFFICIAL ─────────────────────────────────────────────
def scrape_tdp_official():
    out, seen = [], set()
    try:
        r = requests.get("https://www.telugudesam.org/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        cutoff = now_ist() - timedelta(hours=48)
        arts = soup.find_all(["article","div"], class_=re.compile(r'post|entry|article|news-item', re.I))
        for art in arts[:20]:
            try:
                tel = art.find(["h1","h2","h3","h4"])
                if not tel: continue
                a = tel.find("a") or art.find("a", href=True)
                if not a: continue
                title = " ".join(tel.get_text(strip=True).split())[:150]
                if len(title)<15 or title in seen: continue
                seen.add(title)
                href = a.get("href","")
                if not href.startswith("http"): href = "https://www.telugudesam.org"+href
                exc = art.find(class_=re.compile(r'excerpt|summary|content', re.I))
                desc = exc.get_text(strip=True)[:200] if exc else ""
                date_el = art.find(["time","span"], class_=re.compile(r'date|time|publish', re.I))
                date_text = (date_el.get("datetime","") or date_el.get_text(strip=True)) if date_el else ""
                pub = parse_pub(date_text) if date_text else now_ist()
                if pub < cutoff: continue
                tags = tag_article(title, desc, "party_official", "TDP", "pro_tdp")
                out.append({"title":title,"url":href,"source":"TDP Official","description":desc,
                    "language":"te","published_at":fmt_ist(pub),"published_display":display_ist(pub),
                    "scraped_at":now_ist_str(),**tags})
            except: continue
        print(f"  TDP Official: {len(out)} articles")
    except Exception as e:
        print(f"  TDP Official error: {e}")
    return out

# ── SOURCES ──────────────────────────────────────────────────
TELUGU_RSS = [
    ("https://tv9telugu.com/feed","TV9 Telugu","te","news",None,"neutral"),
    ("https://ntvtelugu.com/feed","NTV Telugu","te","news",None,"neutral"),
    ("https://10tv.in/feed","10TV","te","news",None,"neutral"),
    ("https://www.andhrajyothy.com/feed","Andhra Jyothi","te","news",None,"pro_tdp"),
]
TELUGU_HTML = [
    ("https://www.eenadu.net/andhra-pradesh","Eenadu","https://www.eenadu.net","/telugu-news/","news",None,"pro_tdp"),
]
# NOTE: Most English RSS feeds block Render.com server IPs (Cloudflare WAF).
# English media news is fetched CLIENT-SIDE via rss2json browser proxy.
# Backend only keeps sources known to work from server IPs.
ENGLISH_RSS = [
    # These are fetched server-side but most return 403 from Render.com
    # Kept here for compatibility - scrape_rss handles 403 gracefully
]
# English content comes primarily from:
# 1. YSRCP Official website (English press releases)
# 2. Client-side RSS fetching in the browser (rss2json proxy)

def dedup_sort(items):
    seen, out = set(), []
    for a in items:
        h = a.get("article_hash") or ahash(a.get("title",""))
        if h not in seen: seen.add(h); out.append(a)
    return sorted(out, key=lambda x: x.get("published_at",""), reverse=True)

# ── POLITICIAN → PARTY AFFILIATION TABLE ────────────────────
# CANONICAL mapping: politician name → party
# Source bias != politician party. A Sakshi article about a TDP MLA
# does NOT make that MLA YSRCP. This table is the ground truth.
POLITICIAN_PARTY = {
    # YSRCP Leaders
    "jagan": "YSRCP", "ys jagan": "YSRCP", "jaganmohan": "YSRCP",
    "ambati rambabu": "YSRCP", "ambati": "YSRCP",
    "sajjala": "YSRCP", "buggana": "YSRCP", "botsa": "YSRCP",
    "vijayasai reddy": "YSRCP", "vijayasai": "YSRCP",
    "seediri appalaraju": "YSRCP", "seediri": "YSRCP",
    "peddireddy": "YSRCP", "roja": "YSRCP",
    "kakani": "YSRCP", "kakani govardhan": "YSRCP",
    "vangaveeti": "YSRCP", "perni": "YSRCP",
    "వైఎస్ జగన్": "YSRCP", "జగన్": "YSRCP",
    "అంబటి": "YSRCP", "సజ్జల": "YSRCP", "బుగ్గన": "YSRCP",
    # TDP Leaders
    "chandrababu": "TDP", "nara chandrababu": "TDP", "cbn": "TDP",
    "naidu": "TDP", "cm naidu": "TDP", "nara lokesh": "TDP",
    "lokesh": "TDP", "kinjarapu": "TDP", "kollu ravindra": "TDP",
    "devineni": "TDP", "nimmala": "TDP",
    "చంద్రబాబు": "TDP", "నాయుడు": "TDP", "లోకేశ్": "TDP",
    # BJP Leaders
    "kishan reddy": "BJP", "bandi sanjay": "BJP",
    "puranik": "BJP",
    # JSP Leaders
    "pawan kalyan": "JSP", "pawankalyan": "JSP",
    "pawan": "JSP",  # Only when clearly JSP context
    "పవన్ కల్యాణ్": "JSP", "పవన్": "JSP",
    # Known constituency MLAs (extend as needed)
    "gajuwaka mla": "TDP",
    "palla": "TDP", "palla srinivasa rao": "TDP",
    "vamsi krishna": "TDP",
    "kodali nani": "YSRCP", "kodali": "YSRCP",
    "rk roja": "YSRCP",
}

def resolve_politician_party(text):
    """
    Resolve political party from text using canonical politician-party table.
    NEVER infer party from source bias.
    Returns list of verified parties found in text.
    """
    t = text.lower()
    found_parties = set()
    for name, party in POLITICIAN_PARTY.items():
        if name in t:
            found_parties.add(party)
    # Direct party name mentions (when no specific leader)
    if "ysrcp" in t or "ysr congress" in t or "వైఎస్ఆర్సీపీ" in t:
        found_parties.add("YSRCP")
    if " tdp " in t or "telugu desam" in t or "టీడీపీ" in t:
        found_parties.add("TDP")
    if " bjp" in t or "bharatiya janata" in t or "బీజేపీ" in t:
        found_parties.add("BJP")
    if "janasena" in t or " jsp " in t or "జనసేన" in t:
        found_parties.add("JSP")
    return list(found_parties) if found_parties else ["General"]

# ── CATEGORY ISOLATION ───────────────────────────────────────
# Prevent entertainment/sports/lifestyle from entering political clusters
POLITICAL_CATEGORIES = {"Governance","Amaravati","Farm Loan","Fuel Crisis",
    "Google/IT","Law & Order","Elections","Welfare","Budget",
    "Education","Corruption","Polavaram","Land/Property","Opposition","Aarogyasri"}

NON_POLITICAL_SIGNALS = [
    "movie","film","actor","actress","director","cinema","ott","trailer","song",
    "cricket","ipl","football","match","tournament","sports",
    "recipe","fashion","beauty","horoscope","astrology",
    "death","accident","fire","flood","earthquake",  # unless politically relevant
    "celebrity","hero","heroine","నటుడు","నటి","సినిమా","మూవీ",
]

def is_genuinely_political(article):
    """Strict check that article is actual political content."""
    text = (article.get("title","") + " " + article.get("description","")).lower()
    # Reject if non-political signals dominate
    nps = sum(1 for k in NON_POLITICAL_SIGNALS if k in text)
    if nps >= 2: return False
    # Must have political topic or party reference
    topic = article.get("topic","")
    party = article.get("party","General")
    has_political_topic = topic in POLITICAL_CATEGORIES
    has_party = party != "General"
    has_political_kw = any(k in text for k in [
        "government","minister","mla","mp","assembly","election","scheme","policy",
        "ప్రభుత్వ","మంత్రి","ఎమ్మెల్యే","అసెంబ్లీ","ఎన్నిక","పార్టీ"
    ])
    return has_political_topic or has_party or has_political_kw

# ── NAMED ENTITY EXTRACTION ──────────────────────────────────
def extract_named_entities(text):
    """
    Extract key named entities: politicians, locations, organisations.
    Returns set of canonical lowercased entity strings.
    """
    entities = set()
    t = text.lower()
    # Politician names from our table
    for name in POLITICIAN_PARTY:
        if name in t:
            entities.add(name)
    # Known AP constituencies / locations
    ap_locations = [
        "gajuwaka","visakhapatnam","vizag","vijayawada","amaravati","tirupati",
        "guntur","kurnool","nellore","kadapa","anantapur","ongole","rajahmundry",
        "kakinada","eluru","srikakulam","vizianagaram","rayalaseema","uttarandhra",
        "polavaram","yarada","rushikonda","bheemunipatnam","narsipatnam","tadipatri",
        "గాజువాక","విశాఖపట్నం","విజయవాడ","అమరావతి","తిరుపతి","గుంటూరు",
    ]
    for loc in ap_locations:
        if loc in t:
            entities.add(loc)
    # Organisations
    for org in ["ysrcp","tdp","bjp","jsp","janasena","high court","supreme court",
                "cbi","ed","rti","nabard","wdra"]:
        if org in t:
            entities.add(org)
    return entities

# ── MULTI-STAGE CLUSTERING (replaces simple Jaccard) ─────────
# Stage 1: Category isolation  — articles must be political
# Stage 2: Topic match — must share same broad topic
# Stage 3: Named entity overlap — must share politicians/locations
# Stage 4: Semantic keyword overlap — strong Jaccard threshold
# Stage 5: Source integrity — each source entry ties to exact article

STOP_WORDS = {
    "and","the","of","in","to","a","is","are","was","for","on","at","by","an","or",
    "that","this","it","be","as","with","from","but","not","have","has","said","says",
    "will","would","could","should","also","says","said","over","into","after","about",
    "who","what","when","where","how","which","their","they","them","its","has","been",
    "ఆ","ఈ","ఇది","కి","కు","ను","లో","పై","తో","మరియు","అని","గా","కాని","వారు","ఈ",
}

def extract_keywords_strict(text):
    """Extract significant nouns/terms — longer words, no stop words."""
    words = re.findall(r'\b\w{5,}\b', text.lower())  # min 5 chars (stricter)
    return {w for w in words if w not in STOP_WORDS}

def compute_article_similarity(a1, a2):
    """
    Multi-factor similarity score between two articles.
    Returns (score 0.0-1.0, reasons list).
    Higher = more similar.
    """
    reasons = []
    score = 0.0

    t1 = (a1.get("title","") + " " + a1.get("description","")).lower()
    t2 = (a2.get("title","") + " " + a2.get("description","")).lower()

    # STAGE 2: Topic alignment (must match or be closely related)
    topic1, topic2 = a1.get("topic",""), a2.get("topic","")
    if topic1 and topic2:
        if topic1 == topic2:
            score += 0.30
            reasons.append(f"same_topic:{topic1}")
        elif {topic1,topic2} <= {"Governance","Opposition"}:
            score += 0.10  # Related broad topics, small bonus only

    # STAGE 3: Named entity overlap (most important factor)
    e1 = extract_named_entities(t1)
    e2 = extract_named_entities(t2)
    if e1 and e2:
        entity_overlap = e1 & e2
        if entity_overlap:
            entity_score = min(0.40, len(entity_overlap) * 0.15)
            score += entity_score
            reasons.append(f"entity_overlap:{sorted(entity_overlap)}")
        elif not entity_overlap and (e1 or e2):
            # Different entities mentioned = likely different stories
            score -= 0.15
            reasons.append("entity_mismatch")

    # STAGE 4: Strict keyword Jaccard (threshold raised to 0.30)
    k1 = extract_keywords_strict(t1)
    k2 = extract_keywords_strict(t2)
    if k1 and k2:
        inter = len(k1 & k2)
        union = len(k1 | k2)
        jaccard = inter / union if union else 0.0
        if jaccard >= 0.30:
            score += jaccard * 0.30  # Up to 0.30 bonus
            reasons.append(f"keyword_jaccard:{jaccard:.2f}")
        elif jaccard >= 0.15:
            score += jaccard * 0.10  # Small bonus for partial overlap

    # STAGE 5: Party consistency check
    # Articles about completely different parties should not cluster
    p1 = set(resolve_politician_party(t1))
    p2 = set(resolve_politician_party(t2))
    p1.discard("General"); p2.discard("General")
    if p1 and p2 and not (p1 & p2):
        # Different parties, no overlap
        score -= 0.10
        reasons.append(f"party_mismatch:{p1}vs{p2}")

    return max(0.0, score), reasons

# Minimum similarity threshold to join a cluster
CLUSTER_SIMILARITY_THRESHOLD = 0.45
# Minimum cluster confidence to appear in Top Stories
MIN_CLUSTER_CONFIDENCE = 0.40
# Minimum unique sources to appear in Top Stories
MIN_UNIQUE_SOURCES = 2

def cluster_articles_strict(articles):
    """
    Multi-stage clustering with strict validation.
    Returns list of clusters, each with confidence metadata.
    """
    # Pre-filter: only genuinely political articles
    political_arts = [a for a in articles if is_genuinely_political(a)]
    non_political_count = len(articles) - len(political_arts)
    if non_political_count > 0:
        print(f"  Clustering: filtered out {non_political_count} non-political articles")

    groups = []
    used = set()

    for i, seed in enumerate(political_arts):
        if i in used:
            continue
        cluster = [seed]
        used.add(i)
        cluster_scores = []

        for j, candidate in enumerate(political_arts):
            if j in used or j == i:
                continue
            score, reasons = compute_article_similarity(seed, candidate)
            if score >= CLUSTER_SIMILARITY_THRESHOLD:
                cluster.append(candidate)
                cluster_scores.append(score)
                used.add(j)

        # Cluster confidence = average similarity score of members
        confidence = (sum(cluster_scores) / len(cluster_scores)) if cluster_scores else 0.8
        groups.append({
            "articles": cluster,
            "confidence": confidence,
            "size": len(cluster),
        })

    return groups

def build_top_stories(all_arts):
    """
    Build Top Stories with strict validation.
    Each source entry preserves the EXACT article URL it came from.
    """
    groups = cluster_articles_strict(all_arts)
    stories = []

    for group in groups:
        cluster = group["articles"]
        confidence = group["confidence"]
        if not cluster:
            continue

        # Minimum quality gates
        # IMPORTANT: Single-source party official clusters should not dominate Top Stories
        # Build source map FIRST with exact article references
        # key = source name, value = {url, headline, article_hash}
        sources_map = {}
        for art in cluster:
            src_name = art.get("source","")
            if not src_name:
                continue
            art_url = art.get("url","")
            art_title = art.get("title","")
            art_hash = art.get("article_hash","")
            if src_name not in sources_map:
                # First article from this source = authoritative entry
                sources_map[src_name] = {
                    "name": src_name,
                    "url": art_url,          # EXACT article URL
                    "headline": art_title,   # EXACT article headline
                    "hash": art_hash,
                }

        unique_src_count = len(sources_map)

        # Skip clusters that don't meet minimum quality
        # Party official single-source articles should NOT appear in Top Stories
        # They belong in the party feed, not as "top stories"
        is_party_only = all(a.get("source_type") == "party_official" for a in cluster)
        if is_party_only and unique_src_count < 2:
            continue  # Party-only single-source: skip from Top Stories
        if unique_src_count < MIN_UNIQUE_SOURCES and confidence < 0.75:
            continue  # Single-source stories only shown if very high confidence
        if confidence < MIN_CLUSTER_CONFIDENCE:
            continue  # Low confidence clusters never shown

        # Best headline: prefer English, then longest
        english_arts = [a for a in cluster if a.get("language","") == "en"]
        best = (max(english_arts, key=lambda a: len(a.get("title","")))
                if english_arts else max(cluster, key=lambda a: len(a.get("title",""))))
        headline = best.get("title","")

        # Party: use resolved politician party, NOT source bias
        all_text = " ".join(a.get("title","")+" "+a.get("description","") for a in cluster)
        verified_parties = resolve_politician_party(all_text)
        party_str = "/".join(p for p in verified_parties if p != "General") or "General"

        # Spokesperson: only if consistently mentioned across articles
        spokesperson_counts = {}
        for art in cluster:
            sp = art.get("spokesperson","None")
            if sp and sp != "None":
                spokesperson_counts[sp] = spokesperson_counts.get(sp,0) + 1
        # Only include spokesperson if mentioned in ≥2 articles or majority
        top_spokesperson = "None"
        if spokesperson_counts:
            top_sp, top_count = max(spokesperson_counts.items(), key=lambda x: x[1])
            if top_count >= 2 or (len(cluster) == 1):
                top_spokesperson = top_sp

        # Topic from cluster majority
        topic_counts = {}
        for art in cluster:
            t = art.get("topic","Governance")
            topic_counts[t] = topic_counts.get(t,0) + 1
        topic = max(topic_counts, key=topic_counts.get)

        # Viral/reach scoring
        base_viral = max(a.get("viral_score",0) for a in cluster)
        cov_count = len(cluster)
        cov_boost = min(25, cov_count * 5)
        src_boost = min(20, unique_src_count * 6)
        # Cross-ecosystem bonus
        ysrcp_srcs = {"Sakshi","YSRCP Official"}
        tdp_srcs = {"Eenadu","Andhra Jyothi","TDP Official","Eenadu AP"}
        neutral_srcs = {"NDTV","The Hindu","Indian Express","Times of India","Hindustan Times"}
        src_names = set(sources_map.keys())
        eco_bonus = 15 if ((src_names & ysrcp_srcs) and (src_names & tdp_srcs)) else 0
        neutral_bonus = 10 if src_names & neutral_srcs else 0
        confidence_bonus = int(confidence * 10)
        reach = min(100, base_viral + cov_boost + src_boost + eco_bonus + neutral_bonus + confidence_bonus)
        v_lbl = "High" if reach >= 70 else ("Medium" if reach >= 40 else "Low")

        # Trend duration
        long_topics = {"Amaravati","Polavaram","Elections","Corruption","Farm Loan"}
        if reach >= 70 or topic in long_topics:
            trend = "2-3 days"
        elif reach >= 40 or unique_src_count >= 3:
            trend = "1 day"
        elif cov_count >= 2:
            trend = "few hours"
        else:
            trend = "hours"

        # Coverage type
        parties_in_cluster = set()
        for vp in verified_parties:
            if vp != "General": parties_in_cluster.add(vp)
        if len(parties_in_cluster) >= 2:
            cov_type = "multi_directional"
        elif unique_src_count >= 3:
            cov_type = "wide_coverage"
        else:
            cov_type = "one_directional"

        latest = max(cluster, key=lambda a: a.get("published_at",""))

        stories.append({
            "headline": headline,
            "topic": topic,
            "party": party_str,
            "spokesperson": top_spokesperson,
            "coverage_count": cov_count,
            "unique_source_count": unique_src_count,
            "reach_score": reach,
            "viral_score": v_lbl,
            "trend_duration": trend,
            "coverage_type": cov_type,
            "cluster_confidence": round(confidence, 2),
            "published_at": latest.get("published_at",""),
            # STRICT source list: each entry has exact article URL + headline
            "sources": list(sources_map.values()),
            "summary": "",
        })

    # Sort by reach_score desc then coverage_count
    stories.sort(key=lambda s: (s["reach_score"], s["coverage_count"]), reverse=True)
    return stories[:10]

# ── CRAWL LOOP ───────────────────────────────────────────────
def crawl():
    print(f"\n[{now_ist().strftime('%d %b %H:%M IST')}] Crawling all AP political sources...")
    te, en, party = [], [], []
    for url,src,lang,stype,sparty,sbias in TELUGU_RSS:
        te.extend(scrape_rss(url,src,lang,stype,sparty,sbias)); time.sleep(0.5)
    te.extend(scrape_sakshi()); time.sleep(1)
    for url,src,base,filt,stype,sparty,sbias in TELUGU_HTML:
        te.extend(scrape_html(url,src,base,filt,stype,sparty,sbias)); time.sleep(1)
    for url,src,lang,stype,sparty,sbias in ENGLISH_RSS:
        en.extend(scrape_rss(url,src,lang,stype,sparty,sbias)); time.sleep(0.5)
    party.extend(scrape_ysrcp_official()); time.sleep(1)
    party.extend(scrape_tdp_official()); time.sleep(1)
    cache["articles"] = dedup_sort(te)
    cache["english"] = dedup_sort(en)
    cache["party_official"] = dedup_sort(party)
    cache["last_updated"] = now_ist_str()
    cache["status"] = "ok"
    all_for_stories = dedup_sort(te+en+party)
    cache["top_stories"] = build_top_stories(all_for_stories)
    cache["top_stories_updated"] = now_ist_str()
    print(f"  Done: {len(cache['articles'])} Telugu + {len(cache['english'])} English + {len(cache['party_official'])} Party Official")
    print(f"  Top Stories: {len(cache['top_stories'])} clusters")

def bg_crawl():
    while True:
        try: crawl()
        except Exception as e: print(f"Crawl error: {e}")
        time.sleep(15*60)

@app.on_event("startup")
async def startup():
    threading.Thread(target=bg_crawl, daemon=True).start()

# ── ENDPOINTS ────────────────────────────────────────────────
@app.get("/")
def root():
    return {"name":"NādiPulse News API v6","telugu":len(cache["articles"]),
            "english":len(cache["english"]),"party_official":len(cache["party_official"]),
            "top_stories":len(cache["top_stories"]),"last_updated":cache.get("last_updated"),"status":cache["status"]}

@app.get("/news")
def news(party:str=None, limit:int=100):
    arts = cache["articles"]
    if party: arts = [a for a in arts if party.lower() in a.get("party","").lower()]
    return {"count":len(arts[:limit]),"last_updated":cache.get("last_updated"),"articles":arts[:limit]}

@app.get("/english")
def english(party:str=None, limit:int=100):
    arts = cache["english"]
    if party: arts = [a for a in arts if party.lower() in a.get("party","").lower()]
    return {"count":len(arts[:limit]),"last_updated":cache.get("last_updated"),"articles":arts[:limit]}

@app.get("/party-official")
def party_official(party:str=None, limit:int=50):
    arts = cache["party_official"]
    if party: arts = [a for a in arts if party.lower() in a.get("source_party","").lower()]
    return {"count":len(arts[:limit]),"last_updated":cache.get("last_updated"),"articles":arts[:limit]}

@app.get("/all")
def all_news(limit:int=200):
    combined = dedup_sort(cache["articles"]+cache["english"]+cache["party_official"])
    return {"count":len(combined[:limit]),"last_updated":cache.get("last_updated"),"articles":combined[:limit]}

@app.get("/top-stories")
def top_stories():
    return {"count":len(cache["top_stories"]),"last_updated":cache.get("top_stories_updated"),
            "stories":cache["top_stories"]}

@app.get("/health")
@app.head("/health")
def health():
    return {"status":cache["status"],"telugu":len(cache["articles"]),
            "english":len(cache["english"]),"party_official":len(cache["party_official"]),
            "top_stories":len(cache["top_stories"]),"last_updated":cache.get("last_updated")}

# ── AI ENDPOINTS ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior AP political intelligence analyst for YSRCP party leadership.
CRITICAL RULES:
1. ONLY use information from the articles provided. Do NOT use any outside knowledge.
2. If not in articles, say "Not found in today's coverage".
3. All output MUST be in ENGLISH only.
4. Telugu articles labeled [Telugu] — translate before analysis.
5. Chandrababu = Naidu = CBN = CM Naidu — SAME person.
6. Always cite source names. Be factual and concise."""

def call_groq(prompt, system=SYSTEM_PROMPT, max_tokens=1200):
    for model in ["llama-3.3-70b-versatile","llama-3.1-8b-instant","mixtral-8x7b-32768"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
                json={"model":model,"messages":[{"role":"system","content":system},
                      {"role":"user","content":prompt}],"max_tokens":max_tokens,"temperature":0.3},
                timeout=30
            )
            d = r.json()
            if "error" in d: print(f"Groq {model}: {d['error']}"); continue
            if "choices" not in d: print(f"Groq {model} bad response"); continue
            print(f"Groq success: {model}")
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Groq {model}: {e}"); continue
    return None

@app.post("/analyse")
async def analyse(request: Request):
    try:
        body = await request.json()
        prompt = body.get("prompt",""); system = body.get("system", SYSTEM_PROMPT)
        max_tokens = body.get("max_tokens",1200)
        if not prompt: return JSONResponse({"error":"No prompt"}, status_code=400)
        if GROQ_KEY:
            text = call_groq(prompt, system, max_tokens)
            if text: return JSONResponse({"text":text,"model":"groq"})
        if CLAUDE_KEY:
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":CLAUDE_KEY,"anthropic-version":"2023-06-01","Content-Type":"application/json"},
                json={"model":"claude-haiku-4-5-20251001","max_tokens":max_tokens,"system":system,
                      "messages":[{"role":"user","content":prompt}]}, timeout=30)
            d = r.json()
            return JSONResponse({"text":d["content"][0]["text"],"model":"claude-haiku"})
        return JSONResponse({"error":"No AI key configured"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error":str(e)}, status_code=500)

@app.post("/top-stories/summarise")
async def summarise_story(request: Request):
    """Generate 4-line AI summary for a top story cluster."""
    try:
        body = await request.json()
        headline = body.get("headline","")
        sources = body.get("sources",[])
        context = body.get("articles_context","")
        if not headline: return JSONResponse({"error":"No headline"}, status_code=400)
        prompt = f"""Summarize this AP political news story in exactly 4 lines:

Story: "{headline}"
Covered by: {', '.join(s.get('name','') for s in sources)}

Context:
{context[:1500]}

Write exactly 4 lines (no headers, no bullets):
Line 1: What factually happened (cite source)
Line 2: Whether coverage is one-directional, multi-directional, or conflicting
Line 3: Political/media angle (which party benefits or loses)
Line 4: Estimated trend duration (few hours/1 day/2-3 days/long-cycle) and reason

English only. Concise."""
        if GROQ_KEY:
            text = call_groq(prompt, SYSTEM_PROMPT, 300)
            if text: return JSONResponse({"summary":text})
        return JSONResponse({"summary":"AI summary unavailable. Check GROQ_API_KEY."})
    except Exception as e:
        return JSONResponse({"error":str(e)}, status_code=500)
