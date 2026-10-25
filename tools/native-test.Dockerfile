FROM alpine:3.24.2

RUN apk add --no-cache \
    adwaita-icon-theme \
    dbus \
    font-inter \
    gtk4.0 \
    imagemagick \
    librsvg \
    mesa-dri-gallium \
    py3-cairo \
    py3-gobject3 \
    python3 \
    xvfb-run

WORKDIR /opt/pi-home
