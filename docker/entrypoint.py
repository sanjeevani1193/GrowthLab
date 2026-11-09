"""Start the existing app on PORT; replace this process for clean shutdown."""
import os
from pathlib import Path
import sys


def configured_port():
    value = os.environ.get('PORT', '8080')
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError('PORT must be an integer between 1 and 65535.')
    return int(value)


def main():
    try:
        port = configured_port()
    except ValueError as error:
        raise SystemExit(str(error)) from error
    Path(os.environ.get('HOME', '/tmp/growthlab-studio')).mkdir(parents=True, exist_ok=True)
    os.execv(sys.executable, [
        sys.executable, '-m', 'streamlit', 'run', 'streamlit_app.py',
        '--server.address=0.0.0.0', f'--server.port={port}',
        '--server.headless=true', '--browser.gatherUsageStats=false',
        '--server.fileWatcherType=none', '--server.runOnSave=false',
    ])


if __name__ == '__main__':
    main()
