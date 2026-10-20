# Movie Loft web server. Serves the pages `make` builds plus the tags API.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Only what the server needs: the app, the built pages, and the artwork.
COPY app/ app/
COPY index.html tv.html guide.html ./
# Rooms for Tune in (copy movieloft.example.toml to make yours).
COPY movieloft.toml ./
COPY art/ art/
COPY art-tv/ art-tv/
COPY icons/ icons/
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
