#!/usr/bin/python3
"""Tag an MP3 using metadata from a Genius song page.

Usage:
    genius_tag.py SONG.mp3 https://genius.com/Artist-song-lyrics [--no-lyrics] [--dry-run]
    genius_tag.py https://youtu.be/VIDEO https://genius.com/Artist-song-lyrics
"""
import argparse
import html as htmllib
import json
import os
import re
import subprocess
import sys
import urllib.request

from mutagen.id3 import (
    APIC, ID3, ID3NoHeaderError, TALB, TCOM, TCON, TDRC, TIT2, TPE1,
    TPE2, TPOS, TRCK, USLT, WOAS,
)

import youtube

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,image/*,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(url):
    """Download a URL, falling back to curl if Cloudflare blocks urllib."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if b"cloudflare_error" not in data[:20000]:
            return data
    except Exception:
        pass
    cmd = ["curl", "-sL", "--fail", "--max-time", "30"]
    for k, v in HEADERS.items():
        cmd += ["-H", f"{k}: {v}"]
    return subprocess.run(cmd + [url], check=True, capture_output=True).stdout


def js_unescape(s):
    """Decode the body of a single-quoted JavaScript string literal."""
    simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

    def rep(m):
        c = m.group(1)
        if c[0] in "ux" and len(c) > 1:
            return chr(int(c[1:], 16))
        return simple.get(c, c)

    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", rep, s, flags=re.S)


def load_state(url):
    try:
        page = fetch(url).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        sys.exit(f"Couldn't load {url} (check the link, or Genius may be blocking requests).")
    m = re.search(r"window\.__PRELOADED_STATE__ = JSON\.parse\('(.*?)'\);", page, re.S)
    if not m:
        sys.exit("Couldn't find song data on that page. Is it a Genius song (lyrics) URL?")
    return json.loads(js_unescape(m.group(1)))


def lyrics_text(body_html):
    t = re.sub(r"<br\s*/?>\s*", "\n", body_html)
    t = re.sub(r"</p>\s*<p>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmllib.unescape(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def extract(state, url):
    ent = state["entities"]
    sp = state["songPage"]
    song_id = sp["song"]
    song = ent["songs"][str(song_id)]
    artists = ent.get("artists", {})

    def names(ids):
        return [artists[str(i)]["name"] for i in ids or [] if str(i) in artists]

    info = {
        "title": song.get("titleWithFeatured") or song["title"],
        "artist": song.get("primaryArtistNames") or song["artistNames"],
        "writers": names(song.get("writerArtists")),
        "url": song.get("url") or url,
        "colors": [song.get("songArtPrimaryColor"), song.get("songArtSecondaryColor"),
                   song.get("songArtTextColor")],
    }

    d = song.get("releaseDateComponents") or {}
    album = ent.get("albums", {}).get(str(song.get("album"))) if song.get("album") else None
    if album:
        info["album"] = album["name"]
        info["album_artist"] = album.get("primaryArtistNames") or (
            artists.get(str(album.get("artist")), {}).get("name"))
        info["cover_url"] = album.get("coverArtUrl")
        info["cover_thumb"] = album.get("coverArtThumbnailUrl")
        d = album.get("releaseDateComponents") or d
        tracklist = album.get("tracklist") or []
        apps = ent.get("albumAppearances", {})
        for app in apps.values():
            if app.get("song") == song_id:
                info["track"] = app.get("discTrackNumber") or app.get("number")
                info["disc"] = app.get("discNumber")
                break
        else:
            if song_id in tracklist:
                info["track"] = tracklist.index(song_id) + 1
        if info.get("track") and (info.get("disc") or 1) == 1 and tracklist:
            discs = {a.get("discNumber") for a in apps.values()}
            if discs <= {1, None}:
                info["track_total"] = len(tracklist)

    if not info.get("cover_url") or "default_cover" in (info.get("cover_url") or ""):
        info["cover_url"] = song.get("songArtImageUrl")
        info["cover_thumb"] = song.get("songArtImageThumbnailUrl")

    if d.get("year"):
        info["date"] = "-".join(
            f"{d[k]:02d}" if k != "year" else str(d[k])
            for k in ("year", "month", "day") if d.get(k))

    tags = ent.get("tags", {})
    primary = next((t["name"] for t in tags.values() if t.get("primary")), None)
    if primary:
        info["genre"] = primary

    body = (sp.get("lyricsData") or {}).get("body", {}).get("html")
    if body:
        info["lyrics"] = lyrics_text(body)
    for k, v in info.items():
        if isinstance(v, str):
            info[k] = v.replace("\u00a0", " ")
    return info


def write_tags(path, info, lyrics=True):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    for frame in ("TIT2", "TPE1", "TPE2", "TALB", "TDRC", "TRCK", "TPOS",
                  "TCON", "TCOM", "APIC", "USLT", "WOAS"):
        tags.delall(frame)

    tags.add(TIT2(encoding=3, text=info["title"]))
    tags.add(TPE1(encoding=3, text=info["artist"]))
    if info.get("album"):
        tags.add(TALB(encoding=3, text=info["album"]))
    if info.get("album_artist"):
        tags.add(TPE2(encoding=3, text=info["album_artist"]))
    if info.get("date"):
        tags.add(TDRC(encoding=3, text=info["date"]))
    if info.get("track"):
        trk = str(info["track"])
        if info.get("track_total"):
            trk += f"/{info['track_total']}"
        tags.add(TRCK(encoding=3, text=trk))
    if info.get("disc"):
        tags.add(TPOS(encoding=3, text=str(info["disc"])))
    if info.get("genre"):
        tags.add(TCON(encoding=3, text=info["genre"]))
    if info["writers"]:
        tags.add(TCOM(encoding=3, text=", ".join(info["writers"])))
    tags.add(WOAS(url=info["url"]))
    if lyrics and info.get("lyrics"):
        tags.add(USLT(encoding=3, lang="eng", desc="", text=info["lyrics"]))

    if info.get("cover_url"):
        img = fetch(info["cover_url"])
        mime = "image/png" if img[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img))
        info["cover_bytes"] = len(img)

    tags.save(path, v2_version=3)


