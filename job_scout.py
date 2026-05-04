#!/usr/bin/env python3
"""
Job Scout for Dr. K
Scrapes job boards, scores listings, writes ranked HTML to email_body.html
Email is sent by the GitHub Actions workflow (dawidd6/action-send-mail).
"""

import json, datetime, time, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from html import unescape
from zoneinfo import ZoneInfo

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# ── Scoring ───────────────────────────────────────────────────────────────────

CORE_SKILLS = [
    "single-cell", "single cell", "scrna", "rna-seq",
    "organoid", "pluripotent", "ipsc", "stem cell",
]
RESEARCH_AREAS = [
    "brain", "neural", "neuroscience", "primate",
    "comparative genomic", "developmental biology",
    "cell lineage", "organogenesis", "bioinformatic",
]
TITLE_BEST = ["assistant professor", "associate professor", "group leader",
              "staff scientist", "senior scientist", "principal scientist"]
TITLE_GOOD = ["research scientist", "scientist ii", "scientist iii"]
TITLE_OK   = ["scientist", "researcher"]
TITLE_BAD  = ["technician", "lab tech", "undergraduate", "phd student",
              "vp ", "vice president", "marketing", "administrative", "recruiter"]
RSS_KEYWORDS = [
    "single cell", "organoid", "stem cell", "ipsc", "genomic",
    "bioinformat", "sequencing", "neuroscience", "developmental",
    "cell biology", "biochemistry", "molecular biology",
    "biology", "neurobiology", "computational biology",
]

def is_relevant(text):
    return any(k in text.lower() for k in RSS_KEYWORDS)

def score_job(title, desc, org=""):
    text    = f"{title} {desc} {org}".lower()
    title_l = title.lower()
    if any(b in text for b in TITLE_BAD): return 0.0
    s = 0.0
    if   any(t in title_l for t in TITLE_BEST): s += 3.0
    elif any(t in title_l for t in TITLE_GOOD): s += 2.4
    elif any(t in title_l for t in TITLE_OK):   s += 1.8
    else:                                         s += 0.6
    s += min(sum(1 for k in CORE_SKILLS    if k in text) * 1.0, 4.0)
    s += min(sum(1 for k in RESEARCH_AREAS if k in text) * 0.5, 2.0)
    if   any(t in title_l for t in ["senior","principal","staff","professor","group leader"]): s += 1.0
    elif "scientist" in title_l or "researcher" in title_l: s += 0.7
    else:                                                     s += 0.3
    return round(min(s, 10.0), 1)

# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url):
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt == 0: time.sleep(3)
            else: print(f"  skip {url[:70]} — {e}")
    return ""

def clean(text):
    text = re.sub(r"<[^>]+>", " ", unescape(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]

def fmt_date(raw):
    """Parse various date formats into a short 'Mon DD' string, or '' if unparseable."""
    if not raw: return ""
    raw = str(raw).strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",   # RSS: Mon, 28 Apr 2025 00:00:00 +0000
        "%a, %d %b %Y %H:%M:%S %Z",   # RSS: Mon, 28 Apr 2025 00:00:00 GMT
        "%Y-%m-%dT%H:%M:%S.%fZ",      # ISO: 2025-04-28T12:00:00.000Z
        "%Y-%m-%dT%H:%M:%SZ",         # ISO: 2025-04-28T12:00:00Z
        "%Y-%m-%dT%H:%M:%S%z",        # ISO with offset
        "%Y-%m-%d",                    # plain date
    ]
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%b %d")
        except ValueError:
            pass
    # Unix epoch integer
    try:
        return datetime.datetime.utcfromtimestamp(int(raw)).strftime("%b %d")
    except (ValueError, OSError):
        pass
    return ""

# ── Sources ───────────────────────────────────────────────────────────────────

def rss_jobs(url, source, bucket):
    jobs, content = [], fetch(url)
    if not content: return jobs
    for item in re.findall(r"<item[^>]*>(.*?)</item>", content, re.DOTALL):
        def g(tag):
            m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", item, re.DOTALL|re.IGNORECASE)
            return clean(m.group(1)) if m else ""
        title, link, desc = g("title"), g("link") or g("guid"), g("description")
        posted = fmt_date(g("pubDate"))
        if not is_relevant(f"{title} {desc}"): continue
        s = score_job(title, desc)
        if s > 0:
            jobs.append(dict(title=title, org="", location="", url=link, score=s, source=source, bucket=bucket, posted=posted))
    return jobs

