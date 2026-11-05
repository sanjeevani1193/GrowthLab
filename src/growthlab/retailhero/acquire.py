"""Fetch only selected members of the official ZIP using HTTP byte ranges.

No archive-wide download, authentication, or model execution. ZIP CRCs verify
decompression; SHA-256 hashes identify the exact extracted local inputs.
"""
import hashlib
import argparse
import csv
import io
import json
import shutil
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

OFFICIAL = "https://ods.ai/competitions/x5-retailhero-uplift-modeling/data"
ARCHIVE = "https://storage.yandexcloud.net/datasouls-ods/materials/9c6913e5/retailhero-uplift.zip"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class RangeReader(io.RawIOBase):
    """Seekable read-only remote file; reject servers ignoring Range/If-Match."""

    def __init__(self, url):
        self.url, self.pos, self.transferred = url, 0, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
            self.etag = r.headers["ETag"]

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        new = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        if new < 0:
            raise ValueError("negative seek")
        self.pos = new
        return new

    def read(self, size=-1):
        size = self.size - self.pos if size < 0 else min(size, self.size - self.pos)
        if size <= 0:
            return b""
        # zipfile requests small pieces; never silently fetch an entire archive.
        if size > 16 * 1024 * 1024:
            raise ValueError("oversized range request")
        end = self.pos + size - 1
        request = urllib.request.Request(self.url, headers={
            "Range": f"bytes={self.pos}-{end}", "If-Match": self.etag})
        with urllib.request.urlopen(request, timeout=60) as r:
            if (r.status != 206 or r.headers.get("Content-Range") !=
                    f"bytes {self.pos}-{end}/{self.size}" or r.headers.get("ETag") != self.etag):
                raise ValueError("server did not honor immutable byte range")
            data = r.read(size + 1)
        if len(data) != size:
            raise ValueError("truncated range")
        self.pos += size
        self.transferred += size
        return data


def acquire(root=Path(".")):
    dest = root / "data/retailhero/raw"
    docs = root / "docs/causal/phase5"
    dest.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    manifest_path = docs / "acquisition.json"
    if manifest_path.exists():
        saved = json.loads(manifest_path.read_text())
        for f in saved["files"]:
            if sha256(root / f["path"]) != f["sha256"]:
                raise ValueError("existing raw file differs from manifest")
        return saved
    if shutil.disk_usage(dest).free < 1024**3:
        raise RuntimeError("require at least 1 GiB free for the two small files")
    remote = RangeReader(ARCHIVE)
    with zipfile.ZipFile(remote) as z:
        inventory = [{"name": i.filename, "bytes": i.file_size,
                      "compressed_bytes": i.compress_size, "crc32": f"{i.CRC:08x}"}
                     for i in z.infolist()]
        files = []
        for name in ("uplift_train.csv", "clients.csv"):
            matches = [i for i in z.infolist() if Path(i.filename).name == name]
            if len(matches) != 1:
                raise ValueError(f"ambiguous/missing member {name}")
            info = matches[0]
            if info.file_size > 100 * 1024**2:
                raise ValueError("unexpectedly large requested member")
            path = dest / name
            if path.exists():
                raise FileExistsError(f"unmanifested file: {path}; will not overwrite")
            part = path.with_suffix(".csv.part")
            with z.open(info) as src, part.open("xb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            if part.stat().st_size != info.file_size:
                raise ValueError("size mismatch")
            part.rename(path)
            files.append({"path": str(path.relative_to(root)), "member": info.filename,
                          "bytes": info.file_size, "compressed_bytes": info.compress_size,
                          "zip_crc32": f"{info.CRC:08x}", "sha256": sha256(path)})
        # Small source documentation only, never execute the supplied baseline.
        source = root / "data/retailhero/source"
        source.mkdir(parents=True, exist_ok=True)
        for i in z.infolist():
            if Path(i.filename).name in {"description.txt", "uplift_solution.py", "requirements.txt"}:
                if i.file_size < 100_000:
                    (source / ("official_" + Path(i.filename).name)).write_bytes(z.read(i))
    result = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
              "official_page": OFFICIAL, "archive_url": ARCHIVE,
              "archive_bytes": remote.size, "archive_etag": remote.etag,
              "range_bytes_transferred": remote.transferred,
              "archive_inventory": inventory, "files": files,
              "attribution": "X5 Retail Group / RetailHero, hosted by ODS.AI",
              "license": "No explicit dataset reuse license found on official data page or mirrored card. Attribution is not a grant of redistribution rights. Data remain local; no commercial-use permission asserted.",
              "method": "Official archive byte ranges; selected members only; ZIP CRC checked by zipfile. ETag is not treated as a SHA-256."}
    manifest_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def inspect_history(root=Path(".")):
    """Inspect a bounded prefix, never acquire the full purchase history."""
    dest = root / "data/retailhero/source/purchases_prefix.csv"
    record = root / "docs/causal/phase5/purchases_schema.json"
    if record.exists() and dest.exists():
        old = json.loads(record.read_text())
        if "prefix_sha256" in old:
            if old["prefix_sha256"] != sha256(dest):
                raise ValueError("purchase prefix changed")
            return old
    remote = RangeReader(ARCHIVE)
    with zipfile.ZipFile(remote) as z:
        info = z.getinfo("data/purchases.csv")
        with z.open(info) as f:
            prefix = f.read(8192)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.read_bytes() != prefix:
        raise ValueError("existing prefix disagrees with official archive")
    dest.write_bytes(prefix)
    # Drop the final partial CSV record; sample facts cannot describe all rows.
    rows = list(csv.DictReader(io.StringIO("\n".join(prefix.decode().splitlines()[:-1]))))
    result = {"archive_url": ARCHIVE, "archive_etag": remote.etag,
              "member": info.filename, "file_bytes": info.file_size,
              "compressed_bytes": info.compress_size,
              "header": prefix.decode().splitlines()[0].split(","),
              "prefix_uncompressed_bytes": len(prefix), "prefix_sha256": sha256(dest),
              "range_bytes_transferred": remote.transferred,
              "complete_prefix_rows": len(rows),
              "distinct_prefix_customer_transactions": len({(r['client_id'], r['transaction_id']) for r in rows}),
              "scope": "8192-byte prefix only; not a representative sample. No full-table statistics or campaign cutoff inferred."}
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-history", action="store_true")
    args = parser.parse_args()
    print(json.dumps(inspect_history() if args.inspect_history else acquire(), indent=2))
