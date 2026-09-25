#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate west blob metadata against the HAL artifact manifest."""
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import yaml

from project_files import checked_file, relative_path

FETCH_HINT = 'Run west blobs fetch hal_bestechnic from the workspace root'


def blob_metadata(root, manifest=None):
    root = Path(root).resolve()
    if manifest is None:
        manifest = json.loads(checked_file(root, 'manifest.json').read_text())
    module = yaml.safe_load(checked_file(root, 'zephyr/module.yml').read_text())
    if not isinstance(module, dict) or module.get('name') != 'hal_bestechnic':
        raise ValueError('Invalid HAL module name')
    entries = module.get('blobs')
    if not isinstance(entries, list) or not entries:
        raise ValueError('HAL module must declare its library blobs')
    expected = {name for name in manifest['artifacts'] if name.endswith('.a')}
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid HAL blob entry')
        path = entry.get('path')
        if not isinstance(path, str):
            raise ValueError('Invalid HAL blob path')
        relative_path(path)
        name = 'zephyr/blobs/' + path
        if name in result or name not in expected:
            raise ValueError(f'Duplicate or unexpected HAL blob: {name}')
        if (entry.get('type') != 'lib' or entry.get('version') != manifest['version']
                or not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', '')))
                or entry['sha256'] != manifest['artifacts'][name]):
            raise ValueError(f'HAL blob metadata differs from manifest.json: {name}')
        license_path = entry.get('license-path')
        if not isinstance(license_path, str):
            raise ValueError(f'Missing HAL blob license path: {name}')
        checked_file(root, license_path)
        urls = entry.get('url')
        urls = [urls] if isinstance(urls, str) else urls
        if not isinstance(urls, list) or not urls:
            raise ValueError(f'Missing HAL blob download URL: {name}')
        for url in urls:
            if not isinstance(url, str):
                raise ValueError(f'Invalid HAL blob download URL: {name}')
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.netloc
                    or parsed.username or parsed.password or parsed.fragment):
                raise ValueError(f'Invalid HAL blob download URL: {name}')
        if not isinstance(entry.get('description'), str) or not entry['description'].strip():
            raise ValueError(f'Missing HAL blob description: {name}')
        if 'size' in entry and (type(entry['size']) is not int or entry['size'] <= 0):
            raise ValueError(f'Invalid HAL blob size: {name}')
        result[name] = dict(entry)
    if set(result) != expected:
        raise ValueError('HAL blob list differs from manifest.json libraries')
    if (root / '.git').exists():
        tracked = subprocess.check_output(
            ['git', '-C', str(root), 'ls-files', '-z', '--', *sorted(result)])
        if tracked:
            raise ValueError('HAL library blobs must not be tracked by Git')
    return result
