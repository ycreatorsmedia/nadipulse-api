"""
NādiPulse Telugu & English News API v4
- Political articles only
- Party, Spokesperson, Topic tagging
- English + Telugu RSS sources
- 24-hour rolling window
- IST timestamps
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import time
import threading
from datetime import datetime, timezone, timedelta

app = FastAPI(title="NādiPulse News API v4")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "te-IN,te;q=0.9,en;q=0.8",
}

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

# ─── AP-SPECIFIC FILTER ────────────────
# Article MUST contain AP-specific terms to pass
# This prevents Tamil Nadu, Bengal, Assam, etc. articles from showing

AP_REQUIRED = [
    # State names
    "andhra pradesh","andhra","telugu states","ap government","ap cm","ap bjp",
    "ఆంధ్రప్రదేశ్","ఆంధ్ర","తెలుగు రాష్ట్రం",
    # AP-specific parties
    "ysrcp","ysr congress","telugu desam","tdp","janasena","జనసేన",
    "వైఎస్ఆర్సీపీ","టీడీపీ","తెలుగుదేశం",
    # AP Leaders (unique to AP)
    "jagan mohan reddy","jaganmohan","ys jagan","ysr","chandrababu naidu",
    "nara chandrababu","nara lokesh","lokesh","pawan kalyan","pawankalyan",
    "ambati rambabu","sajjala","buggana","botsa","vijayasai reddy",
    "seediri","peddireddy","talasila","roja","anil kumar yadav",
    "జగన్ మోహన్","చంద్రబాబు నాయుడు","నారా లోకేశ్","పవన్ కల్యాణ్",
    "అంబటి రంబాబు","సజ్జల","బొత్స",
    # Short Telugu leader names (common in headlines)
    "జగన్","చంద్రబాబు","లోకేశ్","పవన్","నాయుడు","రాజు",
    "విజయసాయి","అంబటి","సజ్జల","బుగ్గన","బొత్స","రోజా","సీడిరి","పెద్దిరెడ్డి",
    # AP cities/districts
    "amaravati","visakhapatnam","vizag","vijayawada","tirupati","guntur",
    "kurnool","nellore","kadapa","anantapur","ongole","rajahmundry",
    "kakinada","eluru","machilipatnam","srikakulam","vizianagaram",
    "అమరావతి","విశాఖపట్నం","విజయవాడ","తిరుపతి","గుంటూరు",
    "కర్నూలు","నెల్లూరు","కడప","అనంతపురం","ఒంగోలు","రాజమహేంద్రవరం",
    # AP-specific topics
    "polavaram","aarogyasri","rythu bharosa","nabard ap","ap budget",
    "పోలవరం","ఆరోగ్యశ్రీ","రైతు భరోసా",
    # AP assembly/governance
    "ap assembly","andhra assembly","ap legislature","ap high court",
    "amaravati capital","capital city andhra","rayalaseema","uttarandhra",
    "రాయలసీమ","ఉత్తరాంధ్ర",
]

EXCLUDE_STATES = [
    # Other Indian states - if these appear WITHOUT AP terms, exclude
    "tamil nadu","tamilnadu","tamilians","chennai","tvk","vijay actor",
    "west bengal","bengal","kolkata","mamata","trinamool","tmc",
    "assam","guwahati","himanta","arunachal","meghalaya","nagaland","mizoram",
    "karnataka","bengaluru","bangalore","siddaramaiah","kumaraswamy",
    "maharashtra","mumbai","shinde","fadnavis","uddhav","ncp",
    "delhi","arvind kejriwal","aap delhi","punjab","haryana","rajasthan",
    "gujarat","yogi adityanath","uttar pradesh","lucknow","bihar",
    "kerala","thiruvananthapuram","oommen","pinarayi",
    "telangana","hyderabad","revanth reddy","brs","kcr","ktr",
    "odisha","jharkhand","chhattisgarh","goa","manipur","tripura",
    "jammu kashmir","ladakh","bangladesh","pakistan","china",
    "james cameron","disney","hollywood","bollywood","cricket","ipl",
    "swearing-in assam","assam govt","baramati","sunetra pawar","rajya sabha baramati",
    "తమిళనాడు","తమిళ","బెంగాల్","కేరళ","కర్నాటక","మహారాష్ట్ర","తెలంగాణ",
    "అస్సాం","గుజరాత్","రాజస్థాన్","పంజాబ్",
]

POLITICAL_KW = [
    "government","minister","chief minister","assembly","parliament",
    "election","political","party","MLA","MP","CM","cabinet",
    "budget","scheme","welfare","policy","allegation","governance",
    "రాజకీయ","ప్రభుత్వ","మంత్రి","ముఖ్యమంత్రి","అసెంబ్లీ","పార్లమెంట్",
    "ఎన్నిక","పార్టీ","ఎమ్మెల్యే","ఎంపీ","సీఎం","బడ్జెట్","పథకం",
]

EXCLUDE_KW = [
    "cricket","ipl","football","match","score","wicket","batting","tournament",
    "movie","film","actor","actress","director","cinema","box office","release","trailer","ott",
    "recipe","cooking","fashion","beauty","horoscope","astrology","vastu","wedding",
    "ఐపీఎల్","క్రికెట్","మ్యాచ్","సినిమా","మూవీ","హీరో","హీరోయిన్","నటుడు","రాశిఫలం",
    "james cameron","disney","sued","lawsuit","swearing-in ceremony",
]

def is_political(title, desc=""):
    text = (title+" "+(desc or "")).lower()

    # Step 1: Hard exclude non-political content
    for kw in EXCLUDE_KW:
        if kw.lower() in text:
            return False

    # Step 2: MUST have at least one AP-specific term
    has_ap = any(kw.lower() in text for kw in AP_REQUIRED)
    if not has_ap:
        return False

    # Step 3: Check if it's about another state (without AP context)
    other_state = any(kw.lower() in text for kw in EXCLUDE_STATES)
    if other_state and not any(ap in text for ap in [
        "andhra","ysrcp","chandrababu","jagan","pawan","tdp","amaravati",
        "ఆంధ్ర","జగన్","చంద్రబాబు","పవన్","అమరావతి"
    ]):
        return False

    # Step 4: Must be political
    return any(kw.lower() in text for kw in POLITICAL_KW) or has_ap

# ─── PARTY + SPOKESPERSON + TOPIC TAGGING ───
YSRCP_LEADERS = [
    "jagan","ys jagan","jaganmohan","jagan mohan reddy","ysr","vijayasai reddy",
    "sajjala","buggana","ambati rambabu","peddireddy","botsa satyanarayana",
    "talasila","vella murali","roja","seediri","కేడీ","జగన్","అంబటి","విజయసాయి",
    "సజ్జల","బుగ్గన","బొత్స"
]
TDP_LEADERS = [
    "chandrababu","naidu","lokesh","nara lokesh","nara chandrababu",
    "kinjarapu atchen naidu","kollu ravindra","kola suresh","devineni uma",
    "nimmala ramanaidu","gottipati ravi kumar","চন্দ্রবাবু","చంద్రబాబు","లోకేశ్","నారా"
]
BJP_LEADERS = [
    "puranik","vishnu deo sai","daggubati","kishan reddy","bandi sanjay",
    "ap bjp","బండి సంజయ్","కిషన్ రెడ్డి"
]
JSP_LEADERS = [
    "pawan kalyan","pawankalyan","pawan","deputy cm pawan","jsp","janasena",
    "పవన్ కల్యాణ్","పవన్","జనసేన"
]

TOPICS = {
    "Aarogyasri": ["aarogyasri","ఆరోగ్యశ్రీ","health scheme","hospital","medical"],
    "Amaravati": ["amaravati","అమరావతి","capital city","capital region"],
    "Farm Loan": ["farm loan","రైతు రుణమాఫీ","agriculture loan","crop loan","రైతు"],
    "Fuel Crisis": ["petrol","diesel","fuel","పెట్రోల్","డీజిల్","bunk","shortage"],
    "Google/IT": ["google","data center","it sector","tech park","విశాఖ","vizag"],
    "Law & Order": ["arrest","fir","police","court","case","హైకోర్టు","supreme court"],
    "Elections": ["election","poll","by-poll","వోటు","ఎన్నిక","campaign","nomination"],
    "Welfare": ["welfare","scheme","pension","పింఛన్","పథకం","beneficiary"],
    "Budget": ["budget","funds","allocation","నిధులు","బడ్జెట్","financial"],
    "Education": ["school","college","university","students","విద్య","education"],
    "Corruption": ["corruption","scam","fraud","అవినీతి","కుంభకోణం","misappropriation"],
    "Governance": ["governance","administration","policy","పాలన","అభివృద్ధి","development"],
}

def tag_article(title, desc=""):
    text = (title+" "+(desc or "")).lower()
    
    # Party detection
    has_ysrcp = any(l.lower() in text for l in YSRCP_LEADERS) or any(k in text for k in ["ysrcp","ysr congress","విపక్షం opposition leader"])
    has_tdp = any(l.lower() in text for l in TDP_LEADERS) or any(k in text for k in ["tdp","telugu desam","ruling government","ap government","cm naidu"])
    has_bjp = any(l.lower() in text for l in BJP_LEADERS) or "bjp" in text or "bharatiya janata" in text
    has_jsp = any(l.lower() in text for l in JSP_LEADERS) or "janasena" in text or "జనసేన" in text
    
    parties = []
    if has_ysrcp: parties.append("YSRCP")
    if has_tdp: parties.append("TDP")
    if has_bjp: parties.append("BJP")
    if has_jsp: parties.append("JSP")
    party = "/".join(parties) if parties else "General"
    
    # Spokesperson detection
    spokesperson = "None"
    full_text = title+" "+(desc or "")
    for l in YSRCP_LEADERS + TDP_LEADERS + BJP_LEADERS + JSP_LEADERS:
        if l.lower() in full_text.lower() and len(l) > 4:
            spokesperson = l.title()
            break
    
    # Topic detection
    topic = "Politics"
    for t_name, keywords in TOPICS.items():
        if any(k.lower() in text for k in keywords):
            topic = t_name
            break
    
    # Sentiment
    neg_kw = ["attack","criticize","condemn","scam","fraud","failure","corruption","అవినీతి","విమర్శ","ఆరోపణ","వైఫల్యం"]
    pos_kw = ["develop","inaugurat","launch","scheme","welfare","achievement","అభివృద్ధి","ప్రారంభ","పథకం"]
    sentiment = "Negative" if any(k in text for k in neg_kw) else "Positive" if any(k in text for k in pos_kw) else "Neutral"
    
    return {"party": party, "spokesperson": spokesperson, "topic": topic, "sentiment": sentiment}

# ─── DATE PARSER ────────────────────────
def parse_pub(s):
    if not s: return now_ist()
    for fmt in ["%a, %d %b %Y %H:%M:%S %z","%a, %d %b %Y %H:%M:%S GMT","%Y-%m-%dT%H:%M:%S%z","%Y-%m-%d %H:%M:%S"]:
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(IST)
        except: pass
    return now_ist()

# ─── SCRAPE RSS ─────────────────────────
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
            out.append({
                "title": title, "url": link, "source": source,
                "description": desc, "language": lang,
                "published_at": fmt_ist(pub),
                "published_display": display_ist(pub),
                "scraped_at": now_ist_str(), **tags
            })
    except Exception as e:
        print(f"  RSS {source}: {e}")
    return out

# ─── SCRAPE HTML ─────────────────────────
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
            tags = tag_article(title)
            out.append({
                "title": title, "url": href, "source": source,
                "description": "", "language": "te",
                "published_at": now_ist_str(),
                "published_display": display_ist(now_ist()),
                "scraped_at": now_ist_str(), **tags
            })
            if len(out) >= 12: break
    except Exception as e:
        print(f"  HTML {source}: {e}")
    return out

# ─── ALL SOURCES ────────────────────────
TELUGU_RSS = [
    ("https://tv9telugu.com/feed",           "TV9 Telugu",     "te"),
    ("https://ntvtelugu.com/feed",           "NTV Telugu",     "te"),
    ("https://10tv.in/feed",                 "10TV",           "te"),
    ("https://tv5news.in/feed",              "TV5 News",       "te"),
    ("https://www.andhrajyothy.com/feed",    "Andhra Jyothi",  "te"),
]

ENGLISH_RSS = [
    ("https://feeds.feedburner.com/ndtvnews-india-news",                          "NDTV",               "en"),
    ("https://www.thehindu.com/news/national/andhra-pradesh/?service=rss",        "The Hindu",          "en"),
    ("https://indianexpress.com/feed/",                                            "Indian Express",     "en"),
    ("https://www.deccanchronicle.com/rss_feed/",                                 "Deccan Chronicle",   "en"),
    ("https://www.newindianexpress.com/rss/andhra-pradesh.xml",                   "New Indian Express", "en"),
    ("https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",                "Times of India",     "en"),
    ("https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",           "Hindustan Times",    "en"),
    ("https://telugu.news18.com/commonfeeds/v1/tel/rss/news.xml",                 "News18 Telugu",      "en"),
    ("https://www.siasat.com/feed/",                                               "Siasat",             "en"),
    ("https://theprint.in/feed/",                                                  "The Print",          "en"),
]

TELUGU_HTML = [
    ("https://www.eenadu.net/andhra-pradesh",  "Eenadu",       "https://www.eenadu.net", "/telugu-news/"),
    ("https://www.sakshi.com/andhra-pradesh-news", "Sakshi",   "https://www.sakshi.com", "/telugu-news/"),
]

def crawl():
    print(f"\n[{now_ist().strftime('%d %b %H:%M IST')}] Crawling all sources...")
    all_te, all_en = [], []

    for url, src, lang in TELUGU_RSS:
        all_te.extend(scrape_rss(url, src, lang))
        time.sleep(0.5)

    for url, src, base, filt in TELUGU_HTML:
        all_te.extend(scrape_html(url, src, base, filt))
        time.sleep(1)

    for url, src, lang in ENGLISH_RSS:
        all_en.extend(scrape_rss(url, src, lang))
        time.sleep(0.5)

    def dedup(items):
        seen, out = set(), []
        for a in items:
            if a["title"] not in seen:
                seen.add(a["title"])
                out.append(a)
        return sorted(out, key=lambda x: x.get("published_at",""), reverse=True)

    cache["articles"] = dedup(all_te)
    cache["english"]  = dedup(all_en)
    cache["last_updated"] = now_ist_str()
    cache["status"] = "ok"
    print(f"  Done: {len(cache['articles'])} Telugu + {len(cache['english'])} English political articles")

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
    return {"name":"NādiPulse News API v4","telugu":len(cache["articles"]),"english":len(cache["english"]),"last_updated":cache.get("last_updated"),"status":cache["status"]}

@app.get("/news")
def news(party:str=None, lang:str=None, limit:int=100):
    arts = cache["articles"]
    if party: arts = [a for a in arts if party.lower() in a.get("party","").lower()]
    if lang:  arts = [a for a in arts if a.get("language","") == lang]
    return {"count":len(arts[:limit]),"last_updated":cache.get("last_updated"),"articles":arts[:limit]}

@app.get("/english")
def english(party:str=None, limit:int=100):
    arts = cache["english"]
    if party: arts = [a for a in arts if party.lower() in a.get("party","").lower()]
    return {"count":len(arts[:limit]),"last_updated":cache.get("last_updated"),"articles":arts[:limit]}

@app.get("/all")
def all_news(limit:int=200):
    combined = cache["articles"] + cache["english"]
    combined.sort(key=lambda x: x.get("published_at",""), reverse=True)
    seen, out = set(), []
    for a in combined:
        if a["title"] not in seen:
            seen.add(a["title"])
            out.append(a)
    return {"count":len(out[:limit]),"last_updated":cache.get("last_updated"),"articles":out[:limit]}

@app.get("/health")
def health():
    return {"status":cache["status"],"telugu":len(cache["articles"]),"english":len(cache["english"]),"last_updated":cache.get("last_updated")}
