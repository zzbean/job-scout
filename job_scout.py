#!/usr/bin/env python3
"""
Job Scout for Sabina Kanton
Scrapes 8+ job boards, scores against her profile, sends a ranked HTML digest via Resend.
"""

import os, json, datetime, time, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from html import unescape

# ── Config ────────────────────────────────────────────────────────────────────

RESEND_API_KEY = os.environ["RESEND_API_KEY"]
TO_EMAIL       = "bianzhengzhen@gmail.com"
FROM_EMAIL     = "Job Scout <onboarding@resend.dev>"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

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
TITLE_BEST  = ["assistant professor", "associate professor", "group leader",
               "staff scientist", "senior scientist", "principal scientist"]
TITLE_GOOD  = ["research scientist", "scientist ii", "scientist iii"]
TITLE_OK    = ["scientist", "researcher"]
TITLE_BAD   = ["technician", "lab tech", "undergraduate", "phd student",
               "vp ", "vice president", "director of sales", "marketing manager",
               "administrative", "coordinator"]

def score_job(title, description, org=""):
    text  = f"{title} {description} {org}".lower()
    title_l = title.lower()

    # Hard filter
    if any(b in text for b in TITLE_BAD):
        return 0.0
    if "10+ years" in text or "15+ years" in text:
        return 0.0

    s = 0.0

    # Title (30 %)
    if any(t in title_l for t in TITLE_BEST):
        s += 3.0
    elif any(t in title_l for t in TITLE_GOOD):
        s += 2.4
    elif any(t in title_l for t in TITLE_OK):
        s += 1.8
    else:
        s += 0.6

    # Core skills (40 %)
    hits = sum(1 for sk in CORE_SKILLS if sk in text)
    s += min(hits * 1.0, 4.0)

    # Research area (20 %)
    ahits = sum(1 for a in RESEARCH_AREAS if a in text)
    s += min(ahits * 0.5, 2.0)

    # Seniority fit (10 %)
    if any(t in title_l for t in ["senior", "principal", "staff", "professor", "group leader"]):
        s += 1.0
    elif "scientist" in title_l or "researcher" in title_l:
        s += 0.7
    else:
        s += 0.3

    return round(min(s, 10.0), 1)

# ── Helpers ───────────────────────────────────────────────────────────────────

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
                print(f"  ⚠  {url[:60]} — {e}")
    return ""

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", unescape(text or ""))[:800]

# ── Scrapers ──────────────────────────────────────────────────────────────────

def scrape_indeed_rss(queries, bucket):
    jobs = []
    for q in queries:
        url = (f"https://www.indeed.com/rss?q={urllib.parse.quote(q)}"
               f"&sort=date&fromage=7&limit=25")
        content = fetch(url)
        if not content:
            continue
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            raw_title = item.findtext("title", "")
            link      = item.findtext("link",  "")
            desc      = strip_html(item.findtext("description", ""))
            # "Title - Company" format
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title, org = parts[0].strip(), parts[1].strip()
            else:
                title, org = raw_title.strip(), ""
            s = score_job(title, desc, org)
            if s > 0:
                jobs.append(dict(title=title, org=org, location="See listing",
                                 url=link, score=s, source="Indeed", bucket=bucket))
    return jobs


def scrape_greenhouse(slugs):
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
        for job in data.get("jobs", []):
            title = job.get("title", "")
            loc   = job.get("location", {}).get("name", "")
            link  = job.get("absolute_url", "")
            desc  = strip_html(job.get("content", ""))
            s = score_job(title, desc, slug)
            if s >= 5:
                jobs.append(dict(title=title,
                                 org=slug.replace("-", " ").title(),
                                 location=loc, url=link, score=s,
                                 source="Greenhouse", bucket="industry"))
    return jobs


