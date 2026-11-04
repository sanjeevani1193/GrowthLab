"""Sequential, unauthenticated acquisition of the five official Cosmetics files."""

import argparse
import hashlib
import json
import shutil
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REF = "mkechinov/ecommerce-events-history-in-cosmetics-shop"
BASE = "https://www.kaggle.com/api/v1/datasets/"
MONTHS = ("2019-Oct", "2019-Nov", "2019-Dec", "2020-Jan", "2020-Feb")
RESERVE = 20 * 1024**3


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(path)


def get_metadata(endpoint):
    with urllib.request.urlopen(BASE + endpoint + "/" + REF, timeout=60) as r:
        payload = r.read(1_000_001)
    if len(payload) > 1_000_000:
        raise ValueError("Metadata exceeded bounded read")
    return json.loads(payload)


def acquire(root):
    root = root.resolve()
    raw = root / "data/raw"
    archives = root / "data/archives"
    raw.mkdir(parents=True, exist_ok=True)
    archives.mkdir(parents=True, exist_ok=True)
    metadata, listing = get_metadata("view"), get_metadata("list")
    if metadata["currentVersionNumber"] != 6:
        raise ValueError("Source version changed; review before downloading")
    if metadata["licenseName"] != "Data files © Original Authors":
        raise ValueError("License changed; review before downloading")
    if "You can use this dataset for free" not in metadata["description"]:
        raise ValueError("Free-use statement missing; review before downloading")
    files = {f["name"]: f["totalBytes"] for f in listing["datasetFiles"]}
    if set(files) != {m + ".csv" for m in MONTHS}:
        raise ValueError("Unexpected source file list")
    # Allow raw data, conservative Parquet allowance, bounded spill, and an OS reserve.
    required = sum(files.values()) * 3 + 8 * 1024**3 + RESERVE
    if shutil.disk_usage(root).free < required:
        raise RuntimeError(f"Need {required} free bytes including safety reserve")
    manifest_path = root / "docs/phase1/acquisition.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        "dataset_ref": REF, "version": 6, "license": metadata["licenseName"],
        "attribution": "https://www.kaggle.com/datasets/" + REF + " ; https://rees46.com",
        "metadata_sources": [BASE + "view/" + REF, BASE + "list/" + REF],
        "files": [],
    }
    for month in MONTHS:
        name = month + ".csv"
        csv_path, zip_path = raw / name, archives / (name + ".zip")
        previous = next((f for f in manifest["files"] if f["name"] == name), None)
        if csv_path.exists():
            if not previous or csv_path.stat().st_size != files[name] or digest(csv_path) != previous["csv_sha256"]:
                raise RuntimeError(f"Existing {name} is unmanaged or changed; refusing to overwrite")
            print(f"Verified existing {name}; skipping", flush=True)
            continue
        if shutil.disk_usage(root).free < RESERVE + files[name] * 3 + 8 * 1024**3:
            raise RuntimeError("Free disk fell below safe acquisition allowance")
        url = BASE + "download/" + REF + "/" + name + "?datasetVersionNumber=6"
        if not zip_path.exists():
            print(f"Downloading {name} sequentially", flush=True)
            part = zip_path.with_suffix(".zip.part")
            for attempt in range(3):
                try:
                    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
                    with urllib.request.urlopen(request, timeout=120) as response:
                        if response.status != 200:
                            raise RuntimeError(f"Expected full HTTP 200, received {response.status}")
                        with part.open("wb") as target:
                            shutil.copyfileobj(response, target, length=1024 * 1024)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
            part.replace(zip_path)
        # ZipFile checks CRC while reading; only the expected member may be extracted.
        with zipfile.ZipFile(zip_path) as archive:
            if archive.namelist() != [name] or archive.getinfo(name).file_size != files[name]:
                raise ValueError(f"Unexpected archive contents/expanded size for {name}")
            temporary = csv_path.with_suffix(".csv.part")
            with archive.open(name) as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            if temporary.stat().st_size != files[name]:
                raise ValueError(f"Expanded size mismatch for {name}")
            temporary.replace(csv_path)
        entry = {"name": name, "source_url": url, "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
                 "csv_bytes": csv_path.stat().st_size, "zip_bytes": zip_path.stat().st_size,
                 "csv_sha256": digest(csv_path), "zip_sha256": digest(zip_path), "zip_crc_verified": True}
        manifest["files"] = [f for f in manifest["files"] if f["name"] != name] + [entry]
        save_json(manifest_path, manifest)
        print(f"Verified {name}: {entry['csv_bytes']:,} CSV bytes, CRC and SHA-256 recorded", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    acquire(args.root)


if __name__ == "__main__":
    main()
