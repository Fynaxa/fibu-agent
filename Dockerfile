FROM python:3.11-slim

WORKDIR /app

# System-Abhängigkeiten für bcrypt, cryptography, pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Verzeichnisse anlegen
RUN mkdir -p inbox outbox archiv .tmp

# Nicht als Root laufen
RUN useradd -m fibu && chown -R fibu:fibu /app
USER fibu

EXPOSE 8080

ENV FLASK_SECRET_KEY=change-me-in-production
ENV PYTHONUNBUFFERED=1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "web.app:app"]