def scrape_lever(slugs):
    jobs = []
    for slug in slugs:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        content = fetch(url)
        if not content:
            continue
        try:
            data = json.loads(content)
        except Exception:
            continue
        for job in data:
            title = job.get("text", "")
            loc   = job.get("categories", {}).get("location", "")
            link  = job.get("hostedUrl", "")
            desc  = strip_html(job.get("descriptionPlain", ""))
            s = score_job(title, desc, slug)
            if s >= 5:
                jobs.append(dict(title=title,
                                 org=slug.replace("-", " ").title(),
                                 location=loc, url=link, score=s,
                                 source="Lever", bucket="industry"))
    return jobs


def scrape_higheredjobs():
    jobs = []
    for q in ["single cell genomics stem cell faculty",
              "neuroscience organoid assistant professor"]:
        url = (f"https://www.higheredjobs.com/search/advanced_action.cfm"
               f"?Keywords={urllib.parse.quote(q)}&PosType=1&InstType=1&Submit=Search+Jobs")
        content = fetch(url)
        for m in re.finditer(
                r'href="(/(?:faculty|research)/details\.cfm\?JobCode=\d+)"[^>]*>\s*([^<]+)',
                content):
            path, title = m.group(1), m.group(2).strip()
            s = score_job(title, "", "")
            if s >= 4:
                jobs.append(dict(title=title, org="University (see listing)",
                                 location="See listing",
                                 url=f"https://www.higheredjobs.com{path}",
                                 score=s, source="HigherEdJobs", bucket="academia"))
    return jobs


def scrape_nature_careers():
    jobs = []
    for q in ["single cell organoid neuroscience faculty",
              "stem cell brain development group leader scientist"]:
        url = (f"https://www.nature.com/naturecareers/jobs/search"
               f"?q={urllib.parse.quote(q)}&locationId=&locationName=&discipline=")
        content = fetch(url)
        for m in re.finditer(
                r'data-job-id="\d+"[^>]*>.*?'
                r'"jobTitle"[^>]*>([^<]+)<.*?'
                r'"employerName"[^>]*>([^<]+)<.*?'
                r'"jobLocation"[^>]*>([^<]+)<.*?'
                r'href="(/naturecareers/jobs/\d+[^"]*)"',
                content, re.S):
            title = m.group(1).strip()
            org   = m.group(2).strip()
            loc   = m.group(3).strip()
            link  = "https://www.nature.com" + m.group(4)
            s = score_job(title, "", org)
            if s >= 4:
                jobs.append(dict(title=title, org=org, location=loc,
                                 url=link, score=s,
                                 source="Nature Careers", bucket="academia"))
    return jobs

# ── Email builder ─────────────────────────────────────────────────────────────

def build_email(academia, industry, today):
    total = len(academia) + len(industry)

    def score_badge(s):
        color = "#16a34a" if s >= 8 else "#d97706" if s >= 6 else "#dc2626"
        return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;">{s}/10</span>'

    def rows(jobs):
        out = ""
        for i, j in enumerate(jobs, 1):
            out += f"""
            <tr style="border-bottom:1px solid #f1f5f9;">
              <td style="padding:10px 6px;color:#94a3b8;font-size:12px;">{i}</td>
              <td style="padding:10px 6px;">
                <a href="{j['url']}" style="color:#1d4ed8;font-weight:600;text-decoration:none;font-size:14px;">{j['title']}</a><br>
                <span style="color:#64748b;font-size:12px;">{j['org']} · {j['location']}</span>
              </td>
              <td style="padding:10px 6px;text-align:center;">{score_badge(j['score'])}</td>
              <td style="padding:10px 6px;color:#94a3b8;font-size:11px;">{j['source']}</td>
            </tr>"""
        return out

    def section(emoji, label, jobs, accent):
        if not jobs:
            return f'<h2 style="color:{accent};font-size:16px;margin:28px 0 8px;">{emoji} {label}</h2><p style="color:#94a3b8;font-size:13px;">No matches above threshold today.</p>'
        return f"""
        <h2 style="color:{accent};font-size:16px;margin:28px 0 8px;">{emoji} {label}</h2>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f8fafc;">
              <th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;font-weight:600;">#</th>
              <th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;font-weight:600;">POSITION</th>
              <th style="padding:8px 6px;text-align:center;font-size:11px;color:#94a3b8;font-weight:600;">FIT</th>
              <th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;font-weight:600;">SOURCE</th>
            </tr>
          </thead>
          <tbody>{rows(jobs)}</tbody>
        </table>"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:680px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
  <div style="background:#0f172a;padding:24px 28px;">
    <h1 style="color:#fff;margin:0;font-size:18px;font-weight:700;">🔬 Job Leads for Sabina Kanton</h1>
    <p style="color:#94a3b8;margin:6px 0 0;font-size:13px;">{today} &nbsp;·&nbsp; {total} opportunities across 8+ sources</p>
  </div>
  <div style="padding:8px 28px 28px;">
    {section("🎓", "Academia", academia, "#1d4ed8")}
    {section("🏭", "Industry", industry, "#7c3aed")}
    <p style="color:#cbd5e1;font-size:11px;margin-top:28px;text-align:center;">
      Scored on: single-cell genomics · organoids · stem cells · brain development · seniority fit
    </p>
  </div>
</div>
</body></html>"""

