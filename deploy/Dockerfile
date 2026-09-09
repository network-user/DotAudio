FROM python:3.12.8-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libportaudio2 \
    && apt-get clean
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir '.[server]' && useradd --create-home --uid 10001 dotaudio
USER dotaudio
ENV HF_HOME=/home/dotaudio/.cache/huggingface
ENV HF_HUB_DISABLE_TELEMETRY=1
EXPOSE 8765
# Host publish must stay 127.0.0.1; API key is required (DOTAUDIO_API_KEY).
CMD ["dotaudio-server", "--host", "0.0.0.0", "--models", "base"]
