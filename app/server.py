#!/usr/bin/env python3
"""immich-legacy-frame: an Immich photo frame (photos AND videos) for old iPads.

A small, dependency-free server that:
  * serves the frame page (ES5 JavaScript, works on Safari 9 / iOS 9);
  * picks random photos and videos from one Immich album;
  * proxies photo previews from Immich, so the API key never leaves the server;
  * converts the album's videos into light 720p H.264 files that old devices
    can decode smoothly, and serves them with HTTP Range support.
"""
import datetime as dt
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CACHED_VIDEO_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.mp4$")
CONVERSION_VERSION = 2  # bump when ffmpeg_command changes in a way that needs a reconversion


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- config

def env_str(name, default=""):
    # Tolerate "value   # comment", which some tools copy verbatim from .env files
    return re.split(r"\s+#", os.environ.get(name, default), maxsplit=1)[0].strip()


def env_bool(name, default):
    value = env_str(name, str(default)).lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    sys.exit(f"{name} must be true or false, not {value!r}")


def env_int(name, default):
    value = env_str(name, str(default))
    try:
        return int(value)
    except ValueError:
        sys.exit(f"{name} must be a whole number, not {value!r}")


STRINGS = {
    "en": {
        "tapToStart": "Tap the screen to start the frame",
        "tapToStartHint": "(needed once so that videos are allowed to play)",
        "connecting": "Connecting to Immich…",
        "months": ["January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December"],
    },
    "fr": {
        "tapToStart": "Touchez l'écran pour lancer le cadre",
        "tapToStartHint": "(nécessaire une fois pour autoriser les vidéos)",
        "connecting": "Connexion à Immich…",
        "months": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                   "août", "septembre", "octobre", "novembre", "décembre"],
    },
}

IMMICH_URL = env_str("IMMICH_URL").rstrip("/")
API_KEY = env_str("IMMICH_API_KEY")
ALBUM_ID = env_str("ALBUM_ID").lower()
PORT = env_int("PORT", 8080)
# "fr", "fr_FR.UTF-8" and "fr:en" all mean French; anything unknown falls back to English
LANGUAGE = env_str("LANGUAGE", "en")[:2].lower()
if LANGUAGE not in STRINGS:
    LANGUAGE = "en"

INCLUDE_VIDEOS = env_bool("INCLUDE_VIDEOS", True)
SHOW_DATE = env_bool("SHOW_DATE", True)
SHOW_PLACE = env_bool("SHOW_PLACE", True)
DEBUG_LOG = env_bool("DEBUG_LOG", True)

# Video conversion (see README: "Why convert videos?")
CACHE_DIR = env_str("CACHE_DIR", "/cache")
VIDEO_MAX_SIDE = env_int("VIDEO_MAX_SIDE", 1280)
VIDEO_MAXRATE = env_str("VIDEO_MAXRATE", "3M")
RESCAN_MINUTES = env_int("RESCAN_MINUTES", 60)
FFMPEG_THREADS = str(env_int("FFMPEG_THREADS", 2))
FAILED_RETRY_HOURS = 24

# Settings sent to the page (injected into index.html)
PAGE_CONFIG = {
    "photoSeconds": env_int("PHOTO_SECONDS", 10),
    "maxVideoSeconds": env_int("MAX_VIDEO_SECONDS", 60),
    "videoSound": env_bool("VIDEO_SOUND", False),
    "cropPhotos": env_bool("CROP_PHOTOS", True),
    "showClock": env_bool("SHOW_CLOCK", False),
}


def check_config():
    missing = [n for n, v in (("IMMICH_URL", IMMICH_URL), ("IMMICH_API_KEY", API_KEY),
                              ("ALBUM_ID", ALBUM_ID)) if not v]
    if missing:
        sys.exit(f"Missing required setting(s): {', '.join(missing)} (see .env.example)")
    url = urlparse(IMMICH_URL)
    if url.scheme not in ("http", "https") or not url.hostname:
        sys.exit(f"IMMICH_URL must look like http://192.168.1.10:2283, not {IMMICH_URL!r}")
    if not UUID_RE.match(ALBUM_ID):
        sys.exit("ALBUM_ID must be an album id (the last part of the album's URL in Immich)")


