"""
NādiPulse AP Political News API v5
- AP-only strict filter
- Party/Spokesperson/Topic tagging
- Chandrababu=Naidu=CBN aliases fixed
- Sakshi via NewsData.io
- English + Telugu RSS sources
- 24-hour rolling window, IST
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import threading
from datetime import datetime, timezone, timedelta

app = FastAPI(title="NādiPulse News API v5")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "te-IN,te;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}

NEWSDATA_KEY = "pub_6e4903bc366f46d5b8cbbcc2f9593f9f"

IST = timezone(timedelta(hours=5, minutes=30))
def now_ist(): return datetime.now(IST)
def now_ist_str(): return datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
def fmt_ist(dt):
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")
def display_ist(dt):
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")

cache = {"articles": [], "english": [], "last_updated": None, "status": "starting"}

# ─── AP-ONLY FILTER ──────────────────────────────────────────
AP_REQUIRED = [
    # State
    "andhra pradesh","andhra","ap government","ap cm","ap bjp","ap assembly",
    "ఆంధ్రప్రదేశ్","ఆంధ్ర","తెలుగు రాష్ట్రం",
    # AP Parties
    "ysrcp","ysr congress","telugu desam","tdp","janasena","jsp",
    "వైఎస్ఆర్సీపీ","టీడీపీ","తెలుగుదేశం","జనసేన",
    # AP Leaders — ALL ALIASES for Chandrababu
    "chandrababu","naidu","nara lokesh","lokesh","pawan kalyan","pawan",
    "jagan","jaganmohan","ys jagan","jagan mohan reddy",
    "ambati","sajjala","buggana","botsa","vijayasai","seediri","peddireddy","roja",
    "nara chandrababu","cbn","n chandrababu","cm naidu","cm chandrababu",
    # Telugu leader names
    "జగన్","చంద్రబాబు","నాయుడు","లోకేశ్","పవన్","నారా",
    "అంబటి","సజ్జల","బుగ్గన","బొత్స","రోజా","సీడిరి",
    # AP Cities
    "amaravati","visakhapatnam","vizag","vijayawada","tirupati","guntur",
    "kurnool","nellore","kadapa","anantapur","ongole","rajahmundry",
    "kakinada","eluru","srikakulam","vizianagaram","machilipatnam",
    "అమరావతి","విశాఖపట్నం","విజయవాడ","తిరుపతి","గుంటూరు",
    "కర్నూలు","నెల్లూరు","కడప","ఒంగోలు","రాజమహేంద్రవరం","కాకినాడ",
    # AP Schemes/Topics
    "polavaram","aarogyasri","rythu bharosa","ap budget","nabard ap",
    "పోలవరం","ఆరోగ్యశ్రీ","రైతు భరోసా","అమరావతి రాజధాని",
    # AP Assembly/Legal
    "ap high court","andhra high court","rayalaseema","uttarandhra",
    "రాయలసీమ","ఉత్తరాంధ్ర",
]

EXCLUDE_STATES = [
    "tamil nadu","tamilnadu","tvk","vijay actor","palani","dmk","admk","mk stalin",
    "west bengal","bengal","kolkata","mamata","trinamool","tmc",
    "assam","guwahati","himanta","arunachal","nagaland","mizoram","manipur","meghalaya",
    "karnataka","bengaluru","bangalore","siddaramaiah","kumaraswamy","jds",
    "maharashtra","mumbai","shinde","fadnavis","uddhav","ncp","baramati","sharad pawar",
    "gujarat","goa","rajasthan","madhya pradesh","chhattisgarh","jharkhand","odisha",
    "punjab","haryana","himachal","uttarakhand","uttar pradesh","lucknow","yogi",
    "bihar","patna","nitish","lalu","jharkhand","jammu","kashmir","ladakh",
    "kerala","thiruvananthapuram","pinarayi","oommen","iuml",
    "telangana","hyderabad","revanth reddy","brs","kcr","ktr","bhrs",
    "delhi","arvind kejriwal","aap delhi","manish sisodia",
    "bangladesh","pakistan","china","sri lanka","myanmar",
    "james cameron","disney","hollywood","bollywood","oscars","grammy",
    "cricket","ipl","bcci","t20","odi","test match","football","fifa","olympics",
    "movie","film release","box office","ott release","web series","trailer",
    "swearing-in assam","sunetra pawar","rajya sabha baramati",
    "తమిళనాడు","తమిళ","బెంగాల్","కేరళ","కర్నాటక","మహారాష్ట్ర",
    "తెలంగాణ","అస్సాం","గుజరాత్","రాజస్థాన్",
]

EXCLUDE_CONTENT = [
    "recipe","cooking","fashion","beauty","horoscope","astrology","vastu",
    "wedding","relationship tips","health tips","weight loss",
    "రాశిఫలం","వాస్తు","వంటకం","ఫ్యాషన్","అందం",
]

POLITICAL_KW = [
    "government","minister","chief minister","assembly","parliament","election",
    "political","party","MLA","MP","CM","cabinet","budget","scheme","welfare",
    "policy","allegation","criticism","governance","ruling","opposition","rally",
    "press meet","statement","demand","protest","arrest","fir","court",
    "రాజకీయ","ప్రభుత్వ","మంత్రి","ముఖ్యమంత్రి","అసెంబ్లీ","ఎన్నిక",
    "పార్టీ","ఎమ్మెల్యే","ఎంపీ","సీఎం","బడ్జెట్","పథకం","ఆరోపణ","నిరసన",
]

def is_political(title, desc=""):
    text = (title + " " + (desc or "")).lower()
    # Hard exclude
    if any(k.lower() in text for k in EXCLUDE_CONTENT): return False
    # Must have AP context
    has_ap = any(k.lower() in text for k in AP_REQUIRED)
    if not has_ap: return False
    # Block other states (unless AP context overrides)
    other_state = any(k.lower() in text for k in EXCLUDE_STATES)
    if other_state:
        ap_override = any(k.lower() in text for k in [
            "andhra","ysrcp","chandrababu","naidu","jagan","pawan","tdp","amaravati",
            "ఆంధ్ర","జగన్","చంద్రబాబు","పవన్","అమరావతి","నాయుడు"
        ])
        if not ap_override: return False
    # Must be political
    return any(k.lower() in text for k in POLITICAL_KW) or has_ap

# ─── LEADER ALIASES (Chandrababu = Naidu = CBN) ──────────────
# All aliases → canonical display name
LEADER_ALIASES = {
    # Chandrababu - all variations map to one
    "chandrababu naidu": "Chandrababu",
    "nara chandrababu": "Chandrababu",
    "n chandrababu": "Chandrababu",
    "chandrababu": "Chandrababu",
    "cbn": "Chandrababu",
    "cm naidu": "Chandrababu",
    "naidu": "Chandrababu",
    "cm chandrababu": "Chandrababu",
    "చంద్రబాబు నాయుడు": "Chandrababu",
    "చంద్రబాబు": "Chandrababu",
    "నాయుడు": "Chandrababu",
    # Lokesh
    "nara lokesh": "Lokesh",
    "lokesh": "Lokesh",
    "నారా లోకేశ్": "Lokesh",
    "లోకేశ్": "Lokesh",
    # Jagan
    "jagan mohan reddy": "Jagan",
    "jaganmohan reddy": "Jagan",
    "ys jagan": "Jagan",
    "jagan": "Jagan",
    "జగన్ మోహన్": "Jagan",
    "జగన్": "Jagan",
    "ysjagan": "Jagan",
    # Pawan
    "pawan kalyan": "Pawan Kalyan",
    "pawankalyan": "Pawan Kalyan",
    "pawan": "Pawan Kalyan",
    "పవన్ కల్యాణ్": "Pawan Kalyan",
    "పవన్": "Pawan Kalyan",
    # Others
    "ambati rambabu": "Ambati Rambabu",
    "ambati": "Ambati Rambabu",
    "అంబటి రంబాబు": "Ambati Rambabu",
    "అంబటి": "Ambati Rambabu",
    "sajjala": "Sajjala",
    "సజ్జల": "Sajjala",
    "buggana": "Buggana",
    "బుగ్గన": "Buggana",
    "botsa": "Botsa",
    "బొత్స": "Botsa",
    "vijayasai": "Vijayasai Reddy",
    "విజయసాయి": "Vijayasai Reddy",
    "seediri": "Seediri Appalaraju",
    "సీడిరి": "Seediri",
    "roja": "Roja",
    "రోజా": "Roja",
    "peddireddy": "Peddireddy",
    "పెద్దిరెడ్డి": "Peddireddy",
}

YSRCP_LEADERS_CHECK = ["jagan","jaganmohan","ys jagan","ambati","sajjala","buggana","botsa","vijayasai","seediri","peddireddy","roja","జగన్","అంబటి","సజ్జల","బుగ్గన","బొత్స","రోజా"]
TDP_LEADERS_CHECK = ["chandrababu","naidu","nara lokesh","lokesh","cbn","cm naidu","చంద్రబాబు","నాయుడు","లోకేశ్","నారా"]
BJP_LEADERS_CHECK = ["puranik","kishan reddy","bandi sanjay","ap bjp","బండి సంజయ్"]
JSP_LEADERS_CHECK = ["pawan kalyan","pawankalyan","pawan","janasena","jsp","పవన్ కల్యాణ్","పవన్","జనసేన"]

TOPICS = {
    "Aarogyasri": ["aarogyasri","ఆరోగ్యశ్రీ","health scheme","hospital scheme"],
    "Amaravati": ["amaravati","అమరావతి","capital city","capital region","రాజధాని"],
    "Farm Loan": ["farm loan","రైతు రుణమాఫీ","agriculture loan","crop loan","రైతు","rythu"],
    "Fuel Crisis": ["petrol","diesel","fuel","పెట్రోల్","డీజిల్","bunk","shortage"],
    "Google/IT": ["google","data center","it sector","tech","విశాఖ it","vizag it"],
    "Law & Order": ["arrest","fir","police","court","హైకోర్టు","supreme court","raid"],
    "Elections": ["election","poll","by-poll","వోటు","ఎన్నిక","campaign","nomination","bypoll"],
    "Welfare": ["welfare","scheme","pension","పింఛన్","పథకం","beneficiary","ration"],
    "Budget": ["budget","funds","allocation","నిధులు","బడ్జెట్","financial","revenue"],
    "Education": ["school","college","university","students","విద్య","education","fee"],
    "Corruption": ["corruption","scam","fraud","అవినీతి","కుంభకోణం","misappropriation","embezzle"],
    "Governance": ["governance","administration","policy","పాలన","అభివృద్ధి","development","infra"],
    "Polavaram": ["polavaram","పోలవరం","dam","project"],
}

def detect_spokesperson(text):
    text_lower = text.lower()
    for alias, canonical in LEADER_ALIASES.items():
        if alias.lower() in text_lower:
            return canonical
    return "None"

def detect_party(text):
    text_lower = text.lower()
    parties = []
    if any(k in text_lower for k in YSRCP_LEADERS_CHECK + ["ysrcp","ysr congress","వైఎస్ఆర్సీపీ","విపక్షం"]):
        parties.append("YSRCP")
    if any(k in text_lower for k in TDP_LEADERS_CHECK + ["tdp","telugu desam","టీడీపీ","తెలుగుదేశం"]):
        parties.append("TDP")
    if any(k in text_lower for k in BJP_LEADERS_CHECK + ["bjp","bharatiya janata","బీజేపీ"]):
        parties.append("BJP")
    if any(k in text_lower for k in JSP_LEADERS_CHECK + ["జనసేన"]):
        parties.append("JSP")
    return "/".join(parties) if parties else "General"

def detect_topic(text):
    t = text.lower()
    for topic, kws in TOPICS.items():
        if any(k.lower() in t for k in kws):
            return topic
    return "Governance"

def detect_sentiment(text):
    t = text.lower()
    neg = ["attack","criticize","condemn","scam","fraud","failure","corrupt","అవినీతి","విమర్శ","ఆరోపణ","వైఫల్యం","అక్రమ","దాడి","నిరసన"]
    pos = ["develop","inaugurat","launch","scheme","achieve","అభివృద్ధి","ప్రారంభ","పథకం","విజయ","సాధించ"]
    if any(k in t for k in neg): return "Negative"
    if any(k in t for k in pos): return "Positive"
    return "Neutral"

def tag_article(title, desc=""):
    text = title + " " + (desc or "")
    return {
        "party": detect_party(text),
        "spokesperson": detect_spokesperson(text),
        "topic": detect_topic(text),
        "sentiment": detect_sentiment(text),
    }

# ─── DATE PARSER ─────────────────────────────────────────────
def parse_pub(s):
    if not s: return now_ist()
    for fmt in ["%a, %d %b %Y %H:%M:%S %z","%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z","%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%SZ"]:
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST)
        except: pass
    return now_ist()

# ─── SCRAPERS ─────────────────────────────────────────────────
def scrape_rss(url, source, lang="te"):
    out = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item") or soup.find_all("entry")
        cutoff = now_ist() - timedelta(hours=24)
        for item in items[:25]:
            ttag = item.find("title")
            ltag = item.find("link")
            ptag = item.find("pubDate") or item.find("published")
            dtag = item.find("description") or item.find("summary")
            if not ttag: continue
            title = ttag.get_text(strip=True)
            if len(title) < 15: continue
            desc = BeautifulSoup(dtag.get_text(), "html.parser").get_text(strip=True)[:200] if dtag else ""
            if not is_political(title, desc): continue
            pub = parse_pub(ptag.get_text(strip=True) if ptag else None)
            if pub < cutoff: continue
            link = ltag.get_text(strip=True) if ltag else ""
            tags = tag_article(title, desc)
            out.append({"title": title, "url": link, "source": source, "description": desc,
                "language": lang, "published_at": fmt_ist(pub),
                "published_display": display_ist(pub), "scraped_at": now_ist_str(), **tags})
        print(f"  {source}: {len(out)} articles")
    except Exception as e:
        print(f"  RSS {source}: {e}")
    return out

def scrape_html(url, source, base_url, path_filter):
    out = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            h = a.find(["h2","h3","h4"])
            if not h: continue
            title = h.get_text(strip=True)
            if len(title) < 15 or title in seen: continue
            seen.add(title)
            href = a["href"]
            if not href.startswith("http"): href = base_url + href
            if path_filter and path_filter not in href: continue
            if not is_political(title): continue
            p = a.find("p") or a.find_next_sibling("p")
            desc = " ".join(p.get_text(strip=True).split())[:200] if p else ""
            tags = tag_article(title, desc)
            out.append({"title": title, "url": href, "source": source, "description": desc,
                "language": "te", "published_at": now_ist_str(),
                "published_display": display_ist(now_ist()), "scraped_at": now_ist_str(), **tags})
            if len(out) >= 15: break
        print(f"  {source}: {len(out)} articles")
    except Exception as e:
        print(f"  HTML {source}: {e}")
    return out

def scrape_sakshi():
    """Sakshi blocks direct access (403). Use NewsData.io domain filter."""
    out = []
    now = now_ist()
    cutoff = now - timedelta(hours=24)
    seen = set()
    apis = [
        f"https://newsdata.io/api/1/news?apikey={NEWSDATA_KEY}&domainurl=sakshi.com&language=te&size=10",
        f"https://newsdata.io/api/1/news?apikey={NEWSDATA_KEY}&q=ఆంధ్రప్రదేశ్+రాజకీయాలు&domainurl=sakshi.com&language=te&size=10",
    ]
    for api_url in apis:
        try:
            r = requests.get(api_url, timeout=12)
            d = r.json()
            for item in d.get("results", []):
                title = (item.get("title") or "").strip()
                if len(title) < 15 or title in seen: continue
                seen.add(title)
                desc = (item.get("description") or "").strip()[:200]
                link = item.get("link") or ""
                pub = parse_pub(item.get("pubDate") or "")
                if pub < cutoff: continue
                if not is_political(title, desc): continue
                tags = tag_article(title, desc)
                out.append({"title": title, "url": link, "source": "Sakshi",
                    "description": desc, "language": "te",
                    "published_at": fmt_ist(pub), "published_display": display_ist(pub),
                    "scraped_at": now_ist_str(), **tags})
            if out: print(f"  Sakshi (NewsData): {len(out)} articles"); break
        except Exception as e:
            print(f"  Sakshi NewsData error: {e}")
    if not out: print("  Sakshi: 0 articles")
    return out

# ─── SOURCES ─────────────────────────────────────────────────
TELUGU_RSS = [
    ("https://tv9telugu.com/feed",              "TV9 Telugu",    "te"),
    ("https://ntvtelugu.com/feed",              "NTV Telugu",    "te"),
    ("https://10tv.in/feed",                    "10TV",          "te"),
    ("https://tv5news.in/feed",                 "TV5 News",      "te"),
    ("https://www.andhrajyothy.com/feed",       "Andhra Jyothi", "te"),
]
TELUGU_HTML = [
    ("https://www.eenadu.net/andhra-pradesh", "Eenadu", "https://www.eenadu.net", "/telugu-news/"),
]
ENGLISH_RSS = [
    ("https://feeds.feedburner.com/ndtvnews-india-news",                        "NDTV",               "en"),
    ("https://www.thehindu.com/news/national/andhra-pradesh/?service=rss",      "The Hindu",          "en"),
    ("https://indianexpress.com/feed/",                                          "Indian Express",     "en"),
    ("https://www.deccanchronicle.com/rss_feed/",                               "Deccan Chronicle",   "en"),
    ("https://www.newindianexpress.com/rss/andhra-pradesh.xml",                 "New Indian Express", "en"),
    ("https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",              "Times of India",     "en"),
    ("https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",         "Hindustan Times",    "en"),
    ("https://telugu.news18.com/commonfeeds/v1/tel/rss/news.xml",               "News18 Telugu",      "en"),
    ("https://www.siasat.com/feed/",                                             "Siasat",             "en"),
    ("https://theprint.in/feed/",                                                "The Print",          "en"),
]

def dedup_sort(items):
    seen, out = set(), []
    for a in items:
        if a["title"] not in seen:
            seen.add(a["title"])
            out.append(a)
    return sorted(out, key=lambda x: x.get("published_at",""), reverse=True)

def crawl():
    print(f"\n[{now_ist().strftime('%d %b %H:%M IST')}] Crawling AP political news...")
    te, en = [], []
    for url, src, lang in TELUGU_RSS:
        te.extend(scrape_rss(url, src, lang)); time.sleep(0.5)
    te.extend(scrape_sakshi()); time.sleep(1)
    for url, src, base, filt in TELUGU_HTML:
        te.extend(scrape_html(url, src, base, filt)); time.sleep(1)
    for url, src, lang in ENGLISH_RSS:
        en.extend(scrape_rss(url, src, lang)); time.sleep(0.5)
    cache["articles"] = dedup_sort(te)
    cache["english"] = dedup_sort(en)
    cache["last_updated"] = now_ist_str()
    cache["status"] = "ok"
    print(f"  Done: {len(cache['articles'])} Telugu + {len(cache['english'])} English articles")

def bg_crawl():
    while True:
        try: crawl()
        except Exception as e: print(f"Crawl error: {e}")
        time.sleep(15*60)

@app.on_event("startup")
async def startup():
    threading.Thread(target=bg_crawl, daemon=True).start()

@app.get("/")
def root():
    return {"name":"NādiPulse v5","telugu":len(cache["articles"]),"english":len(cache["english"]),"last_updated":cache.get("last_updated"),"status":cache["status"]}

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

@app.get("/all")
def all_news(limit:int=200):
    combined = dedup_sort(cache["articles"] + cache["english"])
    return {"count":len(combined[:limit]),"last_updated":cache.get("last_updated"),"articles":combined[:limit]}

@app.get("/health")
def health():
    return {"status":cache["status"],"telugu":len(cache["articles"]),"english":len(cache["english"]),"last_updated":cache.get("last_updated")}


# ─── AI ANALYSIS ENDPOINT ────────────────────────────────────
import os, json

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY", "")

from fastapi import Request
from fastapi.responses import JSONResponse

SYSTEM_PROMPT = """You are a senior AP political intelligence analyst. You analyze news articles about Andhra Pradesh politics for YSRCP party leadership.

