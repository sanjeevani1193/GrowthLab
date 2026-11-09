"""Audit an already running, native Docker container without research records.

The default requires AMD64. ARM64 is an explicit local harness check, never
reported as AMD64 evidence. Only small public aggregate summaries are emitted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]

# Executed inside the image, not in a research environment. No models are loaded.
CONTAINER_AUDIT = r'''
from pathlib import Path
import hashlib, importlib.metadata as metadata, json, os, sys
sys.path.insert(0, '/app/src')
from growthlab.studio.evidence import MANIFEST, load_evidence
from growthlab.studio.calculations import plan_experiment, scenario_from_inputs, result_payload
root = Path('/app')
assert os.getuid() == 10001
manifest = json.loads((root / MANIFEST).read_text())
evidence = {name: load_evidence(name) for name in manifest['sources']}
for name in ('data', 'artifacts', '.git', '.venv', 'tests'):
    assert not (root / name).exists(), name
for name in ('duckdb', 'xgboost', 'scikit-learn', 'joblib', 'playwright'):
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError('Unexpected research/test dependency: ' + name)
files = {}
for path in root.rglob('*'):
    if path.is_file():
        assert path.suffix not in ('.csv', '.parquet', '.npz', '.joblib', '.pkl', '.duckdb', '.pyc')
        assert b'/Users/' not in path.read_bytes()
        files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
pins = {}
for filename in ('requirements-studio.lock', 'requirements-container.lock'):
    for line in (root / filename).read_text().splitlines():
        if '==' in line:
            name, version = line.split('==', 1)
            pins[name] = version.split(';', 1)[0].strip()
for name, version in pins.items():
    assert metadata.version(name) == version, name
purchase = evidence['purchase']; xgb = purchase['models']['xgboost']['test']
ranking = evidence['ranking']['methods']['ml']['10']
assert round(xgb['roc_auc'], 4) == .8487
assert round(xgb['lift_at_top_10_percent'], 2) == 5.92
assert xgb['top_10_percent_positive_labels'] == 324 and purchase['test_positive_labels'] == 547
assert round(evidence['experiment']['statistics']['difference_pp'], 2) == 3.39
assert evidence['aa']['false_positives']['empirical_rate'] == .043
assert evidence['ab']['empirical_power']['empirical_rate'] == .793
assert round(ranking['recall_macro'] * 100, 2) == 18.42
assert round(ranking['ndcg_macro'], 5) == .21625
assert plan_experiment(.2, .03, .05, .8)['total_n'] == 5886
assert plan_experiment(.2, .03, .05, .8, .3)['total_n'] == 6949
for reward, expected in ((5, '-550'), (0, '600')):
    result = result_payload(scenario_from_inputs(1000, 20, 23, 20, reward, 100, 0))
    assert result['expected_values']['net_incremental_contribution_eur'] == expected
print(json.dumps({'uid': os.getuid(), 'python': sys.version.split()[0],
    'runtime_package_count': len(pins), 'evidence_count': len(evidence),
    'file_sha256': files, 'frozen_headlines_match': True,
    'planning_and_reward_checks': 'passed', 'no_data_models_or_mac_paths': True}))
'''


def native_architecture(machine):
    aliases = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}
    if machine.lower() not in aliases:
        raise ValueError('Unsupported verification host architecture.')
    return aliases[machine.lower()]


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Use a plain localhost HTTP base URL without credentials.')
    return value.rstrip('/')


def docker(*args, input_text=None):
    return subprocess.check_output(['docker', *args], input=input_text, text=True, timeout=60)


def inspect_container(name):
    return json.loads(docker('inspect', name))[0]


def check_isolation(state, image, expected_architecture):
    assert image['Os'] == 'linux' and image['Architecture'] == expected_architecture
    assert state['State']['Running'] and not state['State']['OOMKilled']
    assert state['RestartCount'] == 0 and state['Config']['User'] == '10001:10001'
    host = state['HostConfig']
    assert host['ReadonlyRootfs'] and host['Memory'] == 512 * 1024 * 1024
    assert host['NanoCpus'] == 1000000000 and host['PidsLimit'] == 128
    assert 'ALL' in host['CapDrop']
    assert 'no-new-privileges:true' in host['SecurityOpt']
    assert not any(m['Type'] in ('bind', 'volume') for m in state['Mounts'])
    bindings = [b for group in host['PortBindings'].values() for b in group]
    assert bindings and all(b['HostIp'] == '127.0.0.1' for b in bindings)


def check_app_files(files, root=ROOT):
    allowed = {line[1:] for line in (root / '.dockerignore').read_text().splitlines()
               if line.startswith('!') and not line.endswith('/')}
    assert set(files) == allowed - {'Dockerfile', '.dockerignore'}
    for name, digest in files.items():
        path = (root / name).resolve()
        assert path.is_relative_to(root.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='growthlab-ci')
    parser.add_argument('--expected-architecture', choices=('amd64', 'arm64'), default='amd64')
    parser.add_argument('--url', default='http://127.0.0.1:8502')
    parser.add_argument('--output', type=Path, default=Path('/tmp/growthlab-container-verification.json'))
    args = parser.parse_args()
    if native_architecture(platform.machine()) != args.expected_architecture:
        parser.error('Native host architecture does not match the requested test; do not emulate.')
    base = local_url(args.url)
    start = time.monotonic()
    while time.monotonic() - start < 60:
        try:
            with urlopen(base + '/_stcore/health', timeout=2) as response:
                assert response.status == 200 and response.read(16).strip() == b'ok'
            state = inspect_container(args.container)
            if state['State']['Health']['Status'] == 'healthy':
                break
        except (OSError, URLError):
            pass
        time.sleep(.5)
    else:
        raise SystemExit('Container HTTP/Docker health did not become ready within 60 seconds.')
    image = json.loads(docker('image', 'inspect', state['Image']))[0]
    check_isolation(state, image, args.expected_architecture)
    result = json.loads(docker('exec', '-i', args.container, 'python', '-', input_text=CONTAINER_AUDIT))
    check_app_files(result.pop('file_sha256'))
    logs = subprocess.check_output(['docker', 'logs', args.container], stderr=subprocess.STDOUT, text=True)
    assert not re.search(r'External URL|/Users/|Traceback|PRIVATE KEY|AKIA[0-9A-Z]{16}', logs)
    result.update({'tested_platform': 'linux/' + args.expected_architecture,
        'image_id': image['Id'], 'image_size_bytes': image['Size'],
        'http_health': 200, 'docker_health': 'healthy', 'native_host_guard': 'passed',
        'isolation_and_file_hashes': 'passed', 'startup_logs_checked': True,
        'resource_snapshot': json.loads(docker('stats', '--no-stream', '--format', '{{json .}}', args.container)),
        'note': 'Local Docker evidence only. No registry push or cloud deployment.'})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
