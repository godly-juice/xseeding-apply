"""LUMI RESEARCHES EACH APPLICANT - only where they said yes (2026-11-02, the owner: "lumi should monitor this and research each applicant ...
do not make scrape mandatory ... don't be invasive and respect what xseeding stands for").
Every 60 s: new applications in data/queue.jsonl -> for each source the person ticked (consent.json 'allowed'):
  links   the pages they linked (public text only, 10 pages, 6k chars each)
  github  GitHub's public API: the user named in their GitHub link / handles (profile + 30 public repos + README of the top 5)
  web     one web search on the name + handles (public result pages, 5 hits)
  files   the uploaded files as text (PDF, txt/md, docx; images are listed, not read)
  google  Google Drive read-only: 40 most recent files (names) + the text of up to 8 Google Docs - only when they connected it
Nothing else is ever opened. The Worker 27B (local) writes lumi-research.md: summary, strengths, what they could own, questions to ask,
doubts, sources used, confidence. Copy -> Desktop\\x\\Workspaces\\Lumi\\team-applicants\\<id>\\ + a portal notice. Nothing is decided here.
Off switch: Desktop\\Lumi\\applicants-off.txt. Watchdog service "applicants"."""
import html
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
QUEUE = os.path.join(DATA, "queue.jsonl")
CONFIG_F = r"D:\Atlas\memory\apply-config.json"
OFF = os.path.join(os.path.expanduser("~"), "Desktop", "Lumi", "applicants-off.txt")
OUT_COPY = (json.load(open(CONFIG_F, encoding="utf8")).get("copy_dir") if os.path.exists(CONFIG_F) else "") or os.path.join(DATA, "reads")   # where the owner reads them
WRITER = "http://127.0.0.1:11447/v1/chat/completions"
WHO = "Lumi · Worker 27B (writer)"
UA = "Mozilla/5.0 (compatible; xSeeding-apply/1; +https://apply.xseed.ing/privacy)"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}, "strengths": {"type": "array", "items": {"type": "string"}},
                                           "could_own": {"type": "array", "items": {"type": "string"}}, "questions": {"type": "array", "items": {"type": "string"}},
                                           "doubts": {"type": "array", "items": {"type": "string"}}, "confidence": {"type": "string", "enum": ["low", "medium", "high"]}},
          "required": ["summary", "strengths", "could_own", "questions", "doubts", "confidence"], "additionalProperties": False}
SYSTEM = ("You are Lumi, helping a small team (local AI + its own operating system) read a job application. You get what the person wrote and ONLY the "
          "public material they allowed us to read. Be fair, concrete and short: no guesses about private life, no judging by age, looks, origin, "
          "gender or beliefs; judge what they built, finished, tested, wrote and how they communicate. Quote the source for each strength "
          "('(from GitHub repo X)'). 'questions' = 3-5 things a human should ask them. 'doubts' = only things the material actually shows. "
          "'confidence' = how much material there was. Under 350 words in all.")


def log(msg):
    with open(os.path.join(DATA, "research.log"), "a", encoding="utf8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")
    print(msg, flush=True)


def jload(p, d=None):
    try:
        return json.load(open(p, encoding="utf8"))
    except Exception:  # noqa: BLE001
        return d