CRITICAL RULES:
1. ONLY use information from the articles provided. Do NOT use any outside knowledge.
2. If something is not mentioned in the articles, say "Not found in today's coverage".
3. All output must be in ENGLISH only.
4. Telugu articles are labeled [Telugu] - translate their content before analysis.
5. Chandrababu = Naidu = CBN = N Chandrababu Naidu = CM Naidu — all are the SAME person.
6. Always cite source names when making claims (e.g. "According to Eenadu...").
7. Be factual, specific, and concise."""

@app.post("/analyse")
async def analyse(request: Request):
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        system = body.get("system", SYSTEM_PROMPT)
        max_tokens = body.get("max_tokens", 1200)

        if not prompt:
            return JSONResponse({"error": "No prompt provided"}, status_code=400)

        # Try Groq first (fast, free)
        if GROQ_KEY:
            try:
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.1-70b-versatile",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.3
                    },
                    timeout=30
                )
                d = r.json()
                text = d["choices"][0]["message"]["content"]
                return JSONResponse({"text": text, "model": "groq/llama-3.1-70b"})
            except Exception as e:
                print(f"Groq failed: {e}")

        # Fallback: Claude API
        if CLAUDE_KEY:
            try:
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": CLAUDE_KEY,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": prompt}]
                    },
                    timeout=30
                )
                d = r.json()
                text = d["content"][0]["text"]
                return JSONResponse({"text": text, "model": "claude-haiku"})
            except Exception as e:
                print(f"Claude failed: {e}")

        return JSONResponse({"error": "No AI API key configured. Add GROQ_API_KEY or ANTHROPIC_API_KEY in Render environment variables."}, status_code=500)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
