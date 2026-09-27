FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    ANONYMIZED_TELEMETRY=False \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]
