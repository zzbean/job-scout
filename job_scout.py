#!/usr/bin/env python3
"""
Job Scout for Sabina Kanton — v3
All sources verified working before inclusion.
"""

import os, sys, json, datetime, time, re, urllib.request, urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET
from html import unescape

# ── Config ────────────────────────────────────────────────────────────────────

GMAIL_FROM         = os.environ["GMAIL_FROM"].strip()
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"].strip()
TO_EMAIL           = "bianzhengzhen@gmail.com"
HEADERS        = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Scoring ───────────────────────────────────────────────────────────────────

CORE_SKILLS = [
    "single-cell", "single cell", "scrna-seq", "scrna", "rna-seq",
    "organoid", "brain organoid", "cerebral organoid",
    "pluripotent", "ipsc", "esc", "stem cell",
]
RESEARCH_AREAS = [
    "brain", "neural", "neuroscience", "neurodevelopment",
    "primate", "human evolution", "comparative genomic",
    "developmental biology", "cell lineage", "organogenesis",
    "seurat", "scanpy", "bioinformatic",
]
TITLE_BEST = ["assistant professor", "associate professor", "group leader",
              "staff scientist", "senior scientist", "principal scientist"]
TITLE_GOOD = ["research scientist", "scientist ii", "scientist iii", "scientist, "]
TITLE_OK   = ["scientist", "researcher"]
TITLE_BAD  = ["technician", "lab tech", "undergraduate", "phd student",
              "vp ", "vice president", "director of sales", "marketing",
              "administrative", "coordinator", "recruiter", "accountant"]

# Pre-filter: RSS feeds return ALL jobs; only score items containing these terms
RSS_RELEVANCE = [
    "single cell", "organoid", "stem cell", "ipsc", "genomic",
    "bioinformat", "sequencing", "neuroscience", "developmental biology",
    "cell biology", "biochemistry", "molecular biology",
]

def is_relevant(text):
    t = text.lower()
    return any(kw in t for kw in RSS_RELEVANCE)

def score_job(title, description, org=""):
    text    = f"{title} {description} {org}".lower()
    title_l = title.lower()
    if any(b in text for b in TITLE_BAD):
        return 0.0
    if "10+ years" in text or "15+ years" in text:
        return 0.0
    s = 0.0
    if   any(t in title_l for t in TITLE_BEST): s += 3.0
    elif any(t in title_l for t in TITLE_GOOD): s += 2.4
    elif any(t in title_l for t in TITLE_OK):   s += 1.8
    else:                                         s += 0.6
    s += min(sum(1 for sk in CORE_SKILLS    if sk in text) * 1.0, 4.0)
    s += min(sum(1 for a  in RESEARCH_AREAS if a  in text) * 0.5, 2.0)
    if   any(t in title_l for t in ["senior","principal","staff","professor","group leader"]): s += 1.0
    elif "scientist" in title_l or "researcher" in title_l: s += 0.7
    else:                                                     s += 0.3
    return round(min(s, 10.0), 1)

# ── HTTP helper ───────────────────────────────────────────────────────────────

