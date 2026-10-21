#!/usr/bin/env python3
"""Offline, read-only input checks. No network, deployment, or credential storage."""
import argparse
import json
import math
import re
import sys
from urllib.parse import urlsplit


def validate(data):
    errors = []

    def get(key):
        value = data
        for part in key.split('.'):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def text(key):
        value = get(key)
        if not isinstance(value, str) or not value.strip() or value in {'auto', 'latest'}:
            errors.append(key + ': requires an explicit discovered/confirmed value')
        return value

    def choice(key, allowed):
        value = get(key)
        if not isinstance(value, str) or value not in allowed:
            errors.append(key + ': select one of ' + ', '.join(allowed))
            return None
        return value

    def integer(key, low, high):
        value = get(key)
        if type(value) is not int or not low <= value <= high:
            errors.append(key + ': invalid integer range')

    def https(key):
        value = text(key)
        if not isinstance(value, str):
            return
        try:
            url = urlsplit(value)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError()
            _ = url.port
        except ValueError:
            errors.append(key + ': requires HTTPS without embedded credentials')

    if not isinstance(data, dict):
        return ['root: JSON object required']
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        errors.append('schema_version: unsupported schema')
    operation = choice('operation', ('inspect', 'install', 'upgrade', 'provision', 'troubleshoot'))
    text('target.host')
    access = choice('target.access_method', ('ssh', 'console', 'browser', 'api', 'manual'))
    if access == 'ssh':
        text('target.ssh_user')
        integer('target.ssh_port', 1, 65535)
        text('target.verified_host_fingerprint_ref')

    if operation in {'install', 'upgrade', 'provision'}:
        if get('scope.authorized') is not True:
            errors.append('scope.authorized: explicit authorization required')
        if get('scope.other_targets_unchanged') is not True:
            errors.append('scope.other_targets_unchanged: narrow change scope required')
    if operation in {'install', 'upgrade'}:
        method = choice('target.deployment_method', ('native', 'docker'))
        for key in ('target.os_id', 'target.architecture', 'target.data_path', 'release.panel_target'):
            text(key)
        if method == 'native':
            commit = text('release.upstream_commit_or_digest')
            if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', commit):
                errors.append('release.upstream_commit_or_digest: verified full commit required')
            https('release.download_url')
            text('release.checksum_evidence_ref')
        if method == 'docker':
            image = text('release.image_ref')
            if not isinstance(image, str) or not re.fullmatch(r'[^\s@]+@sha256:[0-9a-fA-F]{64}', image):
                errors.append('release.image_ref: image pinned by sha256 digest required')
    if operation == 'upgrade':
        text('release.panel_installed')
        text('target.service_or_container')
        text('scope.maintenance_window_ref')
        if get('scope.backup_skip_approved') is not True:
            text('scope.backup_evidence_ref')

    if operation == 'provision':
        for key in ('release.panel_installed', 'release.server_core', 'release.client_core',
                    'node.label', 'node.protocol', 'node.transport', 'node.security',
                    'node.client_label', 'node.expiry', 'node.reset_policy'):
            text(key)
        inbound_action = choice('node.inbound_action', ('create', 'reuse'))
        if inbound_action == 'reuse':
            integer('node.inbound_id', 1, 2**63 - 1)
        choice('node.client_strategy', ('independent', 'shared'))
        integer('node.port', 1, 65535)
        quota = get('node.quota_gb')
        try:
            quota_valid = type(quota) in (int, float) and math.isfinite(quota) and quota >= 0
        except (OverflowError, TypeError):
            quota_valid = False
        if not quota_valid:
            errors.append('node.quota_gb: explicit non-negative numeric quota required')
        if get('node.security') == 'reality':
            text('node.server_name')
            text('node.reality_target')
        if get('node.minimum_client_version') is not None:
            text('node.minimum_client_version')
            if get('scope.legacy_compatibility_approved') is not True:
                errors.append('node.minimum_client_version: explicit compatibility-override approval required')

    if operation in {'provision', 'troubleshoot'}:
        https('probe.url')
        statuses = get('probe.expected_statuses')
        if not isinstance(statuses, list) or not statuses or any(
                type(v) is not int or not 100 <= v <= 599 for v in statuses):
            errors.append('probe.expected_statuses: explicit HTTP status set required')
        proxy = text('probe.proxy_url')
        if isinstance(proxy, str):
            try:
                url = urlsplit(proxy)
                if (url.scheme not in {'socks5', 'socks5h', 'http', 'https'} or
                        url.hostname not in {'127.0.0.1', '::1', 'localhost'} or
                        url.port is None or not 1 <= url.port <= 65535 or url.username or url.password):
                    raise ValueError()
            except ValueError:
                errors.append('probe.proxy_url: isolated loopback proxy without embedded credentials required')
        integer('probe.timeout_seconds', 1, 600)

    admin = get('target.admin_access')
    if admin is not None and (not isinstance(admin, str) or admin not in {'https', 'ssh-tunnel'}):
        errors.append('target.admin_access: select https or ssh-tunnel')
    if admin == 'https' and get('target.panel_url') is not None:
        https('target.panel_url')

    forbidden_keys = {'password', 'privatekey', 'apikey', 'token', 'accesstoken', 'authorization',
                      'cookie', 'cookies', 'uuid', 'subscriptionurl', 'dsn'}
    public_sections = {'target', 'release', 'node', 'probe', 'scope', 'secret_refs'}

    def secrets(value, prefix=''):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = key.lower().replace('_', '').replace('-', '') if isinstance(key, str) else ''
                # Even JSON keys can contain secrets or newlines. Never echo unknown keys.
                segment = key if key in public_sections else (
                    normalized if normalized in forbidden_keys else '[field]')
                name = prefix + '.' + segment if prefix else segment
                if normalized in forbidden_keys:
                    errors.append(name + ': store a private reference, not a secret field')
                secrets(child, name)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                secrets(child, prefix + '[' + str(index) + ']')
        elif isinstance(value, str):
            if ('PRIVATE KEY-----' in value or
                    re.search(r'\b(?:vless|vmess|trojan|ss)://', value, re.I) or
                    re.search(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', value, re.I)):
                errors.append(prefix + ': suspected secret payload; use a private reference')
    secrets(data)
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', help='local JSON input; only field paths appear in errors')
    args = parser.parse_args(argv)
    try:
        with open(args.manifest, encoding='utf-8-sig') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        print('INPUT_READ_ERROR: cannot read a valid JSON manifest', file=sys.stderr)
        return 1
    errors = validate(data)
    if errors:
        for error in errors:
            print('INPUT_NOT_READY: ' + error)
        return 2
    print('INPUT_VALID: local checks only; no remote operation or verification performed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
