#!/usr/bin/python3
"""Genius Tagger app: a small local web UI around genius_tag.py.

Normally it runs as a background service (see install_service.sh) at
http://localhost:8765. Run directly, it opens in your browser and shuts itself
down a few minutes after the tab is closed.
"""
import itertools
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import genius_tag  # noqa: E402
import youtube  # noqa: E402

PORT = int(os.environ.get("TAGGER_PORT", 8765))
# As a service it stays up, and restarts (via launchd) when its files change.
SERVICE = bool(os.environ.get("TAGGER_SERVICE"))
# Loaded once, so the page always matches this server's version.
with open(os.path.join(HERE, "ui.html"), "rb") as f:
    PAGE = f.read()
# Changes whenever the app's files change, so an outdated server gets replaced.
def files_version():
    return str(max(os.path.getmtime(os.path.join(HERE, f))
                   for f in ("app.py", "genius_tag.py", "youtube.py", "ui.html")))


VERSION = files_version()
IDLE_LIMIT = 300
last_ping = [None]
jobs = {}
job_ids = itertools.count(1)


def start_download(url):
    job_id = str(next(job_ids))
    job = jobs[job_id] = {"stage": "starting", "pct": 0, "title": None}

    def progress(stage, pct, title):
        job.update(stage=stage, pct=pct, title=title)

    def run():
        try:
            path = youtube.download(url, progress)
            job.update(stage="done", pct=100, file=file_info(path))
        except Exception as e:
            job.update(stage="error", error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return job_id


def save_upload(name, data):
    """Save an uploaded MP3 into the app's folder (it can't write elsewhere)."""
    os.makedirs(youtube.SAVE_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(name))[0] or "Untitled"
    base = re.sub(r'[/\\:*?"<>|]', "", base)
    path = os.path.join(youtube.SAVE_DIR, base + ".mp3")
    n = 2
    while os.path.exists(path):
        path = os.path.join(youtube.SAVE_DIR, f"{base} ({n}).mp3")
        n += 1
    with open(path, "wb") as f:
        f.write(data)
    return path


def current_tags(path):
    try:
        tags = genius_tag.ID3(path)
    except Exception:
        return {}
    get = lambda k: str(tags[k]) if k in tags else ""
    return {"title": get("TIT2"), "artist": get("TPE1"), "album": get("TALB"),
            "has_cover": any(k.startswith("APIC") for k in tags.keys())}


def file_info(path):
    return {"path": path, "name": os.path.basename(path), "tags": current_tags(path)}


def search(q):
    url = "https://genius.com/api/search/song?per_page=8&q=" + urllib.parse.quote(q)
    data = json.loads(genius_tag.fetch(url))
    out = []
    for section in data["response"]["sections"]:
        for hit in section["hits"]:
            r = hit["result"]
            thumb = r.get("song_art_image_thumbnail_url") or ""
            out.append({
                "title": (r.get("title_with_featured") or r["title"]).replace("\u00a0", " "),
                "artist": r.get("primary_artist_names") or r.get("artist_names"),
                "url": r["url"],
                "thumb": "" if "default_cover" in thumb else thumb,
                "year": (r.get("release_date_components") or {}).get("year"),
            })
    return out


def lookup(url):
    page = genius_tag.fetch(url).decode("utf-8", "replace")
    m = re.search(r"window\.__PRELOADED_STATE__ = JSON\.parse\('(.*?)'\);", page, re.S)
    if not m:
        raise ValueError("That link isn't a Genius song page. Copy the link from the song's lyrics page.")
    state = json.loads(genius_tag.js_unescape(m.group(1)))
    return genius_tag.extract(state, url)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/hello":
            self.send(200, {"app": "genius-tagger", "version": VERSION})
        else:
            self.send(404, {"error": "Not found"})

    def do_POST(self):
        # Custom header forces a CORS preflight, so other websites can't call these.
        if self.headers.get("X-Tagger") != "1":
            return self.send(403, {"error": "Forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if self.path == "/api/upload":
            name = urllib.parse.unquote(self.headers.get("X-Filename") or "Untitled.mp3")
            try:
                return self.send(200, file_info(save_upload(name, raw)))
            except Exception as e:
                return self.send(400, {"error": str(e)})
        body = json.loads(raw or b"{}")
        try:
            self.send(200, self.route(body))
        except Exception as e:
            self.send(400, {"error": str(e) or e.__class__.__name__})

    def route(self, body):
        p = self.path
        if p == "/api/quit":
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return {}
        if p == "/api/ping":
            last_ping[0] = time.time()
            return {}
        if p == "/api/search":
            try:
                return {"results": search(body["q"].strip())}
            except subprocess.CalledProcessError:
                raise ValueError("Couldn't reach Genius. Check your internet connection.")
        if p == "/api/lookup":
            try:
                return lookup(body["url"].strip())
            except subprocess.CalledProcessError:
                raise ValueError("Couldn't load that link. Check it opens in your browser.")
        if p == "/api/playlist":
            if not youtube.is_playlist(body["url"]):
                raise ValueError("That isn't a YouTube playlist link.")
            return {"videos": youtube.playlist(body["url"])}
        if p == "/api/youtube":
            if not youtube.is_youtube(body["url"]):
                raise ValueError("That isn't a YouTube link.")
            return {"job": start_download(body["url"])}
        if p == "/api/job":
            return jobs[body["job"]]
        if p == "/api/tag":
            info, path = body["info"], body["path"]
            if not os.path.isfile(path):
                raise ValueError("That MP3 has moved or been deleted. Choose it again.")
            genius_tag.write_tags(path, info, lyrics=body.get("lyrics", True))
            # Everything here is the app's own copy, so give it a clean name.
            if os.path.dirname(os.path.abspath(path)) == youtube.SAVE_DIR:
                path = youtube.tidy_name(path, info["artist"], info["title"])
            return file_info(path)
        if p == "/api/reveal":
            subprocess.run(["open", "-R", body["path"]])
            return {}
        raise ValueError("Unknown action")


def running_version():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/hello", timeout=1) as r:
            data = json.load(r)
            return data.get("version", "old") if data.get("app") == "genius-tagger" else None
    except Exception:
        return None


def stop_old_server():
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/quit", data=b"{}", method="POST",
                                 headers={"X-Tagger": "1", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    for _ in range(15):
        if running_version() is None:
            return
        time.sleep(0.2)
    # Versions from before /api/quit existed: stop the app.py process holding the port.
    pids = subprocess.run(["/usr/sbin/lsof", "-ti", f"tcp:{PORT}", "-sTCP:LISTEN"],
                          capture_output=True, text=True).stdout.split()
    for pid in pids:
        cmd = subprocess.run(["/bin/ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
        if "app.py" in cmd:
            os.kill(int(pid), 15)
    for _ in range(15):
        if running_version() is None:
            return
        time.sleep(0.2)


def watchdog(server):
    started = time.time()
    while True:
        time.sleep(5)
        if SERVICE:
            if files_version() != VERSION:
                print("Files changed, restarting", flush=True)
                os._exit(0)
            continue
        # Quit 5 minutes after the tab closes, or after 5 minutes if no tab ever connects.
        idle = time.time() - (last_ping[0] or started)
        if idle > (IDLE_LIMIT if last_ping[0] else 300):
            server.shutdown()
            return


def main():
    url = f"http://127.0.0.1:{PORT}/"
    open_browser = not (os.environ.get("TAGGER_NO_BROWSER") or SERVICE)
    running = running_version()
    if running == VERSION:
        if open_browser:
            webbrowser.open(url)
        return
    if running:
        stop_old_server()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    print(f"Genius Tagger running at {url}")
    server.serve_forever()


if __name__ == "__main__":
    main()