def fetch(url, retries=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                print(f"  ⚠  {url[:80]} — {e}")
    return ""

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", unescape(text or ""))[:600]

# ── Scrapers ──────────────────────────────────────────────────────────────────

def scrape_rss(url, source, bucket):
    """RSS parser using regex extraction — tolerates malformed namespaces."""
    jobs = []
    content = fetch(url)
    if not content:
        return jobs

    def first(pattern, text, default=""):
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return strip_html(m.group(1)) if m else default

    items = re.findall(r"<item[^>]*>(.*?)</item>", content, re.DOTALL)
    if not items:
        print(f"  ⚠  No <item> elements found in feed ({source})")
        return jobs

    for item_text in items:
        title = first(r"<title[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</title>", item_text)
        link  = first(r"<link[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</link>", item_text)
        if not link:
            link = first(r"<guid[^>]*>(.*?)</guid>", item_text)
        desc  = first(r"<description[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</description>", item_text)
        org   = (first(r"<(?:\w+:)?author[^>]*>(.*?)</(?:\w+:)?author>", item_text) or
                 first(r"<(?:\w+:)?creator[^>]*>(.*?)</(?:\w+:)?creator>", item_text))
        combined = f"{title} {desc}"
        if not is_relevant(combined):
            continue
        s = score_job(title, desc, org)
        if s > 0:
            jobs.append(dict(title=title, org=org or "See listing",
                             location="See listing", url=link,
                             score=s, source=source, bucket=bucket))
    return jobs


def scrape_greenhouse(slugs, bucket="industry"):
    """
    Greenhouse public JSON API.
    Slugs verified at boards.greenhouse.io/{slug} before inclusion.
    """
    jobs = []
    for slug in slugs:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        content = fetch(url)
        if not content:
            continue
        try:
            data = json.loads(content)
        except Exception:
            continue
        org = slug.replace("-", " ").title()
        for job in data.get("jobs", []):
            title = job.get("title", "")
            loc   = job.get("location", {}).get("name", "")
            link  = job.get("absolute_url", "")
            desc  = strip_html(job.get("content", ""))
            s = score_job(title, desc, org)
            if s >= 5:
                jobs.append(dict(title=title, org=org, location=loc,
                                 url=link, score=s,
                                 source="Greenhouse", bucket=bucket))
    return jobs


def scrape_higheredjobs():
    jobs = []
    queries = [
        "single cell genomics stem cell faculty",
        "neuroscience organoid assistant professor",
        "brain development genomics scientist",
    ]
    for q in queries:
        url = (f"https://www.higheredjobs.com/search/advanced_action.cfm"
               f"?Keywords={urllib.parse.quote(q)}&PosType=1&InstType=1&Submit=Search+Jobs")
        content = fetch(url)
        if not content:
            continue
        for m in re.finditer(
            r'href="((?:/faculty/|/research/|/admin/)details\.cfm\?JobCode=\d+)"[^>]*>\s*([^<]{10,})',
            content
        ):
            path, title = m.group(1), m.group(2).strip()
            s = score_job(title, "", "")
            if s >= 3:
                jobs.append(dict(title=title, org="University (see listing)",
                                 location="See listing",
                                 url=f"https://www.higheredjobs.com{path}",
                                 score=s, source="HigherEdJobs", bucket="academia"))
    return jobs


def scrape_themuse():
    """The Muse public API — free, no auth, returns Science & Engineering jobs."""
    jobs = []
    for page in range(3):   # pages 0-2 = up to 60 jobs
        url = (f"https://www.themuse.com/api/public/jobs?page={page}"
               f"&category=Science+and+Engineering&level=Senior+Level&level=Mid+Level")
        content = fetch(url)
        if not content:
            break
        try:
            data = json.loads(content)
        except Exception:
            break
        for job in data.get("results", []):
            title = job.get("name", "")
            org   = job.get("company", {}).get("name", "")
            link  = job.get("refs", {}).get("landing_page", "")
            contents = job.get("contents", [])
            if isinstance(contents, str):
                desc = strip_html(contents)
            else:
                desc = strip_html(" ".join(
                    c if isinstance(c, str) else c.get("body", "")
                    for c in contents
                ))
            locs  = ", ".join(
                l.get("name", "") for l in job.get("locations", [])
            ) or "See listing"
            if not is_relevant(f"{title} {desc}"):
                continue
            s = score_job(title, desc, org)
            if s >= 5:
                jobs.append(dict(title=title, org=org, location=locs,
                                 url=link, score=s,
                                 source="The Muse", bucket="industry"))
    return jobs


def scrape_remoteok():
    """RemoteOK free public API."""
    jobs = []
    for tag in ["biotech", "biology", "bioinformatics"]:
        url     = f"https://remoteok.com/api?tag={tag}"
        content = fetch(url)
        if not content:
            continue
        try:
            data = json.loads(content)
        except Exception:
            continue
        for job in data:
            if not isinstance(job, dict) or "position" not in job:
                continue
            title = job.get("position", "")
            org   = job.get("company", "")
            desc  = strip_html(job.get("description", ""))
            link  = job.get("url", "")
            tags  = " ".join(job.get("tags", []))
            if not is_relevant(f"{title} {desc} {tags}"):
                continue
            s = score_job(title, f"{desc} {tags}", org)
            if s >= 5:
                jobs.append(dict(title=title, org=org, location="Remote",
                                 url=link, score=s,
                                 source="RemoteOK", bucket="industry"))
    return jobs

# ── Email ─────────────────────────────────────────────────────────────────────

def build_email(academia, industry, today):
    total = len(academia) + len(industry)

    def badge(s):
        c = "#16a34a" if s >= 8 else "#d97706" if s >= 6 else "#dc2626"
        return (f'<span style="background:{c};color:#fff;padding:2px 8px;'
                f'border-radius:10px;font-size:11px;font-weight:700;">{s}/10</span>')

    def rows(jobs):
        if not jobs:
            return ('<tr><td colspan="4" style="padding:16px;color:#94a3b8;'
                    'text-align:center;">No matches above threshold today.</td></tr>')
        out = ""
        for i, j in enumerate(jobs, 1):
            out += (
                f'<tr style="border-bottom:1px solid #f1f5f9;">'
                f'<td style="padding:10px 6px;color:#94a3b8;font-size:12px;">{i}</td>'
                f'<td style="padding:10px 6px;">'
                f'<a href="{j["url"]}" style="color:#1d4ed8;font-weight:600;'
                f'text-decoration:none;font-size:14px;">{j["title"]}</a><br>'
                f'<span style="color:#64748b;font-size:12px;">'
                f'{j["org"]} · {j["location"]}</span></td>'
                f'<td style="padding:10px 6px;text-align:center;">{badge(j["score"])}</td>'
                f'<td style="padding:10px 6px;color:#94a3b8;font-size:11px;">'
                f'{j["source"]}</td></tr>'
            )
        return out

    def section(emoji, label, jobs, accent):
        thead = (
            '<thead><tr style="background:#f8fafc;">'
            '<th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;">#</th>'
            '<th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;">POSITION</th>'
            '<th style="padding:8px 6px;text-align:center;font-size:11px;color:#94a3b8;">FIT</th>'
            '<th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;">SOURCE</th>'
            '</tr></thead>'
        )
        return (
            f'<h2 style="color:{accent};font-size:16px;margin:28px 0 8px;">{emoji} {label}</h2>'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'{thead}<tbody>{rows(jobs)}</tbody></table>'
        )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#f1f5f9;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;">'
        '<div style="max-width:680px;margin:24px auto;background:#fff;'
        'border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">'
        '<div style="background:#0f172a;padding:24px 28px;">'
        '<h1 style="color:#fff;margin:0;font-size:18px;font-weight:700;">'
        '🔬 Job Leads for Sabina Kanton</h1>'
        f'<p style="color:#94a3b8;margin:6px 0 0;font-size:13px;">'
        f'{today} &nbsp;·&nbsp; {total} opportunities found</p>'
        '</div>'
        '<div style="padding:8px 28px 28px;">'
        + section("🎓", "Academia", academia, "#1d4ed8")
        + section("🏭", "Industry", industry, "#7c3aed")
        + '<p style="color:#cbd5e1;font-size:11px;margin-top:28px;text-align:center;">'
        'Scored on: single-cell genomics · organoids · stem cells · brain development</p>'
        '</div></div></body></html>'
    )


