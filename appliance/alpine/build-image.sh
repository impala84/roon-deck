#!/usr/bin/env bash
# ARM64 Linux factory: writes regular temporary files, never a physical disk.
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || { echo 'Build on ARM64 Linux (or use the GitHub Alpine image workflow).'; exit 1; }
for tool in docker sudo sfdisk mkfs.vfat mkfs.ext4 mcopy mtype truncate dd gzip sha256sum python3; do command -v "$tool" >/dev/null || { echo "Missing build tool: $tool"; exit 1; }; done
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
out="$repo/dist/alpine"
mkdir -p "$out"
build_dir=$(mktemp -d)
container=
cleanup() {
  if [[ -n $container ]]; then docker rm "$container" >/dev/null; fi
  # Keep failed build files for diagnostics; never recursively delete a target.
  echo "Build working files: $build_dir"
}
trap cleanup EXIT
docker build --platform linux/arm64 --build-arg "PI_HOME_SOURCE_SHA=$(git -C "$repo" rev-parse HEAD)" -t pi-home-alpine:beta -f "$repo/appliance/alpine/Dockerfile" "$repo"
container=$(docker create pi-home-alpine:beta)
mkdir "$build_dir/rootfs" "$build_dir/boot"
docker export "$container" | sudo tar --same-owner -x -C "$build_dir/rootfs"
sudo python3 "$repo/appliance/alpine/prepare_rootfs.py" "$build_dir/rootfs"
# Test the bare-metal export, not just the runtime inside Docker.
test ! -e "$build_dir/rootfs/.dockerenv"
test ! -e "$build_dir/rootfs/run/.containerenv"
system_type=$(sudo chroot "$build_dir/rootfs" /sbin/openrc --sys)
[[ -z $system_type ]] || { echo "Export still detected as virtual/container system: $system_type"; exit 1; }
sudo chroot "$build_dir/rootfs" /sbin/rc-update -u
test -x "$build_dir/rootfs/sbin/fsck.ext4"
test -x "$build_dir/rootfs/sbin/fsck.vfat"
echo 'Bare-metal export: OpenRC container detection, dependency generation and filesystem tools passed.'
sudo cp -a "$build_dir/rootfs/boot/." "$build_dir/boot/"
sudo cp "$repo/appliance/alpine/config.txt" "$repo/appliance/alpine/cmdline.txt" "$build_dir/boot/"
truncate -s 256M "$build_dir/boot.fat"
mkfs.vfat -F 32 -n PIBOOT "$build_dir/boot.fat"
sudo mcopy -i "$build_dir/boot.fat" -s "$build_dir/boot/"* ::/
truncate -s 1792M "$build_dir/root.ext4"
sudo mkfs.ext4 -F -L PIROOT -d "$build_dir/rootfs" "$build_dir/root.ext4"
sudo e2fsck -fn "$build_dir/root.ext4"
# Partition 1 starts at 1MiB, partition 2 at 257MiB. No loop device needed.
truncate -s 2050M "$build_dir/pi-home-alpine-beta.img"
printf 'label: dos\nstart=2048,size=524288,type=c,bootable\nstart=526336,size=3670016,type=83\n' | sfdisk "$build_dir/pi-home-alpine-beta.img"
dd if="$build_dir/boot.fat" of="$build_dir/pi-home-alpine-beta.img" bs=1M seek=1 conv=notrunc status=none
dd if="$build_dir/root.ext4" of="$build_dir/pi-home-alpine-beta.img" bs=1M seek=257 conv=notrunc status=none
cp --sparse=always "$build_dir/pi-home-alpine-beta.img" "$build_dir/pi-home-alpine-beta-touch2-10.img"
cp "$build_dir/boot.fat" "$build_dir/boot-touch2-10.fat"
mcopy -o -i "$build_dir/boot-touch2-10.fat" "$repo/appliance/alpine/config-touch2-10.txt" ::config.txt
mtype -i "$build_dir/boot-touch2-10.fat" ::config.txt | grep -qx 'display_auto_detect=0'
mtype -i "$build_dir/boot-touch2-10.fat" ::config.txt | grep -qx 'dtoverlay=vc4-kms-dsi-ili79600-10-1inch'
dd if="$build_dir/boot-touch2-10.fat" of="$build_dir/pi-home-alpine-beta-touch2-10.img" bs=1M seek=1 conv=notrunc status=none
gzip -c "$build_dir/pi-home-alpine-beta.img" > "$out/pi-home-alpine-beta.img.gz"
gzip -c "$build_dir/pi-home-alpine-beta-touch2-10.img" > "$out/pi-home-alpine-beta-touch2-10.img.gz"
(cd "$out" && sha256sum pi-home-alpine-beta.img.gz > pi-home-alpine-beta.img.gz.sha256)
(cd "$out" && sha256sum pi-home-alpine-beta-touch2-10.img.gz > pi-home-alpine-beta-touch2-10.img.gz.sha256)
cp "$build_dir/rootfs/opt/pi-home/appliance/alpine/packages-resolved.txt" "$out/"
git -C "$repo" rev-parse HEAD > "$out/source-commit.txt"
echo "Alpine Beta image: $out/pi-home-alpine-beta.img.gz"
echo "Alpine Beta Pi 5 + 10-inch Touch Display 2 image: $out/pi-home-alpine-beta-touch2-10.img.gz"
