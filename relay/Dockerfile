FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bridge_relay ./bridge_relay

RUN useradd --create-home --uid 10001 bridge
USER bridge

EXPOSE 8765
CMD ["python", "-m", "bridge_relay.server"]
