FROM python:3.8-slim

COPY . /app
RUN apt update && \
    apt dist-upgrade -y && \
    apt install -y ffmpeg imagemagick && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
    pip3 install --no-cache-dir -r /app/requirements.txt

ENTRYPOINT ["/app/ytmon.py", "--config", "/config/config.json"]
