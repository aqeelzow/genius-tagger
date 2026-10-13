# Genius Tagger

Tag MP3s with the title, artist, album, track number, genre, writers and album cover from a Genius song page. Songs can come from your own files or be downloaded from YouTube.

## The app

A small local web app at http://localhost:8765.

- Add songs by choosing or dropping MP3s, or by pasting YouTube links or a playlist link.
- Each song is matched to Genius automatically. Click a song to check the match, search for a different one, or edit any field.
- Write tags one song at a time, or tag everything that's ready at once.
- Tagged songs are saved to `~/Music/Genius Tagger` as `Artist - Title.mp3`. Your original files aren't changed.

Install it as a background service that starts at login:

```
./install_service.sh            # install, or update after changing the code
./install_service.sh --remove   # uninstall
```

Logs go to `~/Library/Logs/genius-tagger.log`.

## Command line

```
./genius_tag.py song.mp3 https://genius.com/Artist-song-lyrics
./genius_tag.py https://youtu.be/VIDEO https://genius.com/Artist-song-lyrics
```

Options: `--dry-run` shows the tags without writing them, and `--no-lyrics` leaves lyrics out.

## Requirements

- macOS with the system Python (`/usr/bin/python3`)
- [mutagen](https://pypi.org/project/mutagen/): `/usr/bin/python3 -m pip install --user mutagen`
- For YouTube downloads: `brew install yt-dlp ffmpeg`

Genius has no official API for this data, so the app reads it from the song page. If Genius changes its pages, lookups may break. If YouTube downloads stop working, `brew upgrade yt-dlp` usually fixes it.
