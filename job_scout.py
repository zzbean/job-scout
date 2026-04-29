#!/usr/bin/env python3
"""
Job Scout for Sabina Kanton
Scrapes 8+ job boards, scores against her profile, sends a ranked HTML digest via Resend.
"""

import os, json, datetime, time, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from html import unescape

# ── Config ────────────────────────────────────────────────────────────────────

RESEND_API_KEY = os.environ["RESEND_API_KEY"].strip()   # .strip() prevents header crash
TO_EMAIL       = "bianzhengzhen@gmail.com"
FROM_EMAIL     = "Job Scout <onboarding@resend.dev>"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

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
    text    = f"{title} {description} {org}".lower()
    title_l = title.lower()
    if any(b in text for b in TITLE_BAD):
        return 0.0
    if "10+ years" in text or "15+ years" in text:
        return 0.0
    s = 0.0
    if any(t in title_l for t in TITLE_BEST):
        s += 3.0
    elif any(t in title_l for t in TITLE_GOOD):
        s += 2.4
    elif any(t in title_l for t in TITLE_OK):
        s += 1.8
    else:
        s += 0.6
    hits  = sum(1 for sk in CORE_SKILLS    if sk in text)
    ahits = sum(1 for a  in RESEARCH_AREAS if a  in text)
    s += min(hits  * 1.0, 4.0)
    s += min(ahits * 0.5, 2.0)
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
                print(f"  ⚠  {url[:70]} — {e}")
    return ""

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", unescape(text or ""))[:800]

# ── Scrapers ──────────────────────────────────────────────────────────────────

def scrape_science_careers_rss():
    """AAAS Science Careers has a reliable public RSS feed."""
    jobs = []
    for q in ["single cell organoid stem cell",
              "neuroscience genomics faculty scientist",
              "brain development group leader"]:
        url = f"https://jobs.sciencecareers.org/rss/jobs/?keywords={urllib.parse.quote(q)}"
        content = fetch(url)
        if not content:
            continue
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            title  = strip_html(item.findtext("title", ""))
            link   = item.findtext("link", "")
            desc   = strip_html(item.findtext("description", ""))
            org    = strip_html(item.findtext("{http://www.w3.org/2005/Atom}author", "") or
                                item.findtext("author", ""))
            s = score_job(title, desc, org)
            if s > 0:
                jobs.append(dict(title=title, org=org or "See listing",
                                 location="See listing", url=link,
                                 score=s, source="Science Careers", bucket="academia"))
    return jobs


def scrape_nature_careers_rss():
    """Nature Careers RSS feed — more reliable than HTML scraping."""
    jobs = []
    for q in ["single cell organoid neuroscience",
              "stem cell brain development faculty"]:
        url = f"https://www.nature.com/naturecareers/jobs/rss?q={urllib.parse.quote(q)}"
        content = fetch(url)
        if not content:
            continue
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            title = strip_html(item.findtext("title", ""))
            link  = item.findtext("link", "")
            desc  = strip_html(item.findtext("description", ""))
            org   = strip_html(item.findtext("dc:creator", "") or "")
            s = score_job(title, desc, org)
            if s > 0:
                jobs.append(dict(title=title, org=org or "See listing",
                                 location="See listing", url=link,
                                 score=s, source="Nature Careers", bucket="academia"))
    return jobs


def scrape_higheredjobs():
    jobs = []
    for q in ["single cell genomics stem cell faculty",
              "neuroscience organoid assistant professor",
              "brain development genomics"]:
        url = (f"https://www.higheredjobs.com/search/advanced_action.cfm"
               f"?Keywords={urllib.parse.quote(q)}&PosType=1&InstType=1&Submit=Search+Jobs")
        content = fetch(url)
        if not content:
            continue
        # HigherEdJobs lists jobs in anchor tags linking to /faculty/ or /research/
        for m in re.finditer(
                r'href="((?:/faculty/|/research/|/admin/)details\.cfm\?JobCode=\d+)"[^>]*>\s*([^<]{10,})',
                content):
            path, title = m.group(1), m.group(2).strip()
            # Try to grab the institution name from surrounding text
            s = score_job(title, "", "")
            if s >= 3:
                jobs.append(dict(title=title, org="University (see listing)",
                                 location="See listing",
                                 url=f"https://www.higheredjobs.com{path}",
                                 score=s, source="HigherEdJobs", bucket="academia"))
    return jobs