def send_email(html, today):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Leads for Sabina Kanton — {today}"
    msg["From"]    = GMAIL_FROM
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print("✅  Email sent via Gmail SMTP")
    except Exception as e:
        print(f"❌  Gmail SMTP error: {e}")
        sys.exit(1)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    print(f"🔍  Job Scout — {today}\n")

    all_jobs = []

    # ── Academia ──────────────────────────────────────────────────────────────
    # Science Careers RSS — verified URL: https://jobs.sciencecareers.org/jobsrss/
    print("→ Science Careers RSS …")
    all_jobs += scrape_rss(
        "https://jobs.sciencecareers.org/jobsrss/",
        source="Science Careers", bucket="academia"
    )

    # Nature Careers RSS (403 from GH Actions — skipping; Science Careers covers this bucket)
    # print("→ Nature Careers RSS …")
    # all_jobs += scrape_rss("https://www.nature.com/naturecareers/jobsrss/", ...)

    print("→ HigherEdJobs …")
    all_jobs += scrape_higheredjobs()

    # Research institutes — verified Greenhouse slugs
    print("→ Greenhouse (institutes) …")
    institute_jobs = scrape_greenhouse([
        "arcinstitute",             # Arc Institute
        "chanzuckerberginitiative", # Chan Zuckerberg Initiative
        "altoslabs",                # Altos Labs
        "newlimit",                 # New Limit
    ], bucket="academia")
    all_jobs += institute_jobs

    # ── Industry ──────────────────────────────────────────────────────────────
    print("→ Greenhouse (biotech) …")
    all_jobs += scrape_greenhouse([
        "10xgenomics",    # 10x Genomics
        "calicolabs",     # Calico (Google longevity)
        "abcellera",      # AbCellera
        "dynotherapeutics",  # Dyno Therapeutics
        "cellarity",      # Cellarity
    ], bucket="industry")

    print("→ The Muse …")
    all_jobs += scrape_themuse()

    print("→ RemoteOK …")
    all_jobs += scrape_remoteok()

    # ── Deduplicate & rank ────────────────────────────────────────────────────
    seen, unique = set(), []
    for j in all_jobs:
        key = j.get("url") or j["title"]
        if key not in seen:
            seen.add(key)
            unique.append(j)

    unique.sort(key=lambda x: x["score"], reverse=True)

    academia = [j for j in unique if j["bucket"] == "academia"]
    industry = [j for j in unique if j["bucket"] == "industry"]

    a_out = ([j for j in academia if j["score"] >= 6] or academia[:5])[:10]
    i_out = ([j for j in industry if j["score"] >= 6] or industry[:5])[:10]

    print(f"\n📊  {len(a_out)} academia · {len(i_out)} industry leads\n")

    html = build_email(a_out, i_out, today)
    send_email(html, today)


if __name__ == "__main__":
    main()
