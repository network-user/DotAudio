FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libportaudio2 \
    && apt-get clean
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir '.[server]' && useradd --create-home --uid 10001 dotaudio
USER dotaudio
ENV HF_HOME=/home/dotaudio/.cache/huggingface
EXPOSE 8765
CMD ["dotaudio-server", "--host", "0.0.0.0", "--models", "base"]