def main():
    ap = argparse.ArgumentParser(description="Tag an MP3 from a Genius song page.")
    ap.add_argument("mp3", help="an MP3 file, or a YouTube link to download")
    ap.add_argument("genius_url")
    ap.add_argument("--no-lyrics", action="store_true", help="don't embed lyrics")
    ap.add_argument("--dry-run", action="store_true", help="show tags without writing")
    args = ap.parse_args()

    info = extract(load_state(args.genius_url), args.genius_url)

    labels = [("Title", "title"), ("Artist", "artist"), ("Album", "album"),
              ("Album artist", "album_artist"), ("Date", "date"), ("Track", "track"),
              ("Disc", "disc"), ("Genre", "genre"), ("Cover", "cover_url")]
    for label, key in labels:
        if info.get(key):
            val = info[key]
            if key == "track" and info.get("track_total"):
                val = f"{val}/{info['track_total']}"
            print(f"{label:>13}: {val}")
    if info["writers"]:
        print(f"{'Writers':>13}: {', '.join(info['writers'])}")
    if info.get("lyrics"):
        state = "skipped" if args.no_lyrics else f"{len(info['lyrics'].splitlines())} lines"
        print(f"{'Lyrics':>13}: {state}")

    if args.dry_run:
        print("\n(dry run, nothing written)")
        return
    path = args.mp3
    if youtube.is_youtube(path):
        def progress(stage, pct, title):
            print(f"\r{stage.capitalize()} {title or ''}: {pct:.0f}%   ", end="", flush=True)
        print()
        try:
            path = youtube.download(path, progress)
        except RuntimeError as e:
            sys.exit(f"\nCouldn't download that video: {e}")
        print()
    write_tags(path, info, lyrics=not args.no_lyrics)
    if os.path.dirname(os.path.abspath(path)) == youtube.SAVE_DIR:
        path = youtube.tidy_name(path, info["artist"], info["title"])
    print(f"\nTagged {path}")


if __name__ == "__main__":
    main()
