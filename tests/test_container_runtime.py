"""Native CI smoke-test guards, using synthetic metadata and tiny temp files."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('container_runtime', ROOT / 'scripts/verify_container_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class ContainerRuntimeTests(unittest.TestCase):
    def test_native_architecture_aliases_and_unknown_machine(self):
        for machine, expected in (('x86_64', 'amd64'), ('AMD64', 'amd64'), ('aarch64', 'arm64'), ('arm64', 'arm64')):
            self.assertEqual(RUNTIME.native_architecture(machine), expected)
        with self.assertRaises(ValueError):
            RUNTIME.native_architecture('unknown')

    def test_amd64_default_cannot_run_on_arm_host(self):
        with patch('sys.argv', ['verify_container_runtime.py']), \
                patch.object(RUNTIME.platform, 'machine', return_value='arm64'), \
                patch.object(RUNTIME, 'docker') as docker, patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                RUNTIME.main()
            docker.assert_not_called()

    def test_http_target_must_be_local_without_credentials(self):
        self.assertEqual(RUNTIME.local_url('http://127.0.0.1:8502/'), 'http://127.0.0.1:8502')
        self.assertEqual(RUNTIME.local_url('http://localhost:8502'), 'http://localhost:8502')
        for target in ('https://example.com', 'http://127.0.0.1.evil', 'http://localhost/path',
                       'http://user:password@localhost', 'http://localhost?token=example'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                RUNTIME.local_url(target)

    def test_isolation_rejects_mounts_user_resources_and_public_bind(self):
        state = {'State': {'Running': True, 'OOMKilled': False}, 'RestartCount': 0,
            'Config': {'User': '10001:10001'}, 'Mounts': [], 'HostConfig': {
                'ReadonlyRootfs': True, 'Memory': 536870912, 'NanoCpus': 1000000000,
                'PidsLimit': 128, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                'PortBindings': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8502'}]}}}
        image = {'Os': 'linux', 'Architecture': 'amd64'}
        RUNTIME.check_isolation(state, image, 'amd64')
        for mutation in ('mount', 'user', 'memory', 'readonly', 'public'):
            bad = copy.deepcopy(state)
            if mutation == 'mount':
                bad['Mounts'] = [{'Type': 'bind'}]
            elif mutation == 'user':
                bad['Config']['User'] = '0'
            elif mutation == 'memory':
                bad['HostConfig']['Memory'] = 0
            elif mutation == 'readonly':
                bad['HostConfig']['ReadonlyRootfs'] = False
            else:
                bad['HostConfig']['PortBindings']['8080/tcp'][0]['HostIp'] = '0.0.0.0'
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                RUNTIME.check_isolation(bad, image, 'amd64')
        with self.assertRaises(AssertionError):
            RUNTIME.check_isolation(state, image, 'arm64')

    def test_exact_file_set_and_hashes_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.dockerignore').write_text('**\n!Dockerfile\n!.dockerignore\n!streamlit_app.py\n')
            app = root / 'streamlit_app.py'
            app.write_text("print('synthetic packaging fixture')\n")
            files = {'streamlit_app.py': hashlib.sha256(app.read_bytes()).hexdigest()}
            RUNTIME.check_app_files(files, root)
            with self.assertRaises(AssertionError):
                RUNTIME.check_app_files({**files, 'model.joblib': 'not-a-real-model'}, root)
            app.write_text('changed synthetic fixture\n')
            with self.assertRaises(AssertionError):
                RUNTIME.check_app_files(files, root)

    def test_workflow_is_native_read_only_and_never_publishes_images(self):
        text = (ROOT / '.github/workflows/studio-amd64.yml').read_text()
        self.assertIn('runs-on: ubuntu-24.04', text)
        self.assertIn('test "$(uname -m)" = x86_64', text)
        self.assertIn('contents: read', text)
        self.assertEqual(text.split("'on':", 1)[1].split('permissions:', 1)[0].strip(), 'workflow_dispatch:')
        self.assertNotIn('\n  push:', text)
        self.assertNotIn('\n  pull_request:', text)
        self.assertIn('if: ${{ github.event.repository.private == false }}', text)
        self.assertIn('persist-credentials: false', text)
        self.assertRegex(text, r'actions/checkout@[0-9a-f]{40}')
        self.assertIn('--platform linux/amd64', text)
        self.assertIn('scripts/verify_decision_studio.py', text)
        self.assertIn('scripts/verify_container_runtime.py', text)
        for forbidden in ('docker push', 'docker login', 'gcloud ', 'pull_request_target:',
                          'setup-qemu', 'secrets.', 'id-token: write', 'packages: write'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