def fetch(url, limit=6000, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(600_000)
        ct = r.headers.get("Content-Type", "")
    txt = raw.decode("utf8", "replace")
    if "html" in ct or txt.lstrip().startswith("<"):
        txt = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", txt)
        txt = re.sub(r"(?s)<[^>]+>", " ", txt)
        txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()[:limit]


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def github_user(rec):
    for s in rec.get("links", []) + re.split(r"[\s,]+", rec.get("handles", "")):
        m = re.search(r"github\.com/([A-Za-z0-9-]{1,39})(?:/|$)", s)
        if m:
            return m.group(1)
    return None


def src_links(rec):
    out = []
    for u in rec.get("links", [])[:10]:
        try:
            out.append("LINK %s\n%s" % (u, fetch(u)))
        except Exception as exc:  # noqa: BLE001
            out.append("LINK %s - could not read (%s)" % (u, type(exc).__name__))
    return "\n\n".join(out)


def src_github(rec):
    user = github_user(rec)
    if not user:
        return "GITHUB: no GitHub user in the links/handles"
    prof = gh("users/%s" % user) or {}
    repos = gh("users/%s/repos?sort=updated&per_page=30" % user) or []
    lines = ["GITHUB user %s: %s | %s | public repos %s | followers %s | since %s" % (user, prof.get("name"), (prof.get("bio") or "").strip(), prof.get("public_repos"), prof.get("followers"), str(prof.get("created_at"))[:10])]
    for r in repos[:30]:
        lines.append("- %s (%s, stars %s, updated %s): %s" % (r.get("name"), r.get("language"), r.get("stargazers_count"), str(r.get("pushed_at"))[:10], (r.get("description") or "")[:120]))
    for r in sorted(repos, key=lambda x: -(x.get("stargazers_count") or 0))[:5]:
        rd = gh("repos/%s/%s/readme" % (user, r.get("name")))
        if rd and rd.get("content"):
            import base64
            lines.append("README of %s:\n%s" % (r.get("name"), base64.b64decode(rd["content"]).decode("utf8", "replace")[:2500]))
    return "\n".join(lines)


def src_web(rec):
    q = (rec.get("name", "") + " " + rec.get("handles", "")).strip()
    try:
        sys.path.insert(0, r"D:\Atlas\tools")
        import atlas_tools as AT
        return "WEB SEARCH '%s':\n%s" % (q, AT.web_search(q, 5, show_window=False, who="APPLY")[:6000])
    except Exception as exc:  # noqa: BLE001
        try:
            u = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
            return "WEB SEARCH '%s' (results page):\n%s" % (q, fetch(u, 5000))
        except Exception as exc2:  # noqa: BLE001
            return "WEB SEARCH failed: %r / %r" % (exc, exc2)


def file_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md", ".csv", ".rtf"):
        return open(path, encoding="utf8", errors="replace").read()[:8000]
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages[:15])[:8000]
        except Exception as exc:  # noqa: BLE001
            return "(pdf not readable: %r)" % exc
    if ext in (".docx", ".pptx", ".xlsx", ".odt"):
        try:
            with zipfile.ZipFile(path) as z:
                parts = [n for n in z.namelist() if n.endswith(".xml") and ("document" in n or "slide" in n or "sheet" in n or n == "content.xml")]
                txt = " ".join(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf8", "replace")) for n in parts[:20])
                return re.sub(r"\s+", " ", html.unescape(txt))[:8000]
        except Exception as exc:  # noqa: BLE001
            return "(office file not readable: %r)" % exc
    return "(%s file, %d bytes - not read as text)" % (ext, os.path.getsize(path))


def src_files(d):
    out = []
    fd = os.path.join(d, "files")
    for fn in sorted(os.listdir(fd)) if os.path.isdir(fd) else []:
        out.append("FILE %s:\n%s" % (fn, file_text(os.path.join(fd, fn))))
    return "\n\n".join(out) or "FILES: none uploaded"


def src_google(d):
    g = jload(os.path.join(d, "google.json"))
    c = jload(CONFIG_F, {})
    if not g or not g.get("refresh_token"):
        return "GOOGLE: not connected"
    body = urllib.parse.urlencode({"client_id": c.get("google_client_id"), "client_secret": c.get("google_client_secret"), "refresh_token": g["refresh_token"], "grant_type": "refresh_token"}).encode()
    try:
        tok = json.load(urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=30))["access_token"]
    except Exception as exc:  # noqa: BLE001
        return "GOOGLE: token refresh failed (disconnected?) %r" % exc
    hdr = {"Authorization": "Bearer " + tok}
    try:
        lst = json.load(urllib.request.urlopen(urllib.request.Request("https://www.googleapis.com/drive/v3/files?pageSize=40&orderBy=modifiedTime desc&fields=files(id,name,mimeType,modifiedTime)", headers=hdr), timeout=30))
    except Exception as exc:  # noqa: BLE001
        return "GOOGLE: list failed %r" % exc
    lines = ["GOOGLE DRIVE (read-only, 40 most recent):"] + ["- %s (%s, %s)" % (f["name"], f["mimeType"].split(".")[-1], f["modifiedTime"][:10]) for f in lst.get("files", [])]
    n = 0
    for f in lst.get("files", []):
        if f["mimeType"] == "application/vnd.google-apps.document" and n < 8:
            n += 1
            try:
                t = urllib.request.urlopen(urllib.request.Request("https://www.googleapis.com/drive/v3/files/%s/export?mimeType=text/plain" % f["id"], headers=hdr), timeout=30).read().decode("utf8", "replace")
                lines.append("DOC %s:\n%s" % (f["name"], t[:5000]))
            except Exception:  # noqa: BLE001
                pass
    return "\n".join(lines)


