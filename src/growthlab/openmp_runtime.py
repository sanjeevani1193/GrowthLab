"""Optional project-local OpenMP installation for Apple Silicon / older macOS.

No network access on import/preload. Run this module explicitly to install the
checksum-pinned conda-forge runtime inside the current ignored virtualenv.
"""

import ctypes
import io
import json
import platform
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from growthlab.acquire import digest, save_json

URL="https://conda.anaconda.org/conda-forge/osx-arm64/llvm-openmp-20.1.8-h4a912ad_3.conda"
SHA256="09585f9d532eab024b0cb17b0797a6b4c381ee1f4e8643a2068b511caf843796"


def preload_local_openmp():
    if sys.platform!="darwin" or platform.machine()!="arm64":return None
    folder=Path(sys.prefix)/"native"
    library=folder/"lib/libomp.dylib"
    if not library.exists():return None
    metadata=json.loads((folder/"provenance.json").read_text())
    if metadata["archive_sha256"]!=SHA256 or digest(library)!=metadata["library_sha256"]:
        raise ValueError("Local OpenMP runtime fingerprint changed")
    ctypes.CDLL(str(library.resolve()),mode=ctypes.RTLD_GLOBAL)
    return metadata


def main():
    if sys.platform!="darwin" or platform.machine()!="arm64" or sys.prefix==sys.base_prefix:
        raise RuntimeError("This optional installer is only for an Apple Silicon virtualenv")
    if preload_local_openmp() is not None:
        print("Verified existing project-local OpenMP; no download needed")
        return
    from compression import zstd  # Python 3.14, the tested local interpreter.
    import hashlib
    folder=Path(sys.prefix)/"native"
    folder.mkdir(exist_ok=True)
    with urllib.request.urlopen(URL,timeout=30) as response:data=response.read(1_000_000)
    if hashlib.sha256(data).hexdigest()!=SHA256:raise ValueError("OpenMP archive checksum mismatch")
    (folder/"llvm-openmp.conda").write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.namelist():
            if not member.endswith(".tar.zst"):continue
            with tarfile.open(fileobj=io.BytesIO(zstd.decompress(archive.read(member)))) as tar:
                for entry in tar.getmembers():
                    if entry.name=="lib/libomp.dylib":target=folder/"lib/libomp.dylib"
                    elif entry.name.startswith("info/licenses/") and entry.isfile():target=folder/"licenses"/Path(entry.name).name
                    else:continue
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(tar.extractfile(entry).read())
    save_json(folder/"provenance.json",{"source_url":URL,"archive_sha256":SHA256,
        "license":"Apache-2.0 WITH LLVM-exception","library_sha256":digest(folder/"lib/libomp.dylib")})
    preload_local_openmp()
    print("Installed and verified project-local OpenMP")


if __name__=="__main__":main()