def greenhouse(slugs, bucket="industry", min_score=3):
    jobs = []
    for slug in slugs:
        data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not data: continue
        try: items = json.loads(data).get("jobs", [])
        except: continue
        for j in items:
            title = j.get("title","")
            desc  = clean(j.get("content",""))
            s = score_job(title, desc, slug)
            if s >= min_score and not any(b in f"{title} {desc}".lower() for b in TITLE_BAD):
                jobs.append(dict(
                    title=title,
                    org=slug.replace("-"," ").title(),
                    location=j.get("location",{}).get("name",""),
                    url=j.get("absolute_url",""),
                    score=s, source="Greenhouse", bucket=bucket,
                    posted=fmt_date(j.get("updated_at",""))
                ))
    return jobs

def themuse():
    jobs = []
    for page in range(3):
        data = fetch(f"https://www.themuse.com/api/public/jobs?page={page}&category=Science+and+Engineering&level=Senior+Level&level=Mid+Level")
        if not data: break
        try: results = json.loads(data).get("results", [])
        except: break
        for j in results:
            title = j.get("name","")
            org   = j.get("company",{}).get("name","") if isinstance(j.get("company"), dict) else ""
            contents = j.get("contents", [])
            desc = clean(" ".join(c if isinstance(c,str) else c.get("body","") for c in (contents if isinstance(contents,list) else [contents])))
            link = j.get("refs",{}).get("landing_page","") if isinstance(j.get("refs"),dict) else ""
            locs = ", ".join(l.get("name","") for l in j.get("locations",[]) if isinstance(l,dict)) or "See listing"
            if not is_relevant(f"{title} {desc}"): continue
            s = score_job(title, desc, org)
            if s >= 3:
                jobs.append(dict(title=title, org=org, location=locs, url=link, score=s, source="The Muse", bucket="industry",
                                 posted=fmt_date(j.get("publication_date",""))))
    return jobs

def remoteok():
    jobs = []
    for tag in ["biotech","biology","bioinformatics"]:
        data = fetch(f"https://remoteok.com/api?tag={tag}")
        if not data: continue
        try: items = json.loads(data)
        except: continue
        for j in items:
            if not isinstance(j,dict) or "position" not in j: continue
            title, org = j.get("position",""), j.get("company","")
            desc  = clean(j.get("description","")) + " " + " ".join(j.get("tags",[]))
            if not is_relevant(f"{title} {desc}"): continue
            s = score_job(title, desc, org)
            if s >= 3:
                jobs.append(dict(title=title, org=org, location="Remote", url=j.get("url",""), score=s, source="RemoteOK", bucket="industry",
                                 posted=fmt_date(j.get("date",""))))
    return jobs

def ashby(slugs, bucket="industry", min_score=3):
    """Fetch jobs from Ashby-hosted boards (used by insitro, Relation Therapeutics, etc.)."""
    jobs = []
    for slug in slugs:
        data = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(slug)}")
        if not data: continue
        try: items = json.loads(data).get("jobPostings", [])
        except: continue
        for j in items:
            title  = j.get("title","")
            org    = slug.replace("-"," ").title()
            loc    = j.get("locationName","") or j.get("location","")
            url    = j.get("jobUrl","")
            posted = fmt_date(j.get("publishedAt",""))
            desc   = clean(j.get("descriptionPlain","") or j.get("description",""))
            s = score_job(title, desc, slug)
            if s >= min_score and not any(b in f"{title} {desc}".lower() for b in TITLE_BAD):
                jobs.append(dict(title=title, org=org, location=loc, url=url,
                                 score=s, source="Ashby", bucket=bucket, posted=posted))
    return jobs

def workable(slugs, bucket="industry"):
    """Fetch jobs from Workable-hosted boards."""
    jobs = []
    for slug in slugs:
        data = fetch(f"https://apply.workable.com/api/v1/widget/accounts/{slug}/jobs")
        if not data: continue
        try: items = json.loads(data).get("jobs", [])
        except: continue
        for j in items:
            title  = j.get("title","")
            loc    = j.get("location",{})
            location = f'{loc.get("city","")}, {loc.get("region","")} {loc.get("country","")}'.strip(", ")
            url    = j.get("url","") or f"https://apply.workable.com/{slug}/j/{j.get('shortcode','')}"
            posted = fmt_date(j.get("created_at",""))
            desc   = clean(j.get("description","") or j.get("full_description",""))
            s = score_job(title, desc, slug)
            if s >= 4:
                jobs.append(dict(title=title, org=slug.replace("-"," ").title(),
                                 location=location, url=url, score=s,
                                 source="Workable", bucket=bucket, posted=posted))
    return jobs

