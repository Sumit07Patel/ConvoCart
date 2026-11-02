FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY convocart ./convocart
COPY scripts ./scripts
COPY eval ./eval

RUN useradd -m app && chown -R app /app
USER app

EXPOSE 8000 9000
# Default: the agent service. docker-compose overrides the command for the store, seed and cron.
# SEED_ON_START=1 (hosting with a throwaway SQLite file, e.g. Render free) reseeds the demo store at boot.
CMD ["sh", "-c", "if [ \"$SEED_ON_START\" = 1 ]; then python -m scripts.seed --force; fi && exec uvicorn convocart.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
