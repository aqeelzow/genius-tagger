"""Download a YouTube video's audio as an MP3 using yt-dlp and ffmpeg."""
import os
import re
import shutil
import subprocess

SAVE_DIR = os.path.expanduser("~/Music/Genius Tagger")


def tool(name):
    """Find a Homebrew tool even when PATH is bare (as it is when launched from the .app)."""
    path = shutil.which(name)
    for p in (path, f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if p and os.path.isfile(p):
            return p
    raise RuntimeError(f"{name} isn't installed. Run: brew install {name}")


def is_youtube(url):
    return bool(re.match(r"https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", url.strip()))


def is_playlist(url):
    return bool(re.search(r"youtube\.com/playlist\?.*list=", url))


def playlist(url):
    """List a playlist's videos as [{"url", "title"}] without downloading them."""
    r = subprocess.run(
        [tool("yt-dlp"), url.strip(), "--flat-playlist", "--quiet", "--no-warnings",
         "--print", "%(id)s\t%(title)s"],
        capture_output=True, text=True)
    if r.returncode != 0:
        msg = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "yt-dlp failed"
        raise RuntimeError(re.sub(r"^ERROR:\s*(\[\w+\]\s*[\w-]+:\s*)?", "", msg))
    videos = []
    for line in r.stdout.splitlines():
        vid, _, title = line.partition("\t")
        if vid and title not in ("[Private video]", "[Deleted video]"):
            videos.append({"url": f"https://www.youtube.com/watch?v={vid}", "title": title})
    return videos


def download(url, on_progress=None):
    """Download audio to SAVE_DIR and return the MP3's path.

    on_progress(stage, percent, title) is called as the download goes.
    """
    os.makedirs(SAVE_DIR, exist_ok=True)
    cmd = [
        tool("yt-dlp"), url.strip(),
        "--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--ffmpeg-location", tool("ffmpeg"),
        "-o", os.path.join(SAVE_DIR, "%(title).150B [%(id)s].%(ext)s"),
        "--quiet", "--no-warnings", "--progress", "--newline", "--no-simulate",
        "--progress-template", "download:PROG %(progress._percent_str)s",
        "--print", "before_dl:TITLE %(title)s",
        "--print", "after_move:FILE %(filepath)s",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    title, path = None, None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("TITLE "):
            title = line[6:]
            on_progress and on_progress("downloading", 0, title)
        elif line.startswith("PROG "):
            m = re.search(r"([\d.]+)%", line)
            if m and on_progress:
                pct = float(m.group(1))
                on_progress("converting" if pct >= 100 else "downloading", pct, title)
        elif line.startswith("FILE "):
            path = line[5:]
    err = proc.stderr.read().strip()
    proc.wait()
    if proc.returncode != 0 or not path:
        msg = err.splitlines()[-1] if err else "yt-dlp failed"
        raise RuntimeError(re.sub(r"^ERROR:\s*(\[\w+\]\s*[\w-]+:\s*)?", "", msg))
    return path


def tidy_name(path, artist, title):
    """Rename a downloaded MP3 to 'Artist - Title.mp3' without overwriting anything."""
    base = re.sub(r'[/\\:*?"<>|]', "", f"{artist} - {title}").strip() or "Untitled"
    folder = os.path.dirname(path)
    new = os.path.join(folder, base + ".mp3")
    n = 2
    while os.path.exists(new) and os.path.abspath(new) != os.path.abspath(path):
        new = os.path.join(folder, f"{base} ({n}).mp3")
        n += 1
    os.rename(path, new)
    return new
