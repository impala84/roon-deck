"""NEA radar rain arrival service and chronological replay."""
import argparse
import concurrent.futures
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image
from pyproj import Proj
from scipy.ndimage import label
from scipy.signal import correlate

API = "https://api-open.data.gov.sg/v2/real-time/api/weather-radar-images/70km"
STEP = timedelta(minutes=5)
SGT = timezone(timedelta(hours=8))


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "NEA-Rain-Nowcast/1.0", "Accept": "*/*"}), timeout=5) as response:
        return response.read()


def catalog(*, attempts=1, **params):
    url = API + ("?" + urlencode(params) if params else "")
    for attempt in range(attempts):
        try:
            payload = json.loads(fetch(url))
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt + 1 == attempts:
                raise
            time.sleep(65)
    if payload["code"] != 0:
        raise ValueError(payload.get("errorMsg", "Radar request failed"))
    return payload["data"]


def archive(day, root):
    directory = root / day
    directory.mkdir(parents=True, exist_ok=True)
    cursor = directory / "cursor"
    if cursor.exists() and not cursor.read_text():
        return
    params = {"date": day}
    if cursor.exists():
        params["paginationToken"] = cursor.read_text()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        while True:
            data = catalog(attempts=4, **params)
            (directory / "grid.json").write_text(json.dumps({
                key: data[key] for key in ("projection", "boundaryBox")
            }))
            def save(record):
                path = directory / (record["timestamp"][11:19].replace(":", "") + ".png")
                if not path.exists():
                    raw = fetch(record["image"]["url"])
                    with Image.open(BytesIO(raw)) as image:
                        image.verify()
                    temporary = path.with_suffix(".part")
                    temporary.write_bytes(raw)
                    temporary.replace(path)
            list(pool.map(save, data["records"]))
            cursor.write_text(data.get("paginationToken") or "")
            if not data.get("paginationToken"):
                break
            params["paginationToken"] = data["paginationToken"]


def radar_frame(raw, grid, latitude, longitude):
    rgba = np.asarray(Image.open(BytesIO(raw)).convert("RGBA"))
    center = grid["projection"]["center"]
    project = Proj(proj="aeqd", lat_0=center["latitude"], lon_0=center["longitude"], datum="WGS84")
    bounds = grid["boundaryBox"]
    ul, lr = (project(bounds[key]["longitude"], bounds[key]["latitude"])
              for key in ("upperLeft", "lowerRight"))
    x, y = project(longitude, latitude)
    height, width = rgba.shape[:2]
    col = int(width * (x - ul[0]) / (lr[0] - ul[0]))
    row = int(height * (y - ul[1]) / (lr[1] - ul[1]))
    if min(row, col, height - row - 1, width - col - 1) < 85:
        raise ValueError("Location is too close to the edge of the local radar grid")
    # NEA's radar PNG has transparent background and opaque rainfall echoes.
    return rgba[row-85:row+86, col-85:col+86, 3] == 255


def wet_near(mask, row=85, col=85):
    # Five pixels span about 1.5 km on the 480 px, 140 km grid.
    return np.count_nonzero(mask[row-2:row+3, col-2:col+3]) >= 8


