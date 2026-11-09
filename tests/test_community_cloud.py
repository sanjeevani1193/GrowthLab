"""Guard free-host dependency discovery and the preserved runtime fingerprints."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommunityCloudPreparationTests(unittest.TestCase):
    def test_host_requirements_reuse_verified_runtime_locks(self):
        lines = [s for s in (ROOT / 'requirements.txt').read_text().splitlines()
                 if s and not s.startswith('#')]
        self.assertEqual(lines, ['-r requirements-container.lock'])
        linux = (ROOT / 'requirements-container.lock').read_text()
        self.assertIn('-r requirements-studio.lock', linux)
        self.assertIn('watchdog==7.1.0', linux)
        self.assertNotIn('-e ', linux)

    def test_no_higher_priority_dependency_manager_shadows_requirements(self):
        self.assertTrue((ROOT / 'streamlit_app.py').is_file())
        for name in ('uv.lock', 'Pipfile', 'environment.yml'):
            self.assertFalse((ROOT / name).exists(), name)

    def test_approved_app_evidence_and_docker_files_remain_identical(self):
        receipt = json.loads((ROOT / 'docs/deployment/phase12a_verification.json').read_text())
        for group in ('runtime_file_sha256', 'packaging_sha256'):
            for name, digest in receipt[group].items():
                with self.subTest(path=name):
                    self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