def check_immich():
    """One early call, so that a wrong key or album shows a clear message in the logs."""
    try:
        album = immich_json("GET", f"/api/albums/{ALBUM_ID}?withoutAssets=true")
        log(f"connected to Immich, album: {album.get('albumName')!r}")
    except ImmichError as e:
        hints = {401: "the API key is wrong", 403: "the API key lacks a permission",
                 404: "no album with this ALBUM_ID (or the key cannot see it)"}
        log(f"WARNING: Immich answered HTTP {e.status}: {hints.get(e.status, e)}")
    except OSError as e:
        log(f"WARNING: cannot reach Immich at {IMMICH_URL} ({e}); will keep trying")


# --------------------------------------------------------------------------- pure helpers

def duration_seconds(value):
    """Immich returns durations in milliseconds (recent versions) or as 'H:MM:SS.mmm' (older ones)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return value / 1000.0
    try:
        h, m, s = str(value).split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return 0.0


def format_date(value, language="en"):
    """'2023-07-14T15:32:10.000Z' -> '14 July 2023' / '14 juillet 2023'.

    Immich's localDateTime is the wall-clock time where the photo was taken, so we only
    read the date part and never convert time zones.
    """
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value or "")
    if not m:
        return ""
    try:
        day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return ""
    month_name = STRINGS[language]["months"][day.month - 1]
    if language == "fr":
        return f"{'1er' if day.day == 1 else day.day} {month_name} {day.year}"
    return f"{day.day} {month_name} {day.year}"


def place_name(exif):
    """City where the photo was taken; falls back to state, then country."""
    exif = exif or {}
    for key in ("city", "state", "country"):
        value = (exif.get(key) or "").strip()
        if value:
            return value
    return ""


def parse_range(header, size):
    """Parse an HTTP Range header for a file of `size` bytes.

    Returns None for "send the whole file", (start, end) for a satisfiable range,
    or "invalid" for an unsatisfiable one (-> 416).
    """
    if not header:
        return None
    m = re.match(r"^bytes=(\d*)-(\d*)$", header.strip())
    if not m or not (m.group(1) or m.group(2)):
        return None  # unsupported form (e.g. multiple ranges): ignore it, send everything
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        if m.group(2) and int(m.group(2)) < start:
            return None  # "bytes=5-3" is malformed: RFC 9110 says ignore it
    else:  # suffix range: the last N bytes
        start, end = max(0, size - int(m.group(2))), size - 1
    if size == 0 or start > end:
        return "invalid"
    return start, end


def clean_log_text(text):
    """Text sent by the page, made safe for a single log line."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", text)[:500]


# --------------------------------------------------------------------------- Immich API

class ImmichError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def immich_conn():
    url = urlparse(IMMICH_URL)
    if url.scheme == "https":
        return http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=30)
    return http.client.HTTPConnection(url.hostname, url.port or 80, timeout=30)


def immich_path(path):
    return urlparse(IMMICH_URL).path.rstrip("/") + path


