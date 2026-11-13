FROM python:3.12-alpine3.20

# ffmpeg converts the album's videos into a format old devices can play smoothly;
# su-exec lets the entrypoint drop root privileges
RUN apk add --no-cache ffmpeg su-exec

WORKDIR /app
COPY app/ ./
COPY LICENSE ./

# PORT is the port *inside* the container: change the left side of "5050:8080" in
# docker-compose.yml to publish the frame on another port instead.
ENV PORT=8080 CACHE_DIR=/cache PUID=1000 PGID=1000
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD wget -qO- "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