def estimate(frames, now):
    if not frames or now - frames[-1][0] > 2 * STEP:
        return {"status": "unavailable"}
    stamp, latest = frames[-1]
    result = {"status": "clear", "radar_at": stamp.isoformat()}
    if wet_near(latest):
        return result | {"status": "raining"}
    earlier = dict(frames).get(stamp - 2 * STEP)
    if earlier is None:
        return result | {"status": "warming_up"}
    # Match the local pattern over ten minutes. Search +/- 30 pixels (~53 km/h).
    old = earlier[30:-30, 30:-30].astype(float)
    if latest.sum() < 25:
        return result
    if old.sum() < 25:
        return result | {"status": "uncertain"}
    overlap = correlate(latest.astype(float), old, mode="valid", method="fft")
    area = correlate(latest.astype(float), np.ones(old.shape), mode="valid", method="fft")
    similarity = 2 * overlap / (old.sum() + area)
    y, x = np.unravel_index(similarity.argmax(), similarity.shape)
    dy, dx = y - 30, x - 30
    if similarity[y, x] < 0.45 or max(abs(dy), abs(dx)) >= 30:
        return result | {"status": "uncertain"}
    # Ignore isolated echoes before projecting the rain mask.
    regions, _ = label(latest)
    sizes = np.bincount(regions.ravel())
    sizes[0] = 0
    coherent = sizes[regions] >= 25
    for minutes in range(5, 36, 5):
        row = 85 - round(dy * minutes / 10)
        col = 85 - round(dx * minutes / 10)
        if 2 <= row < 169 and 2 <= col < 169 and wet_near(coherent, row, col):
            eta = stamp + timedelta(minutes=minutes)
            if eta <= now:
                return result | {"status": "uncertain"}
            if eta - now <= timedelta(minutes=30):
                return result | {"status": "approaching", "arrival_at": eta.isoformat()}
    return result


def replay(root, coordinates):
    frames = []
    for directory in sorted(root.iterdir()):
        grid = json.loads((directory / "grid.json").read_text())
        for path in sorted(directory.glob("*.png")):
            stamp = datetime.strptime(directory.name + path.stem, "%Y-%m-%d%H%M%S").replace(tzinfo=SGT)
            frames.append((stamp, radar_frame(path.read_bytes(), grid, *coordinates)))
    hits = false = missed = correct = 0
    errors = []
    observed_onsets = set()
    alerted_onsets = set()
    eligible = 0
    for index in range(2, len(frames) - 6):
        now, mask = frames[index]
        if wet_near(mask):
            continue
        past = frames[index-2:index+1]
        future = frames[index+1:index+7]
        if past[0][0] != now - 2 * STEP or future[-1][0] != now + 6 * STEP:
            continue
        eligible += 1
        actual = next((stamp for stamp, image in future if wet_near(image)), None)
        prediction = estimate(past, now).get("arrival_at")
        if actual:
            observed_onsets.add(actual)
        if prediction and actual:
            hits += 1
            alerted_onsets.add(actual)
            errors.append(abs((datetime.fromisoformat(prediction) - actual).total_seconds()) / 60)
        elif prediction:
            false += 1
        elif actual:
            missed += 1
        else:
            correct += 1
    print(json.dumps({"frames": len(frames), "dry_scan_windows": eligible, "hits": hits,
                      "false_alarms": false, "misses": missed, "correct_no_alert": correct,
                      "observed_onsets": len(observed_onsets), "alerted_onsets": len(alerted_onsets),
                      "median_absolute_error_minutes": float(np.median(errors)) if errors else None,
                      "mean_absolute_error_minutes": float(np.mean(errors)) if errors else None}, indent=2))


def update_frames(frames, coordinates):
    data = catalog()
    record = data["records"][0]
    stamp = datetime.fromisoformat(record["timestamp"])

    def add_frame(record, grid):
        timestamp = datetime.fromisoformat(record["timestamp"])
        if timestamp not in dict(frames):
            mask = radar_frame(fetch(record["image"]["url"]), grid, *coordinates)
            frames.append((timestamp, mask))
            frames.sort(key=lambda frame: frame[0])
            del frames[:-7]

    add_frame(record, data)
    prior = stamp - 2 * STEP
    if prior not in dict(frames) and datetime.now(SGT) - stamp <= 2 * STEP:
        older = catalog(date=prior.strftime("%Y-%m-%dT%H:%M:%S"))
        add_frame(older["records"][0], older)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    archive_args = commands.add_parser("archive")
    archive_args.add_argument("directory", type=Path)
    archive_args.add_argument("days", nargs="+")
    replay_args = commands.add_parser("replay")
    replay_args.add_argument("directory", type=Path)
    args = parser.parse_args()
    coordinates = args.latitude, args.longitude
    if args.command == "archive":
        for day in args.days:
            archive(day, args.directory)
    else:
        replay(args.directory, coordinates)
