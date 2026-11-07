FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server rsync openssl tini util-linux tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 10001 -m -s /bin/sh backup \
    && usermod -p '*' backup && mkdir -p /run/sshd
WORKDIR /app
COPY src/pi_bus_time_display /app/pi_bus_time_display
COPY backup-server /app/backup-server
RUN chmod +x /app/backup-server/entrypoint.sh
EXPOSE 8042 2222
VOLUME /data
ENTRYPOINT ["/usr/bin/tini", "--", "/app/backup-server/entrypoint.sh"]
