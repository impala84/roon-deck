#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install-pi.sh"
  exit 1
fi

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
desktop_user=${SUDO_USER:-}
if [[ -z ${desktop_user} || ${desktop_user} == root ]]; then
  echo "Run this installer with sudo from the Raspberry Pi desktop user."
  exit 1
fi
apt-get update
apt-get install -y git nodejs npm python3-venv python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-graphene-1.0 fonts-inter avahi-utils wlr-randr grim curl openssl
id morningbus >/dev/null 2>&1 || useradd --create-home --shell /bin/bash morningbus
# Keep existing settings and Roon pairing in place; never merge two installs.
for parent in /opt /etc /var/lib; do
  canonical="${parent}/pi-home"
  legacy="${parent}/pi-bus-time-display"
  if [[ -e ${canonical} && -e ${legacy} ]]; then
    if [[ $(readlink -f "${canonical}") != $(readlink -f "${legacy}") ]]; then
      echo "Conflicting installations at ${canonical} and ${legacy}; resolve these before installing."
      exit 1
    fi
  elif [[ -e ${legacy} && ! -L ${canonical} ]]; then
    ln -s "${legacy}" "${canonical}"
  elif [[ ! -e ${canonical} && ! -L ${canonical} ]]; then
    install -d -o morningbus -g morningbus "${canonical}"
  fi
  [[ -e ${canonical} ]] || { echo "Broken installation link: ${canonical}"; exit 1; }
  [[ -e ${legacy} ]] || ln -s "${canonical}" "${legacy}"
done
install -d -o morningbus -g morningbus /opt/pi-home /etc/pi-home /var/lib/pi-home /var/lib/pi-home/roon
if [[ $(readlink -f "${SOURCE_DIR}") != $(readlink -f /opt/pi-home) ]]; then
  # Export tracked source only: never copy local keys, node_modules or a Mac
  # virtualenv into the Pi. Keep Git metadata for release-tag updates.
  git -c safe.directory="${SOURCE_DIR}" -C "${SOURCE_DIR}" archive HEAD | tar -x -C /opt/pi-home
  cp -a "${SOURCE_DIR}/.git" /opt/pi-home/
fi
python3 -m venv --system-site-packages /opt/pi-home/.venv
/opt/pi-home/.venv/bin/pip install --no-deps /opt/pi-home
npm --prefix /opt/pi-home/roon-controller ci --omit=dev --no-audit --no-fund
sha256sum /opt/pi-home/roon-controller/package-lock.json | cut -d' ' -f1 >/var/lib/pi-home/roon-package-lock.sha256
chmod 0644 /var/lib/pi-home/roon-package-lock.sha256
[[ -f /etc/pi-home/config.toml ]] || install -m 0640 -o morningbus -g morningbus /opt/pi-home/config.example.toml /etc/pi-home/config.toml
[[ -f /etc/pi-home/secrets.env ]] || install -m 0600 -o morningbus -g morningbus /opt/pi-home/.env.example /etc/pi-home/secrets.env
[[ -f /etc/pi-home/roon.env ]] || install -m 0640 -o morningbus -g morningbus /dev/null /etc/pi-home/roon.env
if grep -q '^ADMIN_PASSWORD=change-me-now$' /etc/pi-home/secrets.env; then
  admin_password=$(openssl rand -hex 8)
  sed -i "s/^ADMIN_PASSWORD=change-me-now$/ADMIN_PASSWORD=${admin_password}/" /etc/pi-home/secrets.env
  echo "Web settings password: ${admin_password}"
fi
install -m 0644 /opt/pi-home/systemd/*.service /etc/systemd/system/
install -m 0644 /opt/pi-home/systemd/*.path /etc/systemd/system/
install -m 0755 /opt/pi-home/scripts/pi-bus-update /usr/local/sbin/pi-bus-update
install -m 0755 /opt/pi-home/scripts/pi-bus-system-action /usr/local/sbin/pi-bus-system-action
install -m 0755 /opt/pi-home/scripts/pi-bus-appliance-mode /usr/local/sbin/pi-bus-appliance-mode
desktop_home=$(getent passwd "${desktop_user}" | cut -d: -f6)
install -d -o "${desktop_user}" -g "${desktop_user}" "${desktop_home}/.config/autostart"
install -m 0644 -o "${desktop_user}" -g "${desktop_user}" /opt/pi-home/native-display/pi-bus-native.desktop "${desktop_home}/.config/autostart/pi-bus-native.desktop"
install -d /usr/share/icons/hicolor/scalable/apps
install -m 0644 /opt/pi-home/native-display/assets/brand/favicon-dark.svg /usr/share/icons/hicolor/scalable/apps/roondeck.svg
rm -f "${desktop_home}/.config/autostart/pi-bus-time-display.desktop"
chmod 0755 /opt/pi-home/native-display/roondeck_native.py
chmod 0755 /opt/pi-home/native-display/pi_bus_native.py
chmod 0755 /opt/pi-home/scripts/pi-bus-cage-launch
usermod -a -G morningbus "${desktop_user}"
systemctl daemon-reload
systemctl enable pi-bus-time-display.service
systemctl enable pi-bus-roon-controller.service
systemctl enable --now pi-bus-system-action.path
systemctl enable --now pi-home-leds.service
echo "Installed RoonDeck native GTK display. Edit /etc/pi-home/config.toml and /etc/pi-home/secrets.env, then reboot."
echo "Future application updates: sudo pi-bus-update"