def immich_json(method, path, body=None):
    conn = immich_conn()
    try:
        headers = {"x-api-key": API_KEY, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, immich_path(path), body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status >= 400:
            raise ImmichError(resp.status, f"Immich {path} -> HTTP {resp.status}: {raw[:200]!r}")
        return json.loads(raw)
    finally:
        conn.close()


def album_videos():
    """All videos of the album, as a list of asset ids."""
    ids, page = [], 1
    while page:
        result = immich_json("POST", "/api/search/metadata",
                             {"albumIds": [ALBUM_ID], "type": "VIDEO", "page": int(page), "size": 1000})
        assets = result["assets"]
        ids.extend(item["id"] for item in assets["items"])
        page = assets.get("nextPage")  # a page number as a string, or null on the last page
    return ids


# Ids the page is allowed to ask for. Only assets handed out by /api/batch are served, so
# the frame cannot be used to browse the rest of the Immich library (the API key often sees
# much more than this album).
served_ids = set()


def random_batch(size):
    """A random selection of the album, ready for the page.

    Videos that are not converted yet are skipped: they will show up once ready.
    """
    body = {"albumIds": [ALBUM_ID], "size": size, "withExif": SHOW_PLACE}
    if not INCLUDE_VIDEOS:
        body["type"] = "IMAGE"
    out = []
    for asset in immich_json("POST", "/api/search/random", body):
        kind = asset.get("type")
        if kind not in ("IMAGE", "VIDEO"):
            continue
        if kind == "VIDEO" and not os.path.exists(cache_path(asset["id"])):
            continue
        served_ids.add(asset["id"])
        out.append({
            "id": asset["id"],
            "type": "video" if kind == "VIDEO" else "photo",
            "duration": round(duration_seconds(asset.get("duration")), 1),
            "date": format_date(asset.get("localDateTime") or asset.get("fileCreatedAt"), LANGUAGE)
            if SHOW_DATE else "",
            "place": place_name(asset.get("exifInfo")) if SHOW_PLACE else "",
        })
    return out


# --------------------------------------------------------------------------- video conversion

class ConvertError(Exception):
    """The file itself could not be converted (as opposed to Immich or the disk failing)."""


def cache_path(asset_id):
    return os.path.join(CACHE_DIR, asset_id + ".mp4")


def conversion_settings():
    return {"version": CONVERSION_VERSION, "maxSide": VIDEO_MAX_SIDE, "maxrate": VIDEO_MAXRATE,
            "maxSeconds": PAGE_CONFIG["maxVideoSeconds"]}


def scale_filter(max_side):
    """Fit inside max_side x (max_side * 9/16), in the video's own orientation.

    For the default 1280 this is 1280x720 (landscape) or 720x1280 (portrait): at most 3,600
    macroblocks, the H.264 level 3.1 limit, even for 4:3 videos.
    """
    long_side = max_side
    short_side = max_side * 9 // 16 // 2 * 2
    return (f"scale=w='if(gte(iw,ih),{long_side},{short_side})':"
            f"h='if(gte(iw,ih),{short_side},{long_side})':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2")


def ffmpeg_command(src, dest):
    """Light, widely compatible H.264: 720p box, 30 fps max, Main profile level 3.1.

    ffmpeg applies the rotation stored by phones, so portrait videos come out upright.
    Only the first MAX_VIDEO_SECONDS (+5 s margin) are kept, since the frame cuts there anyway.
    """
    return [
        "nice", "-n", "19", "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", src,
        "-t", str(PAGE_CONFIG["maxVideoSeconds"] + 5),
        "-vf", scale_filter(VIDEO_MAX_SIDE),
        "-fpsmax", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "main", "-level", "3.1",
        "-crf", "23", "-maxrate", VIDEO_MAXRATE, "-bufsize", "6M", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart", "-threads", FFMPEG_THREADS, dest,
    ]


def download_original(asset_id, dest):
    conn = immich_conn()
    try:
        conn.request("GET", immich_path(f"/api/assets/{asset_id}/original"),
                     headers={"x-api-key": API_KEY})
        resp = conn.getresponse()
        if resp.status != 200:
            resp.read()
            raise ImmichError(resp.status, f"download {asset_id} -> HTTP {resp.status}")
        expected = resp.getheader("Content-Length")
        written = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
        if expected is not None and written != int(expected):
            raise OSError(f"download {asset_id} truncated ({written} of {expected} bytes)")
    finally:
        conn.close()


def convert(asset_id):
    tmp_dir = os.path.join(CACHE_DIR, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    src = os.path.join(tmp_dir, asset_id + ".src")
    part = os.path.join(tmp_dir, asset_id + ".mp4")
    try:
        download_original(asset_id, src)
        timeout = max(300, 10 * PAGE_CONFIG["maxVideoSeconds"])
        try:
            result = subprocess.run(ffmpeg_command(src, part), capture_output=True, text=True,
                                    timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ConvertError(f"ffmpeg took more than {timeout} s") from None
        if result.returncode != 0:
            if "No space left" in result.stderr:
                raise OSError("disk full")
            raise ConvertError(f"ffmpeg: {result.stderr.strip()[-300:]}")
        os.replace(part, cache_path(asset_id))  # atomic: never serve a half-written file
    finally:
        for path in (src, part):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def prepare_cache():
    """Clean leftovers, and drop the cache if the conversion settings changed."""
    tmp_dir = os.path.join(CACHE_DIR, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    for name in os.listdir(tmp_dir):  # leftovers of an interrupted conversion
        path = os.path.join(tmp_dir, name)
        if os.path.isfile(path):
            os.remove(path)
    settings_file = os.path.join(CACHE_DIR, "settings.json")
    try:
        with open(settings_file) as f:
            previous = json.load(f)
    except (OSError, ValueError):
        previous = None
    if previous != conversion_settings():
        removed = 0
        for name in os.listdir(CACHE_DIR):
            if CACHED_VIDEO_RE.match(name):
                os.remove(os.path.join(CACHE_DIR, name))
                removed += 1
        if removed:
            log(f"conversion settings changed: {removed} cached video(s) will be converted again")
        with open(settings_file, "w") as f:
            json.dump(conversion_settings(), f)


def sync_cache(failed):
    """One pass: remove videos that left the album, convert the missing ones.

    Raises on Immich or disk problems, so that the caller retries later; only files that
    ffmpeg cannot convert are remembered in `failed` (id -> time of the failure).
    """
    videos = album_videos()
    wanted = set(videos)
    # An empty answer is treated as suspicious (wrong album, API change…): never empty the cache
    if wanted:
        for name in os.listdir(CACHE_DIR):
            if CACHED_VIDEO_RE.match(name) and name[:-4] not in wanted:
                os.remove(os.path.join(CACHE_DIR, name))
                log(f"video {name[:-4]} left the album, removed from cache")
    retry_before = time.time() - FAILED_RETRY_HOURS * 3600
    todo = [v for v in videos
            if failed.get(v, 0) < retry_before and not os.path.exists(cache_path(v))]
    if not todo:
        return
    log(f"converting {len(todo)} of {len(videos)} video(s)")
    for i, asset_id in enumerate(todo, 1):
        started = time.time()
        try:
            convert(asset_id)
        except ConvertError as e:
            failed[asset_id] = time.time()
            log(f"FAILED {i}/{len(todo)} {asset_id}: {e} (will retry in {FAILED_RETRY_HOURS} h)")
            continue
        except ImmichError as e:
            if e.status in (403, 404):  # deleted meanwhile, or not downloadable with this key
                failed[asset_id] = time.time()
                log(f"FAILED {i}/{len(todo)} {asset_id}: {e}")
                continue
            raise
        failed.pop(asset_id, None)
        mb = os.path.getsize(cache_path(asset_id)) / 1e6
        log(f"converted {i}/{len(todo)} {asset_id} ({mb:.1f} MB, {time.time() - started:.0f} s)")
    ready = sum(1 for v in wanted if os.path.exists(cache_path(v)))
    log(f"conversion pass done: {ready} of {len(wanted)} video(s) ready")


def converter_loop():
    """Background thread: keep the cache in sync with the album, forever."""
    failed = {}
    prepared = False
    delay = 30
    while True:
        try:
            if not prepared:
                prepare_cache()
                prepared = True
            sync_cache(failed)
            delay = 30
            time.sleep(RESCAN_MINUTES * 60)
        except Exception as e:  # noqa: BLE001 - Immich down, disk full… try again later
            log(f"conversion paused ({e}), retrying in {delay} s")
            time.sleep(delay)
            delay = min(delay * 2, RESCAN_MINUTES * 60)


# --------------------------------------------------------------------------- HTTP server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silence the default per-request log
        pass

    def send_response(self, *args, **kwargs):
        self.headers_sent = True
        super().send_response(*args, **kwargs)

    def send_body(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        self.send_response(code)
        if code != 204:
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and code != 204:
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.headers_sent = False
        url = urlparse(self.path)
        path = url.path
        query = parse_qs(url.query)
        try:
            if path in ("/", "/index.html"):
                return self.send_page()
            if path == "/api/batch":
                try:
                    size = min(50, max(1, int(query.get("n", ["20"])[0])))
                except ValueError:
                    return self.send_body(400, b"n must be a number")
                return self.send_body(200, json.dumps(random_batch(size)).encode(), "application/json")
            if path == "/log":
                if DEBUG_LOG:
                    log("frame> " + clean_log_text(query.get("m", [""])[0]))
                return self.send_body(204)
            m = re.match(r"^/(img|thumb|vid)/([^/]+)$", path)
            if m:
                kind, asset_id = m.groups()
                if not UUID_RE.match(asset_id) or asset_id not in served_ids:
                    return self.send_body(404, b"not found")
                if kind == "img":
                    return self.proxy(f"/api/assets/{asset_id}/thumbnail?size=preview")
                if kind == "thumb":
                    return self.proxy(f"/api/assets/{asset_id}/thumbnail?size=thumbnail")
                return self.send_file(cache_path(asset_id), "video/mp4")
            if path == "/blank.mp4":
                return self.send_file(os.path.join(HERE, "blank.mp4"), "video/mp4")
            if path == "/health":
                return self.send_body(200, b"ok")
            return self.send_body(404, b"not found")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # the device moved on (next photo, video skipped…)
        except Exception as e:  # noqa: BLE001
            log(f"ERROR {path}: {e}")
            if self.headers_sent:
                # Part of a response is already out: the only clean way out is to hang up
                self.close_connection = True
            else:
                try:
                    self.send_body(502, b"upstream error")
                except OSError:
                    self.close_connection = True

    def send_page(self):
        with open(os.path.join(HERE, "index.html"), "rb") as f:
            page = f.read()
        config = dict(PAGE_CONFIG, strings={k: v for k, v in STRINGS[LANGUAGE].items() if k != "months"})
        page = page.replace(b"/*CONFIG*/{}", json.dumps(config).replace("</", "<\\/").encode())
        page = page.replace(b'<html lang="en">', f'<html lang="{LANGUAGE}">'.encode())
        self.send_body(200, page, "text/html; charset=utf-8")

    def send_file(self, path, ctype):
        """Serve a local file with Range support (Safari on iOS refuses video without it)."""
        try:
            f = open(path, "rb")  # opened first: the converter may delete it at any moment
        except FileNotFoundError:
            return self.send_body(404, b"not found (video not converted yet?)")
        with f:
            size = os.fstat(f.fileno()).st_size
            rng = parse_range(self.headers.get("Range"), size)
            if rng == "invalid":
                return self.send_body(416, headers={"Content-Range": f"bytes */{size}"})
            start, end = rng if rng else (0, size - 1)
            self.send_response(206 if rng else 200)
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command == "HEAD":
                return
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def proxy(self, upstream_path):
        """Stream an image from Immich, adding the API key on the way."""
        conn = immich_conn()
        try:
            conn.request("GET", immich_path(upstream_path), headers={"x-api-key": API_KEY})
            resp = conn.getresponse()
            self.send_response(resp.status)
            for header in ("Content-Type", "Content-Length", "Last-Modified", "ETag"):
                value = resp.getheader(header)
                if value:
                    self.send_header(header, value)
            # Only cache real images: an error must not stick in the device's cache
            self.send_header("Cache-Control", "private, max-age=3600" if resp.status == 200 else "no-store")
            if not resp.getheader("Content-Length"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if self.command == "HEAD":
                return
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        finally:
            conn.close()


def main():
    check_config()
    log(f"immich-legacy-frame listening on port {PORT} (album {ALBUM_ID}, videos: {INCLUDE_VIDEOS})")
    check_immich()
    if INCLUDE_VIDEOS:
        os.makedirs(CACHE_DIR, exist_ok=True)
        threading.Thread(target=converter_loop, daemon=True).start()
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
