#!/bin/sh
# Start as root only long enough to give the cache folder to PUID:PGID,
# then run the server as that unprivileged user.
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
mkdir -p "${CACHE_DIR:-/cache}"
chown -R "$PUID:$PGID" "${CACHE_DIR:-/cache}"
exec su-exec "$PUID:$PGID" python3 -u /app/server.py