def write(system, user):
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.2, "max_tokens": 900,
            "response_format": {"type": "json_schema", "json_schema": {"name": "r", "schema": SCHEMA}}}
    req = urllib.request.Request(WRITER, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        txt = json.load(r)["choices"][0]["message"]["content"]
    return json.loads(re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip())


def research(aid):
    d = os.path.join(DATA, aid)
    rec, con = jload(os.path.join(d, "application.json")), jload(os.path.join(d, "consent.json"), {})
    if not rec:
        return
    allowed = con.get("allowed", [])
    material = ["WHAT THEY WROTE:\nname/handle: %s\nreach: %s\nlinks: %s\nhandles: %s\n\n%s" % (rec["name"], rec["reach"], ", ".join(rec.get("links", [])), rec.get("handles", ""), rec["why"])]
    used = ["the application itself"]
    for k, fn in (("links", lambda: src_links(rec)), ("github", lambda: src_github(rec)), ("web", lambda: src_web(rec)), ("files", lambda: src_files(d)), ("google", lambda: src_google(d))):
        if k in allowed:
            try:
                material.append(fn()); used.append(k)
            except Exception as exc:  # noqa: BLE001
                material.append("%s: failed %r" % (k.upper(), exc))
    user = "SOURCES ALLOWED BY THE APPLICANT: %s\n\n%s" % (", ".join(used), "\n\n".join(material)[:60000])
    r = write(SYSTEM, user)
    md = ("# Lumi's first read of applicant %s - %s\n\nWritten by %s on %s. Sources the applicant allowed: %s. Not a decision - a human decides.\n\n"
          "**Summary:** %s\n\n**Strengths**\n%s\n\n**Could own on the team**\n%s\n\n**Questions to ask them**\n%s\n\n**Doubts (only what the material shows)**\n%s\n\n"
          "Confidence: %s\n\nDelete link (theirs): %s/delete/%s/%s\n"
          % (aid, rec["name"], WHO, time.strftime("%Y-%m-%d %H:%M"), ", ".join(used), r["summary"], "\n".join("- " + s for s in r["strengths"]) or "- (none named)",
             "\n".join("- " + s for s in r["could_own"]) or "- (none named)", "\n".join("- " + s for s in r["questions"]) or "- (none)", "\n".join("- " + s for s in r["doubts"]) or "- none",
             r["confidence"], jload(CONFIG_F, {}).get("public_url", ""), aid, rec.get("delete_token", "")))
    open(os.path.join(d, "lumi-research.md"), "w", encoding="utf8").write(md)
    rec["status"] = "researched"
    json.dump(rec, open(os.path.join(d, "application.json"), "w", encoding="utf8"), indent=1)
    out = os.path.join(OUT_COPY, "%s-%s" % (rec["at"][:10], aid))
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "lumi-research.md"), "w", encoding="utf8").write(md)
    json.dump({k: v for k, v in rec.items() if k not in ("delete_token", "google_token")}, open(os.path.join(out, "application.json"), "w", encoding="utf8"), indent=1)
    try:
        sys.path.insert(0, r"D:\Atlas\tools")
        import notify as N
        N.notify("Lumi read applicant %s" % rec["name"], "%s (confidence %s). Full read: %s\\lumi-research.md" % (r["summary"][:220], r["confidence"], out), "/")
    except Exception:  # noqa: BLE001
        pass
    log("researched %s (%s) with %s" % (aid, rec["name"], ", ".join(used)))


def main():
    os.makedirs(DATA, exist_ok=True)
    log("applicant research loop on (sources only by consent)")
    while True:
        if not os.path.exists(OFF):
            try:
                for ln in open(QUEUE, encoding="utf8") if os.path.exists(QUEUE) else []:
                    try:
                        aid = json.loads(ln)["id"]
                    except Exception:  # noqa: BLE001
                        continue
                    d = os.path.join(DATA, aid)
                    if os.path.isdir(d) and not os.path.exists(os.path.join(d, "lumi-research.md")):
                        try:
                            research(aid)
                        except Exception as exc:  # noqa: BLE001
                            log("research %s failed: %r" % (aid, exc))
                            open(os.path.join(d, "lumi-research.md"), "w", encoding="utf8").write("research failed: %r (the Director will look)\n" % exc)
            except Exception as exc:  # noqa: BLE001
                log("loop error %r" % exc)
        time.sleep(60)


if __name__ == "__main__":
    main()
