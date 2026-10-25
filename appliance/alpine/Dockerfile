# Build on ARM64 Linux. No credentials or host configuration enter this image.
FROM alpine:3.24.2
RUN apk add --no-cache alpine-base linux-rpi raspberrypi-bootloader \
    mkinitfs eudev seatd cage wlr-randr mesa-dri-gallium mesa-egl \
    python3 py3-pip py3-setuptools py3-gobject3 py3-cairo gtk4.0 \
    nodejs npm git ca-certificates curl openssl tzdata font-inter dbus avahi avahi-tools bash \
    networkmanager networkmanager-cli networkmanager-wifi networkmanager-openrc wpa_supplicant \
    e2fsprogs e2fsprogs-extra cloud-utils-growpart dosfstools openssh sudo adwaita-icon-theme librsvg grim procps chrony chrony-openrc \
    gcompat libstdc++ icu-libs alsa-lib bzip2
WORKDIR /opt/pi-home
COPY pyproject.toml ./
COPY src ./src
COPY native-display ./native-display
COPY scripts/pi-bus-cage-launch ./scripts/pi-bus-cage-launch
COPY roon-controller ./roon-controller
COPY tools/discovery-wire.cjs ./tools/discovery-wire.cjs
COPY tools/viewports.json ./tools/viewports.json
COPY config.example.toml .env.example ./
COPY appliance/alpine/ ./appliance/alpine/
RUN sh appliance/alpine/provision.sh
ARG PI_HOME_SOURCE_SHA
RUN test -n "$PI_HOME_SOURCE_SHA" && printf '%s\n' "$PI_HOME_SOURCE_SHA" > /opt/pi-home/.source-commit
