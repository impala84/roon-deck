FROM python:3.12-slim-bookworm
# Debian already provides backup (UID 34); configure it instead of creating it.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server rsync openssl tini util-linux tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && usermod -u 10001 -d /home/backup -s /bin/sh -p '*' backup \
    && mkdir -p /home/backup /run/sshd \
    && chown backup:backup /home/backup
WORKDIR /app
COPY src/pi_bus_time_display /app/pi_bus_time_display
COPY backup-server /app/backup-server
RUN chmod +x /app/backup-server/entrypoint.sh
EXPOSE 8042 2222
VOLUME /data
ENTRYPOINT ["/usr/bin/tini", "--", "/app/backup-server/entrypoint.sh"]