def scrape_greenhouse(slugs):
    """
    Greenhouse public JSON API.
    Verified slugs for life-science companies — confirm at:
    https://boards.greenhouse.io/{slug}
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
        if not isinstance(data, list):
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


def scrape_remoteok():
    """RemoteOK has a free public JSON API — good for remote biotech/science roles."""
    jobs = []
    url = "https://remoteok.com/api?tag=biotech"
    content = fetch(url)
    if not content:
        return jobs
    try:
        data = json.loads(content)
    except Exception:
        return jobs
    for job in data:
        if not isinstance(job, dict) or "position" not in job:
            continue
        title = job.get("position", "")
        org   = job.get("company", "")
        desc  = strip_html(job.get("description", ""))
        link  = job.get("url", "")
        tags  = " ".join(job.get("tags", []))
        s = score_job(title, f"{desc} {tags}", org)
        if s >= 5:
            jobs.append(dict(title=title, org=org, location="Remote",
                             url=link, score=s,
                             source="RemoteOK", bucket="industry"))
    return jobs

# ── Email builder ─────────────────────────────────────────────────────────────

def build_email(academia, industry, today):
    total = len(academia) + len(industry)

    def score_badge(s):
        color = "#16a34a" if s >= 8 else "#d97706" if s >= 6 else "#dc2626"
        return (f'<span style="background:{color};color:#fff;padding:2px 8px;'
                f'border-radius:10px;font-size:11px;font-weight:700;">{s}/10</span>')

    def rows(jobs):
        if not jobs:
            return '<tr><td colspan="4" style="padding:16px;color:#94a3b8;text-align:center;">No matches above threshold today.</td></tr>'
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
        return f"""
        <h2 style="color:{accent};font-size:16px;margin:28px 0 8px;">{emoji} {label}</h2>
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f8fafc;">
              <th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;">#</th>
              <th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;">POSITION</th>
              <th style="padding:8px 6px;text-align:center;font-size:11px;color:#94a3b8;">FIT</th>
              <th style="padding:8px 6px;text-align:left;font-size:11px;color:#94a3b8;">SOURCE</th>
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
    <p style="color:#94a3b8;margin:6px 0 0;font-size:13px;">{today} &nbsp;·&nbsp; {total} opportunities found</p>
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
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={
            "Authorization": "Bearer " + RESEND_API_KEY,
            "Content-Type":  "application/json",
        })
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
        print(f"✅  Email sent — id: {result.get('id')}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    print(f"🔍  Job Scout — {today}\n")

    all_jobs = []

    # ── Academia ──────────────────────────────────────────────────────────────
    print("→ Science Careers (AAAS) RSS …")
    all_jobs += scrape_science_careers_rss()

    print("→ Nature Careers RSS …")
    all_jobs += scrape_nature_careers_rss()

    print("→ HigherEdJobs …")
    all_jobs += scrape_higheredjobs()

    # Research institutes on Greenhouse (academic bucket)
    print("→ Greenhouse (institutes) …")
    academic_gh = scrape_greenhouse([
        "hhmi",                   # Howard Hughes Medical Institute
        "broadinstitute",         # Broad Institute
        "chanzuckerberginitiative",
        "czbiohubsf",             # CZ Biohub SF
        "arcinstitute",           # Arc Institute (Patrick Collison)
        "newlimit",               # New Limit (epigenetics/aging)
        "altoslabs",              # Altos Labs
    ])
    for j in academic_gh:
        j["bucket"] = "academia"
    all_jobs += academic_gh

    # ── Industry ──────────────────────────────────────────────────────────────
    print("→ Greenhouse (biotech) …")
    all_jobs += scrape_greenhouse([
        "10xgenomics",
        "vizgen",
        "fluent-biosciences",
        "scale-biosciences",
        "parse-biosciences",
        "nanostring",
        "pacificbiosciences",
        "abcellera",
        "pioneerbiopharma",
        "vividion",
    ])

    print("→ Lever (biotech) …")
    all_jobs += scrape_lever([
        "sana-biotechnology",
        "laronde",
        "encoded-therapeutics",
        "vividion-therapeutics",
        "flagship-pioneering",
        "cellarity",
        "dynotx",
    ])

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
