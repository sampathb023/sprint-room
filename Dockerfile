FROM python:3.13-slim

WORKDIR /app
COPY app.py README.md ./
COPY static ./static

ENV HOST=0.0.0.0
ENV PORT=8000
ENV DATA_FILE=/app/data/sessions.json
ENV SESSION_TTL_DAYS=30

EXPOSE 8000
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"
CMD ["python", "app.py"]
