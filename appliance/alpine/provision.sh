#!/bin/sh
# Runs only inside the disposable image build, never on the existing Pi.
set -eu
test "$(uname -m)" = aarch64
test -f /etc/alpine-release
adduser -D -h /var/lib/pi-home morningbus
addgroup morningbus video
addgroup morningbus input
adduser -D -h /home/admin admin
addgroup admin wheel
awk -F: '$1 == "admin" && $2 ~ /^[!*]/ {locked=1} END {exit !locked}' /etc/shadow
mkdir -p /etc/sudoers.d /etc/ssh/sshd_config.d
printf '%s\n' '%wheel ALL=(ALL:ALL) ALL' > /etc/sudoers.d/pi-home
chmod 440 /etc/sudoers.d/pi-home
printf '%s\n' 'PermitRootLogin no' 'PasswordAuthentication yes' 'PermitEmptyPasswords no' 'AllowUsers admin' > /etc/ssh/sshd_config.d/pi-home.conf
sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config
# Host keys are generated uniquely on the device by the OpenRC sshd service.
rc-update add sshd default
mkdir -p /etc/pi-home /var/lib/pi-home/roon
# Internal compatibility paths are retained across the RoonDeck rebrand.
ln -s /opt/pi-home /opt/pi-bus-time-display
ln -s /etc/pi-home /etc/pi-bus-time-display
ln -s /var/lib/pi-home /var/lib/pi-bus-time-display
cp config.example.toml /etc/pi-home/config.toml
touch /var/lib/pi-home/update-channel-initialized
sed -i 's/display_theme = "fresh-mint"/display_theme = "roon"/' /etc/pi-home/config.toml
cp .env.example /etc/pi-home/secrets.env
printf '%s\n' 'Ready' > /var/lib/pi-home/update-status
chmod 600 /etc/pi-home/secrets.env
chown -R morningbus:morningbus /etc/pi-home /var/lib/pi-home
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --no-build-isolation --no-deps .
npm --prefix roon-controller ci --omit=dev --no-audit --no-fund
chmod 755 native-display/pi_bus_native.py scripts/pi-bus-cage-launch
chmod 755 appliance/alpine/display-session
cp appliance/alpine/reset-password.py /usr/local/bin/pi-home-reset-password
chmod 755 /usr/local/bin/pi-home-reset-password
mkdir -p /usr/local/sbin
cp appliance/alpine/updater.py /usr/local/sbin/pi-home-alpine-update
chmod 755 /usr/local/sbin/pi-home-alpine-update
cp appliance/alpine/init.d/* /etc/init.d/
chmod 755 /etc/init.d/pi-home-*
cp appliance/alpine/display-launch /usr/local/bin/pi-home-display-launch
chmod 755 /usr/local/bin/pi-home-display-launch
mkdir -p /var/log/pi-home
chown morningbus:morningbus /var/log/pi-home
chmod 750 /var/log/pi-home
printf '%s\n' 'rc_logger="YES"' 'rc_log_path="/var/log/rc.log"' >> /etc/rc.conf
printf '%s\n' 'command_args="-g video"' > /etc/conf.d/seatd
printf '%s\n' 'roondeck' > /etc/hostname
mkdir -p /usr/share/icons/hicolor/scalable/apps
cp native-display/assets/brand/app-icon-dark.svg /usr/share/icons/hicolor/scalable/apps/roondeck.svg
printf '%s\n' 'auto lo' 'iface lo inet loopback' > /etc/network/interfaces
mkdir -p /etc/NetworkManager/conf.d
printf '%s\n' '[main]' 'plugins=keyfile' '[connection]' 'wifi.powersave=2' '[device]' 'wifi.backend=wpa_supplicant' > /etc/NetworkManager/conf.d/pi-home.conf
printf '%s\n' 'LABEL=PIROOT / ext4 defaults,noatime 0 1' 'LABEL=PIBOOT /boot vfat defaults 0 2' > /etc/fstab
for service in devfs dmesg mdev; do rc-update add "$service" sysinit; done
rc-update del mdev sysinit
rc-update add udev sysinit
rc-update add udev-trigger sysinit
for service in hwclock modules sysctl bootmisc hostname localmount hwdrivers; do rc-update add "$service" boot; done
for service in killprocs savecache mount-ro; do rc-update add "$service" shutdown; done
for service in networking dbus networkmanager avahi-daemon seatd pi-home-storage pi-home-firstboot pi-home-api pi-home-roon pi-home-setup pi-home-input pi-home-display; do rc-update add "$service" default; done
# Pi 4 has no battery-backed RTC. An epoch clock breaks HTTPS (LTA/updates).
# Restore at least the last known/build time before networking, then let chrony
# burst and step to exact network time as soon as connectivity appears.
date +%s > /var/lib/pi-home/clock-seed
rc-update del hwclock boot 2>/dev/null || true
rc-update add pi-home-clock boot
sed -i '/^[[:space:]]*makestep[[:space:]]/d' /etc/chrony/chrony.conf
sed -i -E '/^[[:space:]]*(pool|server)[[:space:]]/ { /[[:space:]]iburst([[:space:]]|$)/! s/$/ iburst/; }' /etc/chrony/chrony.conf
printf '%s\n' 'makestep 0.1 -1' >> /etc/chrony/chrony.conf
rc-update add chronyd default
rc-update add crond default
mkdir -p /etc/crontabs
sed -i '\|pi-home/appliance/alpine/updater.py --check|d' /etc/crontabs/root 2>/dev/null || true
printf '%s\n' '0 3 * * * /usr/bin/python3 /opt/pi-home/appliance/alpine/updater.py --check' >> /etc/crontabs/root
chmod 600 /etc/crontabs/root
# SSH is enabled, but admin stays locked until setup supplies a unique password.
awk -F: '$1 == "root" && $2 ~ /^[!*]/ {locked=1} END {exit !locked}' /etc/shadow
sed -i '/^[^#].*getty/s/^/#/' /etc/inittab
printf '%s\n' 'features="base mmc ext4"' > /etc/mkinitfs/mkinitfs.conf
kernel_version=$(find /lib/modules -mindepth 1 -maxdepth 1 -type d | head -n 1)
mkinitfs "${kernel_version##*/}"
test -s /boot/vmlinuz-rpi
test -s /boot/initramfs-rpi
test -s /boot/bcm2712-rpi-5-b.dtb
test -s /boot/overlays/vc4-kms-dsi-ili79600-10-1inch.dtbo
# Record the exact resolved package versions; repositories may receive fixes.
apk info -vv > /opt/pi-home/appliance/alpine/packages-resolved.txt
# Start with the same atomic deployment layout the updater uses. This avoids
# converting the live directory into a symlink during the first update.
mkdir -p /opt/pi-home-releases
mv /opt/pi-home /opt/pi-home-releases/initial-image
ln -s pi-home-releases/initial-image /opt/pi-home