# ── Send ──────────────────────────────────────────────────────────────────────

def send_email(html, today):
    payload = json.dumps({
        "from":    FROM_EMAIL,
        "to":      [TO_EMAIL],
        "subject": f"🔬 Job Leads for Sabina Kanton — {today}",
        "html":    html,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
        print(f"✅  Email sent — id: {result.get('id')}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    print(f"🔍  Job Scout — {today}\n")

    all_jobs = []

    # Academia
    print("→ Nature Careers …");       all_jobs += scrape_nature_careers()
    print("→ HigherEdJobs …");         all_jobs += scrape_higheredjobs()
    print("→ Indeed (academia) …");    all_jobs += scrape_indeed_rss([
        "assistant professor single cell neuroscience organoid",
        "group leader brain organoid stem cell genomics",
        "faculty single cell sequencing developmental biology",
    ], bucket="academia")

    # Industry — Greenhouse companies
    print("→ Greenhouse boards …");    all_jobs += scrape_greenhouse([
        "10xgenomics", "genentech", "calico", "recursion",
        "benchling", "czbiohuborg", "insitro", "cellarity",
        "arctusbio", "miltenyi", "vizgen", "parse-biosciences",
        "singleron", "scale-biosciences",
    ])

    # Industry — Lever companies
    print("→ Lever boards …");         all_jobs += scrape_lever([
        "calicolabs", "insitro", "recursion", "dyno",
        "cellarity", "encoded-therapeutics", "vivterapeutics",
    ])

    # Industry — broad Indeed
    print("→ Indeed (industry) …");    all_jobs += scrape_indeed_rss([
        "scientist single cell genomics organoid biotech",
        "senior scientist stem cell brain organoid pharma",
        "computational biologist single cell sequencing",
    ], bucket="industry")

    # Deduplicate on URL
    seen, unique = set(), []
    for j in all_jobs:
        key = j["url"] or j["title"]
        if key not in seen:
            seen.add(key); unique.append(j)

    unique.sort(key=lambda x: x["score"], reverse=True)

    academia = [j for j in unique if j["bucket"] == "academia"]
    industry = [j for j in unique if j["bucket"] == "industry"]

    # Ensure at least 5 per bucket, cap at 10
    a_out = [j for j in academia if j["score"] >= 6] or academia[:5]
    i_out = [j for j in industry if j["score"] >= 6] or industry[:5]
    a_out, i_out = a_out[:10], i_out[:10]

    print(f"\n📊  {len(a_out)} academia · {len(i_out)} industry leads selected\n")

    html = build_email(a_out, i_out, today)
    send_email(html, today)


if __name__ == "__main__":
    main()
