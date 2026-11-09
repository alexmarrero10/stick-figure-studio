# The public site as one container: builds the web pages, then runs the API that also serves them.
# Build from the site/ folder:  docker build -t ndh-site site
# Hosts like Render and Fly.io build this file directly.

FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TRUST_PROXY=1
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ server/
COPY --from=web /web/dist web/dist
# Hosts set PORT; 8080 when run by hand.
CMD ["sh", "-c", "uvicorn app:app --app-dir server --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
