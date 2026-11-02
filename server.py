"""APPLY TO JOIN xSEEDING - apply.xseed.ing (2026-11-02, the owner, from the road: "a place for ppl to apply to join where they can drop files
and linkedin or whatever ... lumi should monitor this and research each applicant ... applicants are told an AI search will be performed ...
show where we will get the data exactly and allow them to check no or yes on things ... make it legal ... do not make scrape mandatory ...
open source the team part").
Standard library only. Public (through the tunnel): GET /, /privacy, /static/*, /api/config, POST /api/apply, GET /delete/<id>/<token>,
GET /google/start + /google/callback (only when Google OAuth is configured). Local only (Host 127.0.0.1): GET /admin, /admin/<id>/...
Every application = data/<id>/application.json + the files + consent.json (what the person allowed, with the time and the wording they saw).
Lumi's research (lumi_research.py, a separate loop) reads ONLY the sources the person ticked. Delete link = the whole folder goes.
Config: D:\\Atlas\\memory\\apply-config.json {public_url, contact_email, google_client_id, google_client_secret, keep_days}."""
import email.parser
import email.policy
import hashlib
import http.server
import io
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA = os.path.join(HERE, "data")
CONFIG_F = r"D:\Atlas\memory\apply-config.json"
PORT = 11594
MAX_FILE = 25 << 20
MAX_FILES = 5
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md", ".doc", ".docx", ".odt", ".rtf", ".csv", ".xlsx", ".pptx", ".zip", ".mp4", ".mov", ".mp3", ".wav"}
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
# the EXACT sources, in the words the applicant sees (saved with every consent so nobody can argue about what was agreed)
SOURCES = [
    ("links", "The links I typed in this form - you open those pages and read what is public there."),
    ("github", "My public GitHub: profile, public repositories, README files."),
    ("web", "A web search on my name and the handles I gave - you read the public pages that come up."),
    ("files", "The files I uploaded here."),
    ("google", "My Google Drive, read-only, only while connected (I can disconnect any time) - only if I connect it below."),
]
RATE = {}


def cfg():
    try:
        return json.load(open(CONFIG_F, encoding="utf8"))
    except Exception:  # noqa: BLE001
        return {}


def log(msg):
    with open(os.path.join(DATA, "apply.log"), "a", encoding="utf8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")


def notify(title, text):
    try:
        sys.path.insert(0, r"D:\Atlas\tools")
        import notify as N
        N.notify(title, text, "/")
    except Exception:  # noqa: BLE001
        pass


def clean(s, n=4000):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s or ""))[:n].strip()


def google_ready(c):
    return bool(c.get("google_client_id") and c.get("google_client_secret") and c.get("public_url"))


