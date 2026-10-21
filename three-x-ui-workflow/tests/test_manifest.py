"""Offline behavioral tests. All target values here are documentation fixtures."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('validator', ROOT / 'scripts' / 'validate_manifest.py')
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def fixture(operation='inspect'):
    data = json.loads((ROOT / 'templates' / 'inputs.example.json').read_text(encoding='utf-8'))
    data['operation'] = operation
    data['target'].update(host='server.example.invalid', access_method='manual',
                          os_id='discovered-os', architecture='discovered-arch',
                          deployment_method='native', data_path='/chosen-test-path',
                          service_or_container='discovered-service')
    data['release'].update(panel_installed='v1.2.3', panel_target='v1.2.4',
                           server_core='test-core', client_core='test-client-core',
                           upstream_commit_or_digest='a' * 40,
                           download_url='https://example.invalid/release',
                           checksum_evidence_ref='private-checksum-record')
    data['scope'].update(authorized=True, backup_evidence_ref='private-backup-record',
                         maintenance_window_ref='approved-test-window')
    data['node'].update(inbound_action='reuse', inbound_id=123, label='test-new-user',
                        protocol='vless', transport='tcp', security='reality', port=23456,
                        client_strategy='independent', client_label='test-client',
                        quota_gb=5, expiry='none', reset_policy='confirmed-test-policy',
                        server_name='example.invalid', reality_target='example.invalid:443')
    data['probe'].update(url='https://example.invalid/probe', expected_statuses=[200, 204],
                         proxy_url='socks5h://127.0.0.1:23457', timeout_seconds=10)
    return data


class ManifestTests(unittest.TestCase):
    def assert_invalid(self, data, field):
        self.assertTrue(any(field in e for e in validator.validate(data)))

    def test_unfilled_template_is_not_ready(self):
        data = json.loads((ROOT / 'templates' / 'inputs.example.json').read_text(encoding='utf-8'))
        self.assertTrue(validator.validate(data))

    def test_complete_operations_are_locally_valid(self):
        for operation in ('inspect', 'install', 'upgrade', 'provision', 'troubleshoot'):
            with self.subTest(operation=operation):
                self.assertEqual(validator.validate(fixture(operation)), [])

    def test_manual_inspection_needs_no_ssh_credentials(self):
        self.assertEqual(validator.validate(fixture()), [])

    def test_ssh_requires_fingerprint_and_explicit_port(self):
        data = fixture(); data['target']['access_method'] = 'ssh'
        self.assert_invalid(data, 'verified_host_fingerprint_ref')
        self.assert_invalid(data, 'ssh_port')
        data['target'].update(ssh_user='test-operator', ssh_port=23458,
                              verified_host_fingerprint_ref='private-trusted-fingerprint')
        self.assertEqual(validator.validate(data), [])

    def test_mutation_needs_authorization(self):
        data = fixture('provision'); data['scope']['authorized'] = False
        self.assert_invalid(data, 'scope.authorized')

    def test_upgrade_needs_backup_or_explicit_exception(self):
        data = fixture('upgrade'); data['scope']['backup_evidence_ref'] = None
        self.assert_invalid(data, 'scope.backup_evidence_ref')
        data['scope']['backup_skip_approved'] = True
        self.assertEqual(validator.validate(data), [])

    def test_shared_identity_is_explicit_not_default(self):
        data = fixture('provision'); data['node']['client_strategy'] = None
        self.assert_invalid(data, 'client_strategy')
        data['node']['client_strategy'] = 'shared'
        self.assertEqual(validator.validate(data), [])

    def test_invalid_ports_include_bool(self):
        for value in (0, 65536, '23456', True, None):
            data = fixture('provision'); data['node']['port'] = value
            self.assert_invalid(data, 'node.port')

    def test_quota_requires_explicit_finite_number(self):
        for value in (None, -1, True, 'unlimited', float('inf'), float('nan')):
            data = fixture('provision'); data['node']['quota_gb'] = value
            self.assert_invalid(data, 'quota_gb')
        data['node']['quota_gb'] = 0
        self.assertEqual(validator.validate(data), [])

    def test_version_override_requires_separate_approval(self):
        data = fixture('provision'); data['node']['minimum_client_version'] = 'test-exception'
        self.assert_invalid(data, 'minimum_client_version')
        data['scope']['legacy_compatibility_approved'] = True
        self.assertEqual(validator.validate(data), [])

    def test_native_installer_needs_immutable_commit_and_evidence(self):
        data = fixture('install'); data['release']['upstream_commit_or_digest'] = 'master'
        self.assert_invalid(data, 'upstream_commit_or_digest')

    def test_docker_requires_image_digest(self):
        data = fixture('install'); data['target']['deployment_method'] = 'docker'
        data['release']['image_ref'] = 'example.invalid/test:latest'
        self.assert_invalid(data, 'image_ref')
        data['release']['image_ref'] = 'example.invalid/test@sha256:' + 'b' * 64
        self.assertEqual(validator.validate(data), [])

    def test_proxy_must_be_isolated_without_credentials(self):
        for value in ('socks5h://example.invalid:23457', 'socks5h://127.0.0.1',
                      'socks5h://user:secret@127.0.0.1:23457', 'ftp://127.0.0.1:23457'):
            data = fixture('provision'); data['probe']['proxy_url'] = value
            self.assert_invalid(data, 'probe.proxy_url')

    def test_https_probe_and_explicit_expected_status_required(self):
        data = fixture('provision'); data['probe'].update(url='http://example.invalid', expected_statuses=[])
        self.assert_invalid(data, 'probe.url')
        self.assert_invalid(data, 'expected_statuses')

    def test_secrets_are_rejected_without_echoing_values(self):
        data = fixture(); data['extra'] = {'password': 'DO_NOT_ECHO_THIS'}
        errors = validator.validate(data)
        self.assertTrue(any('[field].password' in e for e in errors))
        self.assertNotIn('DO_NOT_ECHO_THIS', '\n'.join(errors))

    def test_private_connection_payload_rejected_in_reference(self):
        data = fixture(); data['secret_refs']['node_credential_ref'] = 'vless://synthetic-test'
        self.assert_invalid(data, 'suspected secret payload')

    def test_schema_and_root_types(self):
        self.assertTrue(validator.validate([]))
        data = fixture(); data['schema_version'] = True
        self.assert_invalid(data, 'schema_version')

    def test_malformed_section_is_reported_not_crashed(self):
        data = fixture('provision'); data['node'] = []
        self.assertTrue(validator.validate(data))

    def test_malformed_discriminators_are_reported_not_crashed(self):
        for value in ([], {}, True, 1):
            data = fixture(); data['operation'] = value
            self.assertTrue(validator.validate(data))
            data = fixture(); data['target']['admin_access'] = value
            self.assertTrue(validator.validate(data))

    def test_zero_proxy_port_is_not_a_listener(self):
        data = fixture('provision'); data['probe']['proxy_url'] = 'socks5h://127.0.0.1:0'
        self.assert_invalid(data, 'probe.proxy_url')

    def test_large_quota_is_an_input_error_not_overflow(self):
        data = fixture('provision'); data['node']['quota_gb'] = 10**1000
        self.assert_invalid(data, 'quota_gb')

    def test_unknown_json_keys_cannot_leak_or_inject_logs(self):
        data = fixture(); data['DEMO_SECRET_AS_KEY\nFORGED_LOG'] = 'vless://synthetic-test'
        errors = '\n'.join(validator.validate(data))
        self.assertNotIn('DEMO_SECRET_AS_KEY', errors)
        self.assertNotIn('FORGED_LOG', errors)
        self.assertIn('[field]', errors)

    def test_cli_contract_and_input_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            command = [sys.executable, str(ROOT / 'scripts' / 'validate_manifest.py'), str(path)]
            path.write_text(json.dumps(fixture()), encoding='utf-8')
            before = path.read_bytes()
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn('INPUT_VALID', result.stdout)
            self.assertEqual(path.read_bytes(), before)
            path.write_text('{}', encoding='utf-8')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            path.write_text('not JSON', encoding='utf-8')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)


if __name__ == '__main__':
    unittest.main()
