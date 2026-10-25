#!/usr/bin/env python3
"""Safely grow the mounted Alpine root partition and ext4 filesystem once."""
import os
from pathlib import Path
import subprocess
import time


STATE = Path("/var/lib/pi-home")
LOG = Path("/var/log/pi-home/storage.log")
SYS_DEV_BLOCK = Path("/sys/dev/block")
MIN_UNUSED_BYTES = 8 * 1024 * 1024


def append_log(message: str, log: Path = LOG) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o640)
    with os.fdopen(descriptor, "a") as output:
        os.fchmod(output.fileno(), 0o640)
        output.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n")


def write_status(state: Path, message: str) -> None:
    temporary = state / ".storage-status.tmp"
    temporary.write_text(message + "\n")
    temporary.chmod(0o644)
    temporary.replace(state / "storage-status")


def root_filesystem_type(mountinfo: Path = Path("/proc/self/mountinfo")) -> str:
    for line in mountinfo.read_text().splitlines():
        left, separator, right = line.partition(" - ")
        fields = left.split()
        if separator and len(fields) >= 5 and fields[4] == "/":
            return right.split()[0]
    raise RuntimeError("Could not identify the mounted root filesystem")


def root_partition(sys_dev_block: Path = SYS_DEV_BLOCK, device_number=None):
    if device_number is None:
        stat = os.stat("/")
        device_number = (os.major(stat.st_dev), os.minor(stat.st_dev))
    link = sys_dev_block / f"{device_number[0]}:{device_number[1]}"
    partition_sysfs = link.resolve(strict=True)
    partition_number_file = partition_sysfs / "partition"
    if not partition_number_file.is_file():
        raise RuntimeError("Root filesystem is not on a directly growable disk partition")
    disk_sysfs = partition_sysfs.parent
    partition_number = int(partition_number_file.read_text().strip())
    start_bytes = int((partition_sysfs / "start").read_text().strip()) * 512
    partition_bytes = int((partition_sysfs / "size").read_text().strip()) * 512
    disk_bytes = int((disk_sysfs / "size").read_text().strip()) * 512
    return Path("/dev") / disk_sysfs.name, Path("/dev") / partition_sysfs.name, partition_number, max(0, disk_bytes - start_bytes - partition_bytes)


def run(command, log: Path = LOG) -> None:
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o640)
    with os.fdopen(descriptor, "a") as output:
        os.fchmod(output.fileno(), 0o640)
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} exited with status {result.returncode}")


def expand(state: Path = STATE, log: Path = LOG, sys_dev_block: Path = SYS_DEV_BLOCK, device_number=None) -> str:
    marker = state / "root-storage-expanded"
    if marker.exists():
        return "already completed"
    state.mkdir(parents=True, exist_ok=True)
    if root_filesystem_type() != "ext4":
        raise RuntimeError("Automatic root expansion supports ext4 only")
    disk, partition, number, unused = root_partition(sys_dev_block, device_number)
    append_log(f"Detected ext4 root {partition} on {disk}; {unused} bytes remain after its partition", log)
    if unused > MIN_UNUSED_BYTES:
        append_log(f"Growing partition {number} to use the remaining device space", log)
        run(["/usr/bin/growpart", str(disk), str(number)], log)
    else:
        append_log("Root partition already occupies the available device space", log)
    # Always run after the partition check. This completes an interrupted boot
    # where growpart succeeded but resize2fs had not yet run.
    append_log(f"Growing ext4 filesystem on {partition}", log)
    run(["/usr/sbin/resize2fs", str(partition)], log)
    marker.write_text("complete\n")
    marker.chmod(0o600)
    write_status(state, "Expanded and ready" if unused > MIN_UNUSED_BYTES else "Ready")
    append_log("Root storage expansion completed", log)
    return "expanded" if unused > MIN_UNUSED_BYTES else "filesystem checked"


def main() -> int:
    try:
        result = expand(STATE, LOG, SYS_DEV_BLOCK)
        append_log("First-boot storage result: " + result, LOG)
    except Exception as error:
        # OpenRC deliberately treats this as recoverable: RoonDeck must still
        # start so the owner can diagnose or repair the card.
        append_log("Root storage expansion failed safely: " + str(error), LOG)
        STATE.mkdir(parents=True, exist_ok=True)
        write_status(STATE, "Expansion needs attention; see storage.log")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