def lever(slugs, bucket="industry"):
    """Fetch jobs from Lever-hosted boards (many biotech startups use Lever)."""
    jobs = []
    for slug in slugs:
        data = fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not data: continue
        try: items = json.loads(data)
        except: continue
        if not isinstance(items, list): continue
        for j in items:
            title = j.get("text","")
            org   = j.get("team","") or slug.replace("-"," ").title()
            desc  = clean(j.get("descriptionPlain","") or j.get("description",""))
            loc   = j.get("categories",{}).get("location","") if isinstance(j.get("categories"),dict) else ""
            url   = j.get("hostedUrl","")
            posted = fmt_date(str(j.get("createdAt","")//1000) if j.get("createdAt") else "")
            s = score_job(title, desc, slug)
            if s >= 3:
                jobs.append(dict(title=title, org=slug.replace("-"," ").title(),
                                 location=loc, url=url, score=s,
                                 source="Lever", bucket=bucket, posted=posted))
    return jobs

def linkedin():
    """Scrape LinkedIn public guest job search (no login required)."""
    LINKEDIN_HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    queries = [
        "single cell genomics",
        "brain organoid stem cell",
        "bioinformatics scientist neuroscience",
        "ipsc developmental biology",
    ]
    jobs, seen_ids = [], set()
    for q in queries:
        for start in range(0, 75, 25):   # 3 pages × 25 = up to 75 results per query
            params = urllib.parse.urlencode({
                "keywords": q,
                "location": "United States",
                "f_TPR": "r2592000",  # posted in last 30 days
                "start": start,
            })
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{params}"
            try:
                req = urllib.request.Request(url, headers=LINKEDIN_HEADERS)
                with urllib.request.urlopen(req, timeout=20) as r:
                    html = r.read().decode("utf-8", errors="ignore")
            except Exception as e:
                print(f"  LinkedIn skip ({q} start={start}) — {e}")
                break
            if not html.strip():
                break

            # Each job card is a <li> block; pull fields with regex
            for card in re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL):
                # Job ID / URL
                id_m = re.search(r'data-entity-urn="[^"]*:(\d+)"', card)
                url_m = re.search(r'href="(https://www\.linkedin\.com/jobs/view/[^"?]+)', card)
                job_url = url_m.group(1) if url_m else ""
                job_id  = id_m.group(1) if id_m else job_url
                if not job_id or job_id in seen_ids: continue
                seen_ids.add(job_id)

                title_m = re.search(r'class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+)', card)
                org_m   = re.search(r'class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)', card)
                loc_m   = re.search(r'class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([^<]+)', card)
                date_m  = re.search(r'<time[^>]*datetime="([^"]+)"', card)

                title    = title_m.group(1).strip() if title_m else ""
                org      = org_m.group(1).strip()   if org_m   else ""
                location = loc_m.group(1).strip()   if loc_m   else ""
                posted   = fmt_date(date_m.group(1)) if date_m else ""

                if not title: continue
                if not is_relevant(f"{title} {org}"): continue
                s = score_job(title, "", org)
                if s >= 4:
                    # Determine bucket: academia keywords → academia, else industry
                    bucket = "academia" if any(k in f"{title} {org}".lower()
                        for k in ["universit","college","institute","professor","postdoc","faculty","hospital","research center"]) else "industry"
                    jobs.append(dict(title=title, org=org, location=location,
                                     url=job_url, score=s, source="LinkedIn", bucket=bucket, posted=posted))
            time.sleep(2)   # be polite between pages
    return jobs

# ── HTML ──────────────────────────────────────────────────────────────────────

def build_html(academia, industry, featured, today):
    total = len(academia) + len(industry) + len(featured)

    def badge(s):
        color = "#16a34a" if s>=8 else "#d97706" if s>=6 else "#dc2626"
        return f'<span style="background:{color};color:#fff;padding:2px 7px;border-radius:9px;font-size:11px;font-weight:700">{s}/10</span>'

    def table_rows(jobs):
        if not jobs:
            return '<tr><td colspan="4" style="padding:14px;color:#94a3b8;text-align:center">No matches above threshold today.</td></tr>'
        rows = ""
        for i,j in enumerate(jobs,1):
            subtitle = j.get("org","")
            if subtitle and j.get("location"): subtitle += f'&nbsp;&middot;&nbsp;{j["location"]}'
            if j.get("posted"): subtitle += f'{"&nbsp;&middot;&nbsp;" if subtitle else ""}Posted {j["posted"]}'
            rows += (
                f'<tr style="border-bottom:1px solid #f1f5f9">'
                f'<td style="padding:9px 6px;color:#94a3b8;font-size:12px">{i}</td>'
                f'<td style="padding:9px 6px"><a href="{j["url"]}" style="color:#1d4ed8;font-weight:600;text-decoration:none">{j["title"]}</a>'
                + (f'<br><span style="color:#64748b;font-size:12px">{subtitle}</span>' if subtitle else "")
                + f'</td><td style="padding:9px 6px;text-align:center">{badge(j["score"])}</td>'
                f'<td style="padding:9px 6px;color:#94a3b8;font-size:11px">{j["source"]}</td></tr>'
            )
        return rows

    def section(emoji, label, jobs, color):
        return (
            f'<h2 style="color:{color};font-size:15px;margin:26px 0 8px">{emoji} {label}</h2>'
            f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr style="background:#f8fafc">'
            f'<th style="padding:7px 6px;text-align:left;font-size:11px;color:#94a3b8">#</th>'
            f'<th style="padding:7px 6px;text-align:left;font-size:11px;color:#94a3b8">POSITION</th>'
            f'<th style="padding:7px 6px;text-align:center;font-size:11px;color:#94a3b8">FIT</th>'
            f'<th style="padding:7px 6px;text-align:left;font-size:11px;color:#94a3b8">SOURCE</th>'
            f'</tr></thead><tbody>{table_rows(jobs)}</tbody></table>'
        )

    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif">'
        '<div style="max-width:680px;margin:20px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">'
        '<div style="background:#0f172a;padding:22px 26px">'
        '<h1 style="color:#fff;margin:0;font-size:17px;font-weight:700">Job Leads for Dr. K</h1>'
        f'<p style="color:#94a3b8;margin:5px 0 0;font-size:13px">{today} - {total} opportunities found</p>'
        '</div>'
        f'<div style="padding:6px 26px 26px">'
        + section("🎓", "Academia", academia, "#1d4ed8")
        + section("🏢", "Industry", industry, "#7c3aed")
        + section("🤖", "AI &amp; Neurotech", featured, "#0891b2")
        + '<p style="color:#cbd5e1;font-size:11px;margin-top:24px;text-align:center">'
        'Scored on: single-cell genomics, organoids, stem cells, brain development, seniority fit'
        '</p></div></div></body></html>'
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%B %d, %Y")
    print(f"Job Scout - {today}")

    jobs = []

    print("Science Careers RSS...")
    jobs += rss_jobs("https://jobs.sciencecareers.org/jobsrss/", "Science Careers", "academia")

    print("Nature Careers RSS...")
    jobs += rss_jobs("https://www.nature.com/naturejobs/rss/sciencejobs", "Nature Careers", "academia")

    print("BioSpace RSS...")
    jobs += rss_jobs("https://jobs.biospace.com/jobsrss/?countrycode=US", "BioSpace", "industry")

    print("HigherEdJobs...")
    for q in ["single cell genomics stem cell faculty", "neuroscience organoid assistant professor"]:
        url = f"https://www.higheredjobs.com/search/advanced_action.cfm?Keywords={urllib.parse.quote(q)}&PosType=1&InstType=1&Submit=Search+Jobs"
        content = fetch(url)
        for m in re.finditer(r'href="((?:/faculty/|/research/)details\.cfm\?JobCode=\d+)"[^>]*>\s*([^<]{10,})', content):
            s = score_job(m.group(2).strip(), "")
            if s >= 3:
                jobs.append(dict(title=m.group(2).strip(), org="University", location="", url=f"https://www.higheredjobs.com{m.group(1)}", score=s, source="HigherEdJobs", bucket="academia", posted=""))

    print("Greenhouse (institutes + academia)...")
    jobs += greenhouse(["arcinstitute","chanzuckerberginitiative","altoslabs","newlimit"], "academia")

    print("Greenhouse (biotech)...")
    jobs += greenhouse([
        "10xgenomics","calicolabs","abcellera","dynotherapeutics","cellarity",
        "recursionpharmaceuticals","OctantBio",
    ])

    print("Ashby (biotech startups)...")
    jobs += ashby(["insitro","relationrx","cohere"])

    print("AI & Neurotech (featured)...")
    featured_raw = []
    featured_raw += greenhouse(["anthropic","deepmind"], min_score=0)
    featured_raw += ashby(["openai","Merge Labs"], min_score=0)

    print("Lever (biotech startups)...")
    jobs += lever(["ScaleBio"])

    print("The Muse...")
    jobs += themuse()

    print("RemoteOK...")
    jobs += remoteok()

    print("LinkedIn...")
    jobs += linkedin()

    # Deduplicate main jobs
    seen, unique = set(), []
    for j in jobs:
        k = j["url"] or j["title"]
        if k not in seen:
            seen.add(k); unique.append(j)

    unique.sort(key=lambda x: x["score"], reverse=True)
    academia = [j for j in unique if j["bucket"]=="academia"]
    industry = [j for j in unique if j["bucket"]=="industry"]
    a_out = academia[:15]
    i_out = industry[:15]

    # Deduplicate and sort featured companies
    seen_f, featured = set(), []
    for j in sorted(featured_raw, key=lambda x: x["score"], reverse=True):
        k = j["url"] or j["title"]
        if k not in seen_f and k not in seen:
            seen_f.add(k); featured.append(j)

    print(f"{len(a_out)} academia, {len(i_out)} industry, {len(featured)} featured leads")

    html = build_html(a_out, i_out, featured, today)
    with open("email_body.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Wrote email_body.html")

if __name__ == "__main__":
    main()
