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
    for fmt in ["%a, %d %b %Y %H:%M:%S %z","%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z","%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%SZ",
                "%d-%m-%Y %I:%M %p","%d-%m-%Y"]:
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
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
                dm = re.findall(r'\d{2}-\d{2}-\d{4}', parent.get_text())
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
ENGLISH_RSS = [
    ("https://feeds.feedburner.com/ndtvnews-india-news","NDTV","en","news",None,"neutral"),
    ("https://www.thehindu.com/news/national/andhra-pradesh/?service=rss","The Hindu","en","news",None,"neutral"),
    ("https://indianexpress.com/feed/","Indian Express","en","news",None,"neutral"),
    ("https://www.deccanchronicle.com/rss_feed/","Deccan Chronicle","en","news",None,"neutral"),
    ("https://www.newindianexpress.com/rss/andhra-pradesh.xml","New Indian Express","en","news",None,"neutral"),
    ("https://timesofindia.indiatimes.com/rssfeeds/296589292.cms","Times of India","en","news",None,"neutral"),
    ("https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml","Hindustan Times","en","news",None,"neutral"),
    ("https://telugu.news18.com/commonfeeds/v1/tel/rss/news.xml","News18 Telugu","en","news",None,"neutral"),
    ("https://www.siasat.com/feed/","Siasat","en","news",None,"neutral"),
    ("https://theprint.in/feed/","The Print","en","news",None,"neutral"),
]

def dedup_sort(items):
    seen, out = set(), []
    for a in items:
        h = a.get("article_hash") or ahash(a.get("title",""))
        if h not in seen: seen.add(h); out.append(a)
    return sorted(out, key=lambda x: x.get("published_at",""), reverse=True)

# ── STORY CLUSTERING ─────────────────────────────────────────
def keywords(text):
    stop = {"and","the","of","in","to","a","is","are","was","for","on","at","by","an","or",
            "that","this","it","be","as","with","from","but","not","have","has","said","says",
            "ఆ","ఈ","ఇది","కి","కు","ను","లో","పై","తో","మరియు","అని","గా"}
    return {w for w in re.findall(r'\b\w{4,}\b', text.lower()) if w not in stop}

def similar(a1, a2):
    # Same spokesperson + topic = same story
    sp1, sp2 = a1.get("spokesperson","None"), a2.get("spokesperson","None")
    if sp1 == sp2 and sp1 not in ["None",""] and a1.get("topic") == a2.get("topic"):
        return True
    # Keyword Jaccard similarity
    k1 = keywords(a1.get("title","")+" "+a1.get("description",""))
    k2 = keywords(a2.get("title","")+" "+a2.get("description",""))
    if not k1 or not k2: return False
    inter = len(k1&k2); union = len(k1|k2)
    return (inter/union) >= 0.25 if union else False

def cluster(articles):
    groups, used = [], set()
    for i, a in enumerate(articles):
        if i in used: continue
        g = [a]; used.add(i)
        for j, b in enumerate(articles):
            if j in used or j == i: continue
            if similar(a, b): g.append(b); used.add(j)
        groups.append(g)
    return groups

def build_top_stories(all_arts):
    groups = cluster(all_arts)
    stories = []
    for g in groups:
        if not g: continue
        best = max(g, key=lambda a: len(a.get("title","")))
        headline = best.get("title","")
        srcs = {}
        for a in g:
            s = a.get("source","")
            if s and s not in srcs: srcs[s] = a.get("url","")
        unique_src = len(srcs); cov = len(g)
        base = max(a.get("viral_score",0) for a in g)
        cov_boost = min(30, cov*5); src_boost = min(20, unique_src*7)
        ysrcp_srcs = {"Sakshi","YSRCP Official"}; tdp_srcs = {"Eenadu","Andhra Jyothi","TDP Official"}
        eco = 15 if (any(s in ysrcp_srcs for s in srcs) and any(s in tdp_srcs for s in srcs)) else 0
        reach = min(100, base+cov_boost+src_boost+eco)
        v_lbl = "High" if reach>=70 else ("Medium" if reach>=40 else "Low")
        topic = best.get("topic","Governance")
        long_topics = ["Amaravati","Polavaram","Elections","Corruption","Farm Loan"]
        trend = "2-3 days" if (reach>=70 or topic in long_topics) else ("1 day" if (reach>=40 or unique_src>=3) else ("few hours" if cov>=2 else "hours"))
        parties = set()
        for a in g:
            for p in (a.get("party","") or "").split("/"):
                if p and p!="General": parties.add(p)
        cov_type = "multi_directional" if len(parties)>=2 else ("wide_coverage" if unique_src>=3 else "one_directional")
        latest = max(g, key=lambda a: a.get("published_at",""))
        stories.append({
            "headline": headline,
            "topic": topic,
            "party": best.get("party","General"),
            "spokesperson": best.get("spokesperson","None"),
            "coverage_count": cov,
            "unique_source_count": unique_src,
            "reach_score": reach,
            "viral_score": v_lbl,
            "trend_duration": trend,
            "coverage_type": cov_type,
            "published_at": latest.get("published_at",""),
            "sources": [{"name":n,"url":u} for n,u in srcs.items()],
            "summary": "",
        })
    stories.sort(key=lambda s:(s["reach_score"],s["coverage_count"]), reverse=True)
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
