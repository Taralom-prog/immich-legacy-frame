# immich-legacy-frame

**Turn an old iPad into a photo frame for your [Immich](https://immich.app) album — videos included.**

🇫🇷 [Lire en français](README.fr.md)

Old iPads (iPad 2, iPad 3, iPad mini 1…) are stuck on iOS 9, and their Safari can no
longer run modern web apps. Most photo frame projects either don't work on them at all,
or fall back to photos only. This one was written for them:

- 📷 **Photos and 🎬 videos** from one Immich album, in random order
- 🐢 **Smooth video on old hardware**: videos are converted in the background to a light
  720p format the old chip decodes easily (your originals in Immich are never touched)
- 🖼️ **Smart framing**: photos that match the screen's orientation fill it; the others
  (e.g. a landscape photo on a portrait frame) are shown whole on a blurred background,
  or cropped to fill the screen if you prefer
- 🗓️ **Date caption** (and place, when Immich knows it), optional clock
- 🔐 **Your API key stays on your server**: the device only talks to this small proxy
- 🪶 One small container, no dependencies besides Python and ffmpeg

Tested with an iPad 3 (iOS 9.3.5) and Immich v3.3.5. It should work on any iPad with
iOS 9 or later and in any modern browser. (iPhones on iOS 9 play videos full screen
outside a home-screen web app, which this project does not try to work around.)

If your device runs a modern browser, a full-featured project such as
[ImmichFrame](https://github.com/immichFrame/ImmichFrame) or
[immich-kiosk](https://github.com/damongolding/immich-kiosk) may suit you better. This one
focuses on devices stuck on iOS 9, and on playing videos smoothly there.

## How it works

```
 old iPad (Safari 9)  ──►  immich-legacy-frame  ──►  Immich
                           ├─ serves the frame page (old-school ES5 JavaScript)
                           ├─ picks random items from the album
                           ├─ relays photo previews, adding the API key
                           └─ converts videos with ffmpeg ──► ./cache
```

**Why convert videos?** Phone videos are typically 1080p or 4K at 15–20 Mbit/s with
H.264 "High 5.x" or HEVC. An iPad 3 can only play them with stutters, if at all. Each
video of the album is converted once to H.264 Main 3.1, ~3 Mbit/s, 30 fps max, fitting in
a 1280×720 box (720×1280 for portrait videos), with the phone's rotation applied. Videos
longer than `MAX_VIDEO_SECONDS` are cut. Videos appear on the frame as soon as they are
converted; the frame only ever shows assets of the album.

## Quick start

You need Docker with Compose, on a machine that can reach your Immich server.

1. **Get the code**
   ```bash
   git clone https://github.com/Taralom-prog/immich-legacy-frame.git
   cd immich-legacy-frame
   cp .env.example .env
   ```
2. **Create an API key** in Immich: *Account settings → API keys → New API key*. Use a
   dedicated key for the frame, and prefer a restricted, read-only one: it needs to read
   albums and assets, search, view thumbnails and download originals (to convert
   videos). At startup the logs say whether the key and album work.
3. **Find the album id**: open the album in Immich, the id is the last part of the URL:
   `https://immich.example/albums/`**`1b2c3d4e-0000-4000-8000-…`**
4. **Fill in `.env`**: `IMMICH_URL`, `IMMICH_API_KEY`, `ALBUM_ID`, and `LANGUAGE`
   (`en` or `fr`). Everything else has sensible defaults.
5. **Start it**
   ```bash
   docker compose up -d
   docker compose logs -f     # watch the video conversion
   ```
6. On the old device, open **`http://<docker-host-ip>:5050`** in Safari and **tap the
   screen once**.

## Setting up the old device

- **Tap once after each (re)load.** iOS 9 refuses to play a video that was not started by
  a tap. The first tap unlocks video playback for as long as the page stays open. Any
  later tap skips to the next item.
- **Never sleep**: *Settings → General → Auto-Lock → Never*, and keep it plugged in.
- **Full screen**: in Safari, *Share → Add to Home Screen*, then open the frame from that
  icon.
- **Kiosk mode**: *Settings → General → Accessibility → Guided Access*, then triple-click
  the Home button on the frame to lock the device on it.

## Configuration

All settings live in `.env`. Apply changes with `docker compose up -d`.

| Setting | Default | Description |
|---|---|---|
| `IMMICH_URL` | *(required)* | Immich address as seen from the container, e.g. `http://192.168.1.10:2283` |
| `IMMICH_API_KEY` | *(required)* | API key, see above |
| `ALBUM_ID` | *(required)* | Album to show |
| `LANGUAGE` | `en` | `en` or `fr`: start screen and dates |
| `PHOTO_SECONDS` | `10` | How long each photo stays on screen |
| `MAX_VIDEO_SECONDS` | `60` | Longer videos are cut |
| `VIDEO_SOUND` | `false` | Play the videos' sound |
| `CROP_PHOTOS` | `true` | Fill the screen, or show whole photos with black bars |
| `CROP_OTHER_ORIENTATION_PHOTOS` | `false` | Photos whose orientation differs from the screen (e.g. landscape on a portrait frame): `false` = whole on a blurred background, `true` = cropped to fill the screen |
| `CROP_OTHER_ORIENTATION_VIDEOS` | `false` | Same, for videos |
| `SHOW_DATE` | `true` | Caption with the date the photo was taken |
| `SHOW_PLACE` | `true` | Add the city (or state, or country) to the caption |
| `SHOW_CLOCK` | `false` | Small clock in the bottom right corner |
| `INCLUDE_VIDEOS` | `true` | `false` = photos only, nothing is converted |
| `VIDEO_MAX_SIDE` | `1280` | Longest side of converted videos, in pixels (the short side is 9/16 of it) |
| `VIDEO_MAXRATE` | `3M` | Maximum bitrate of converted videos |
| `RESCAN_MINUTES` | `60` | How often the album is checked for new or removed videos |
| `FFMPEG_THREADS` | `2` | CPU cores used while converting (ffmpeg runs at the lowest priority) |
| `PUID` / `PGID` | `1000` | Owner of the `./cache` folder on the host (run `id` to see yours) |
| `DEBUG_LOG` | `true` | Show the frame's own messages in `docker compose logs` |

Changing one of the video conversion settings converts every video again, automatically.

To use another port, change the `5050` in `docker-compose.yml`. (`PORT` is the port
inside the container: leave it alone.)

## Disk and CPU usage

- **Disk**: about 9 MB per video on average in `./cache`, up to ~25 MB for a video that
  reaches the 60 s cut (for example, 1,300 videos ≈ 12 GB). While a video is converted,
  its original is downloaded to `./cache/tmp`, so keep room for your largest video too.
  Videos removed from the album are deleted from the cache at the next check.
- **CPU**: the first conversion of a big album takes a while (about 10 s per video on 2
  cores of a small server). After that, only new videos are converted.

## Troubleshooting

`docker compose logs -f` shows both the server and the frame's own messages (lines
starting with `frame>`).

| Symptom | What to check |
|---|---|
| The device can't open the page | Is port 5050 reachable from the device's network (firewall, NAT rules)? Try opening the page from a computer first. |
| "Connecting to Immich…" forever | Check the `WARNING` at startup: `IMMICH_URL`, `IMMICH_API_KEY` or `ALBUM_ID`. It also happens with an empty album, or an album of videos that are not converted yet. |
| No videos | They show up once converted: look for `converted` lines in the logs. |
| A video is never shown | Look for a `FAILED` line in the logs. Such videos are retried after 24 h. |
| A video looks washed out | It was filmed in HDR (default on many recent phones); the conversion does not tone-map HDR yet. |
| No place in the caption | Your photos have no GPS position in Immich (location disabled in the camera, or removed by a messaging app). |
| Videos stopped playing after a reload | Tap the screen once (iOS 9 rule, see above). |
| HTTPS error with a self-signed certificate | Use Immich's plain `http://` address on your local network. |

## Security

- Anyone who can reach port 5050 can see the album's photos and videos, without logging
  in. Keep it on your local network and don't expose it to the internet.
- Only the album is reachable: the frame refuses any other asset id, even if the API key
  could see it.
- The API key is only used by the server and never sent to the device.
- The container drops root privileges at startup (`PUID`/`PGID`).
- The caption can show where photos were taken, on a screen that may sit in a shared
  room: set `SHOW_PLACE=false` if you'd rather not.

## Development

The server is a single file with no dependencies: [`app/server.py`](app/server.py).
The page is [`app/index.html`](app/index.html), and it must stay compatible with Safari 9:
ES5 only, no `object-fit`, no CSS grid.

```bash
python3 -m unittest discover tests
```

To run it without Docker you need Python 3.9+ and ffmpeg 4.4+ in your `PATH`, then open
http://localhost:8080:

```bash
set -a; . ./.env; set +a
CACHE_DIR=./cache python3 app/server.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

[MIT](LICENSE). This project is not affiliated with Immich; Immich is a trademark of its owners.
