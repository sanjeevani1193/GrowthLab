"""Small packaging-contract checks; no Docker daemon or research data needed."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'docker' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENTRY = load_module('studio_container_entrypoint', 'entrypoint.py')
with patch.dict(sys.modules, {'entrypoint': ENTRY}):
    HEALTH = load_module('studio_container_health', 'healthcheck.py')


class ContainerPackagingTests(unittest.TestCase):
    def test_port_default_override_and_invalid_values(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ENTRY.configured_port(), 8080)
        for value in ('8503', '65535', '1'):
            with patch.dict(os.environ, {'PORT': value}):
                self.assertEqual(ENTRY.configured_port(), int(value))
        for value in ('', '0', '-1', '65536', '80.0', ' 8080', '٨٠', '8080; echo unsafe'):
            with self.subTest(port=value), patch.dict(os.environ, {'PORT': value}):
                with self.assertRaises(ValueError):
                    ENTRY.configured_port()

    def test_entrypoint_executes_existing_app_without_shell(self):
        with patch.dict(os.environ, {'PORT': '8123', 'HOME': '/tmp/studio-test'}), \
                patch.object(ENTRY.Path, 'mkdir'), patch.object(ENTRY.os, 'execv') as execute:
            ENTRY.main()
        executable, args = execute.call_args.args
        self.assertEqual(executable, sys.executable)
        self.assertEqual(args[:5], [sys.executable, '-m', 'streamlit', 'run', 'streamlit_app.py'])
        self.assertIn('--server.port=8123', args)
        self.assertIn('--server.address=0.0.0.0', args)
        self.assertIn('--server.fileWatcherType=none', args)

    def test_healthcheck_uses_configured_loopback_endpoint(self):
        response = MagicMock(status=200)
        response.read.return_value = b'ok'
        with patch.dict(os.environ, {'PORT': '8123'}), patch.object(HEALTH, 'urlopen') as request:
            request.return_value.__enter__.return_value = response
            self.assertEqual(HEALTH.main(), 0)
            request.assert_called_once_with('http://127.0.0.1:8123/_stcore/health', timeout=3)

    def test_healthcheck_rejects_failures_and_wrong_body(self):
        for status, body in ((503, b'ok'), (200, b'not ready')):
            response = MagicMock(status=status)
            response.read.return_value = body
            with patch.object(HEALTH, 'urlopen') as request, patch('sys.stderr'):
                request.return_value.__enter__.return_value = response
                self.assertEqual(HEALTH.main(), 1)
        for error in (URLError('not ready'), TimeoutError('not ready')):
            with patch.object(HEALTH, 'urlopen', side_effect=error), patch('sys.stderr'):
                self.assertEqual(HEALTH.main(), 1)

    def test_image_contract_and_platform_specific_lock(self):
        text = (ROOT / 'Dockerfile').read_text()
        self.assertRegex(text, r'FROM python:3\.14\.7-slim-bookworm@sha256:[a-f0-9]{64}')
        self.assertIn('USER 10001:10001', text)
        self.assertIn('HEALTHCHECK ', text)
        self.assertIn('--only-binary=:all:', text)
        self.assertNotIn('COPY . ', text)
        self.assertNotIn('pip install -e', text)
        lock = (ROOT / 'requirements-container.lock').read_text()
        self.assertIn('-r requirements-studio.lock', lock)
        self.assertIn('watchdog==7.1.0; platform_system != "Darwin"', lock)

    def test_context_allowlist_covers_evidence_and_rejects_broad_exceptions(self):
        lines = [s for s in (ROOT / '.dockerignore').read_text().splitlines() if s and not s.startswith('#')]
        self.assertEqual(lines[0], '**')
        for index, line in enumerate(lines):
            if line.startswith('!') and line.endswith('/'):
                # An allowed directory must not implicitly admit all descendants.
                self.assertEqual(lines[index + 1], line[1:] + '**')
        allowed = {s[1:] for s in lines if s.startswith('!') and not s.endswith('/')}
        self.assertTrue(all('*' not in s and Path(s).is_file() for s in allowed))
        manifest = json.loads((ROOT / 'docs/decision_studio/evidence_manifest.json').read_text())
        for entry in manifest['sources'].values():
            self.assertIn(entry['path'], allowed)
        for private in ('data/raw/2019-Oct.csv', '.env', '.git/config', '.streamlit/secrets.toml',
                        '.venv/bin/python', 'src/growthlab/studio/__pycache__/app.pyc',
                        'src/growthlab/modeling.py', 'docs/deployment/private.json'):
            self.assertNotIn(private, allowed)


if __name__ == '__main__':
    unittest.main()