class H(http.server.BaseHTTPRequestHandler):
    server_version = "xseeding-apply/1"

    def log_message(self, *a):
        pass

    def ip(self):
        return (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def local(self):
        return (self.headers.get("Host") or "").split(":")[0] in ("127.0.0.1", "localhost") and self.client_address[0] == "127.0.0.1" and not self.headers.get("CF-Connecting-IP")

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def static(self, rel):
        p = os.path.normpath(os.path.join(STATIC, rel))
        if not p.startswith(STATIC) or not os.path.isfile(p):
            return self.send(404, "not found", "text/plain")
        self.send(200, open(p, "rb").read(), MIME.get(os.path.splitext(p)[1], "application/octet-stream"))

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        c = cfg()
        if p == "/healthz":
            return self.send(200, "ok", "text/plain")
        if p in ("/", "/apply"):
            return self.static("index.html")
        if p == "/privacy":
            return self.static("privacy.html")
        if p.startswith("/static/"):
            return self.static(p[8:])
        if p == "/api/config":
            return self.send(200, {"google": google_ready(c), "contact": c.get("contact_email", ""), "keep_days": c.get("keep_days", 90),
                                   "sources": [{"id": k, "text": t} for k, t in SOURCES]})
        m = re.match(r"^/delete/([a-z0-9]{12})/([a-z0-9]{32})$", p)
        if m:
            d = os.path.join(DATA, m.group(1))
            rec = jload(os.path.join(d, "application.json"))
            if rec and secrets.compare_digest(rec.get("delete_token", ""), m.group(2)):
                shutil.rmtree(d, ignore_errors=True)
                log("deleted %s by its delete link" % m.group(1))
                return self.send(200, "<meta charset=utf-8><body style='background:#0b0a14;color:#eee;font:16px system-ui;padding:40px'>Done. Your application and every file with it are deleted.</body>", "text/html; charset=utf-8")
            return self.send(404, "no such application (maybe already deleted)", "text/plain")
        if p == "/google/start" and google_ready(c):
            q = urllib.parse.parse_qs(u.query)
            aid, t = q.get("app", [""])[0], q.get("t", [""])[0]
            rec = jload(os.path.join(DATA, aid, "application.json")) if re.match(r"^[a-z0-9]{12}$", aid) else None
            if not rec or not secrets.compare_digest(rec.get("google_token", ""), t):
                return self.send(403, "bad link", "text/plain")
            state = secrets.token_urlsafe(24)
            jsave(os.path.join(DATA, aid, "google-state.json"), {"state": state, "at": time.time()})
            params = {"client_id": c["google_client_id"], "redirect_uri": c["public_url"].rstrip("/") + "/google/callback", "response_type": "code",
                      "scope": "https://www.googleapis.com/auth/drive.readonly", "access_type": "offline", "prompt": "consent", "state": aid + "." + state}
            return self.send(302, "", "text/plain", {"Location": "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)})
        if p == "/google/callback" and google_ready(c):
            q = urllib.parse.parse_qs(u.query)
            st = q.get("state", [""])[0]
            aid, _, state = st.partition(".")
            d = os.path.join(DATA, aid) if re.match(r"^[a-z0-9]{12}$", aid) else None
            saved = jload(os.path.join(d, "google-state.json")) if d else None
            if not saved or not secrets.compare_digest(saved.get("state", ""), state) or "code" not in q:
                return self.send(403, "bad state", "text/plain")
            body = urllib.parse.urlencode({"code": q["code"][0], "client_id": c["google_client_id"], "client_secret": c["google_client_secret"],
                                           "redirect_uri": c["public_url"].rstrip("/") + "/google/callback", "grant_type": "authorization_code"}).encode()
            try:
                tok = json.load(urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=30))
            except Exception as exc:  # noqa: BLE001
                return self.send(502, "Google did not answer: %r" % exc, "text/plain")
            jsave(os.path.join(d, "google.json"), {"connected_at": time.time(), "refresh_token": tok.get("refresh_token"), "scope": tok.get("scope")})
            con = jload(os.path.join(d, "consent.json")) or {}
            con.setdefault("allowed", []).append("google") if "google" not in con.get("allowed", []) else None
            con["google_connected_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            jsave(os.path.join(d, "consent.json"), con)
            log("google connected for %s" % aid)
            return self.send(200, "<meta charset=utf-8><body style='background:#0b0a14;color:#eee;font:16px system-ui;padding:40px'>Google Drive connected (read-only). You can close this tab. Disconnect any time at myaccount.google.com &gt; Security &gt; Third-party access.</body>", "text/html; charset=utf-8")
        if p.startswith("/admin"):
            if not self.local():
                return self.send(404, "not found", "text/plain")
            return self.admin(p)
        return self.send(404, "not found", "text/plain")

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p != "/api/apply":
            return self.send(404, {"error": "no"})
        ip = self.ip()
        day = time.strftime("%Y-%m-%d")
        RATE.setdefault(day, {}).setdefault(ip, 0)
        if RATE[day][ip] >= 10:
            return self.send(429, {"error": "too many applications from this address today"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_FILES * MAX_FILE + 1 << 20:
            return self.send(413, {"error": "too big"})
        try:
            raw = self.rfile.read(n)
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(b"Content-Type: " + self.headers.get("Content-Type", "").encode() + b"\r\n\r\n" + raw)
            fields, items = {}, []
            for part in msg.iter_parts() if msg.is_multipart() else []:
                nm = part.get_param("name", header="content-disposition")
                fn = part.get_filename()
                if fn:
                    items.append((fn, part.get_payload(decode=True) or b""))
                elif nm:
                    fields.setdefault(nm, (part.get_payload(decode=True) or b"").decode("utf8", "replace"))
        except Exception:  # noqa: BLE001
            return self.send(400, {"error": "bad form"})
        g = lambda k, lim=4000: clean(fields.get(k, ""), lim)  # noqa: E731
        if g("website_url"):                                   # honeypot: real people never see this field
            return self.send(200, {"ok": True, "id": "thanks"})
        name, reach, why = g("name", 120), g("reach", 300), g("why", 6000)
        if len(name) < 2 or len(reach) < 3 or len(why) < 20:
            return self.send(400, {"error": "name, a way to reach you and a few lines about you are needed"})
        if g("adult") != "yes":
            return self.send(400, {"error": "you must be 18 or older to apply"})
        links = [clean(x, 300) for x in re.split(r"[\s,]+", g("links", 3000)) if x.startswith(("http://", "https://"))][:20]
        allowed = [k for k, _ in SOURCES if g("src_" + k) == "yes" and k != "google"]
        aid = secrets.token_hex(6)
        d = os.path.join(DATA, aid)
        os.makedirs(os.path.join(d, "files"), exist_ok=True)
        files = []
        for filename, data in items:
            fn = re.sub(r"[^A-Za-z0-9._ -]+", "_", os.path.basename(filename))[:120] or "file"
            ext = os.path.splitext(fn)[1].lower()
            if ext not in ALLOWED_EXT or len(files) >= MAX_FILES or len(data) > MAX_FILE or not data:
                continue
            with open(os.path.join(d, "files", fn), "wb") as fh:
                fh.write(data)
            files.append({"name": fn, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        rec = {"id": aid, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "name": name, "reach": reach, "why": why, "links": links, "handles": g("handles", 500),
               "files": files, "ip_hash": hashlib.sha256(ip.encode()).hexdigest()[:16], "delete_token": secrets.token_hex(16), "google_token": secrets.token_hex(16),
               "status": "new"}
        jsave(os.path.join(d, "application.json"), rec)
        jsave(os.path.join(d, "consent.json"), {"at": rec["at"], "allowed": allowed, "wording": dict(SOURCES), "privacy_page": "/privacy",
                                                "keep_days": cfg().get("keep_days", 90), "agreed_text": g("agreed_text", 2000)})
        RATE[day][ip] += 1
        log("new application %s from %s: %s (%d files, allowed %s)" % (aid, name, reach, len(files), ",".join(allowed) or "nothing"))
        with open(os.path.join(DATA, "queue.jsonl"), "a", encoding="utf8") as fh:
            fh.write(json.dumps({"id": aid, "at": rec["at"]}) + "\n")
        notify("New team applicant: " + name, "%s | %s | %d file(s) | Lumi may research: %s. Folder: %s" % (reach, why[:140], len(files), ", ".join(allowed) or "nothing (they said no)", d))
        c = cfg()
        base = c.get("public_url", "").rstrip("/")
        return self.send(200, {"ok": True, "id": aid, "delete_link": "%s/delete/%s/%s" % (base, aid, rec["delete_token"]),
                               "google_link": ("%s/google/start?app=%s&t=%s" % (base, aid, rec["google_token"])) if google_ready(c) else ""})

    def admin(self, p):
        rows = []
        for aid in sorted(os.listdir(DATA)):
            rec = jload(os.path.join(DATA, aid, "application.json"))
            if rec:
                con = jload(os.path.join(DATA, aid, "consent.json")) or {}
                rows.append({k: rec.get(k) for k in ("id", "at", "name", "reach", "status", "links", "files")} | {"allowed": con.get("allowed", []),
                            "research": os.path.exists(os.path.join(DATA, aid, "lumi-research.md"))})
        m = re.match(r"^/admin/([a-z0-9]{12})/research$", p)
        if m:
            f = os.path.join(DATA, m.group(1), "lumi-research.md")
            return self.send(200, open(f, encoding="utf8").read() if os.path.exists(f) else "no research yet", "text/plain; charset=utf-8")
        return self.send(200, rows)


def jload(p):
    try:
        return json.load(open(p, encoding="utf8"))
    except Exception:  # noqa: BLE001
        return None


def jsave(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf8") as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, p)


def sweep():
    """Applications older than keep_days (and not accepted) are deleted - the promise on the privacy page."""
    keep = float(cfg().get("keep_days", 90)) * 86400
    for aid in os.listdir(DATA):
        rec = jload(os.path.join(DATA, aid, "application.json"))
        if rec and rec.get("status") != "accepted":
            try:
                if time.time() - time.mktime(time.strptime(rec["at"], "%Y-%m-%d %H:%M:%S")) > keep:
                    shutil.rmtree(os.path.join(DATA, aid), ignore_errors=True)
                    log("deleted %s: older than the keep period" % aid)
            except Exception:  # noqa: BLE001
                pass


def main():
    os.makedirs(DATA, exist_ok=True)
    sweep()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print("apply server on http://127.0.0.1:%d/ (data %s)" % (PORT, DATA), flush=True)
    log("apply server started on %d" % PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
