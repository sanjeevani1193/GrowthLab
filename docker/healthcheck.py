"""Probe Streamlit with the Python standard library; no curl layer needed."""
import sys
from urllib.error import URLError
from urllib.request import urlopen

from entrypoint import configured_port


def main():
    try:
        with urlopen(f'http://127.0.0.1:{configured_port()}/_stcore/health', timeout=3) as response:
            if response.status == 200 and response.read(16).strip() == b'ok':
                return 0
    except (OSError, URLError, ValueError):
        pass
    print('Streamlit health check failed.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
