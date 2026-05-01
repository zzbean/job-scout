#!/usr/bin/env python3
"""
Job Scout for Sabina Kanton
Scrapes job boards, scores listings, writes ranked HTML to email_body.html
Email is sent by the GitHub Actions workflow (dawidd6/action-send-mail).
"""

import json, datetime, time, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from html import unescape

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

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

# ── Sources ───────────────────────────────────────────────────────────────────

def rss_jobs(url, source, bucket):
    jobs, content = [], fetch(url)
    if not content: return jobs
    for item in re.findall(r"<item[^>]*>(.*?)</item>", content, re.DOTALL):
        def g(tag):
            m = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", item, re.DOTALL|re.IGNORECASE)
            return clean(m.group(1)) if m else ""
        title, link, desc = g("title"), g("link") or g("guid"), g("description")
        if not is_relevant(f"{title} {desc}"): continue
        s = score_job(title, desc)
        if s > 0:
            jobs.append(dict(title=title, org="", location="", url=link, score=s, source=source, bucket=bucket))
    return jobs

def greenhouse(slugs, bucket="industry"):
    jobs = []
    for slug in slugs:
        data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not data: continue
        try: items = json.loads(data).get("jobs", [])
        except: continue
        for j in items:
            title = j.get("title","")
            s = score_job(title, clean(j.get("content","")), slug)
            if s >= 5:
                jobs.append(dict(
                    title=title,
                    org=slug.replace("-"," ").title(),
                    location=j.get("location",{}).get("name",""),
                    url=j.get("absolute_url",""),
                    score=s, source="Greenhouse", bucket=bucket
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
            if s >= 5:
                jobs.append(dict(title=title, org=org, location=locs, url=link, score=s, source="The Muse", bucket="industry"))
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
            if s >= 5:
                jobs.append(dict(title=title, org=org, location="Remote", url=j.get("url",""), score=s, source="RemoteOK", bucket="industry"))
    return jobs

# ── HTML ──────────────────────────────────────────────────────────────────────

def build_html(academia, industry, today):
    total = len(academia) + len(industry)

    def badge(s):
        color = "#16a34a" if s>=8 else "#d97706" if s>=6 else "#dc2626"
        return f'<span style="background:{color};color:#fff;padding:2px 7px;border-radius:9px;font-size:11px;font-weight:700">{s}/10</span>'

    def table_rows(jobs):
        if not jobs:
            return '<tr><td colspan="4" style="padding:14px;color:#94a3b8;text-align:center">No matches above threshold today.</td></tr>'
        rows = ""
        for i,j in enumerate(jobs,1):
            rows += (
                f'<tr style="border-bottom:1px solid #f1f5f9">'
                f'<td style="padding:9px 6px;color:#94a3b8;font-size:12px">{i}</td>'
                f'<td style="padding:9px 6px"><a href="{j["url"]}" style="color:#1d4ed8;font-weight:600;text-decoration:none">{j["title"]}</a>'
                + (f'<br><span style="color:#64748b;font-size:12px">{j["org"]}{"&nbsp;&middot;&nbsp;"+j["location"] if j["location"] else ""}</span>' if j["org"] else "")
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
        '<h1 style="color:#fff;margin:0;font-size:17px;font-weight:700">Job Leads for Sabina Kanton</h1>'
        f'<p style="color:#94a3b8;margin:5px 0 0;font-size:13px">{today} - {total} opportunities found</p>'
        '</div>'
        f'<div style="padding:6px 26px 26px">'
        + section("Academia", "Academia", academia, "#1d4ed8")
        + section("Industry", "Industry", industry, "#7c3aed")
        + '<p style="color:#cbd5e1;font-size:11px;margin-top:24px;text-align:center">'
        'Scored on: single-cell genomics, organoids, stem cells, brain development, seniority fit'
        '</p></div></div></body></html>'
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    print(f"Job Scout - {today}")

    jobs = []

    print("Science Careers RSS...")
    jobs += rss_jobs("https://jobs.sciencecareers.org/jobsrss/", "Science Careers", "academia")

    print("HigherEdJobs...")
    for q in ["single cell genomics stem cell faculty", "neuroscience organoid assistant professor"]:
        url = f"https://www.higheredjobs.com/search/advanced_action.cfm?Keywords={urllib.parse.quote(q)}&PosType=1&InstType=1&Submit=Search+Jobs"
        content = fetch(url)
        for m in re.finditer(r'href="((?:/faculty/|/research/)details\.cfm\?JobCode=\d+)"[^>]*>\s*([^<]{10,})', content):
            s = score_job(m.group(2).strip(), "")
            if s >= 3:
                jobs.append(dict(title=m.group(2).strip(), org="University", location="", url=f"https://www.higheredjobs.com{m.group(1)}", score=s, source="HigherEdJobs", bucket="academia"))

    print("Greenhouse (institutes)...")
    for j in greenhouse(["arcinstitute","chanzuckerberginitiative","altoslabs","newlimit"], "academia"):
        jobs.append(j)

    print("Greenhouse (biotech)...")
    jobs += greenhouse(["10xgenomics","calicolabs","abcellera","dynotherapeutics","cellarity"])

    print("The Muse...")
    jobs += themuse()

    print("RemoteOK...")
    jobs += remoteok()

    # Deduplicate
    seen, unique = set(), []
    for j in jobs:
        k = j["url"] or j["title"]
        if k not in seen:
            seen.add(k); unique.append(j)

    unique.sort(key=lambda x: x["score"], reverse=True)
    academia = [j for j in unique if j["bucket"]=="academia"]
    industry = [j for j in unique if j["bucket"]=="industry"]
    a_out = ([j for j in academia if j["score"]>=6] or academia[:5])[:10]
    i_out = ([j for j in industry if j["score"]>=6] or industry[:5])[:10]

    print(f"{len(a_out)} academia, {len(i_out)} industry leads")

    html = build_html(a_out, i_out, today)
    with open("email_body.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Wrote email_body.html")

if __name__ == "__main__":
    main()
