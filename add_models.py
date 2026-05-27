#!/usr/bin/env python3
"""Fetch models from an OpenAI-compatible endpoint and register them with an llmlite gateway via its web API.

Usage examples:
  OPENAI_API_KEY=sk... LLMGATEWAY_API_KEY=key... python add_models.py --openai-url https://api.openai.com --llmgateway-url http://localhost:8080 --dry-run

Environment variables:
  OPENAI_API_KEY       OpenAI-compatible API key (or use --openai-key)
  LLMGATEWAY_API_KEY   llmlite gateway API key (optional)

The script is idempotent: it will skip models already present on the gateway.
"""

import argparse
import os
import sys
import requests
from typing import List, Dict


def _load_env_file(path: str = None) -> None:
    """Load KEY=VALUE pairs from an env file into os.environ (existing vars take priority)."""
    candidates = [path] if path else [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'env'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.split('#')[0].strip()
                    if key and key not in os.environ:
                        os.environ[key] = value
            break


_load_env_file()


def fetch_openai_models(openai_url: str, api_key: str, timeout: int = 10) -> List[str]:
    url = openai_url.rstrip('/') + '/v1/models'
    headers = {'Authorization': f'Bearer {api_key}'}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # Expecting OpenAI-like response: {"data": [{"id": "gpt-4"}, ...]}
    models = []
    for item in data.get('data', []):
        if isinstance(item, dict) and 'id' in item:
            models.append(item['id'])
    return models


def fetch_github_models(github_url: str, token: str, timeout: int = 10) -> List[str]:
    url = github_url.rstrip('/') + '/catalog/models'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2026-03-10',
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    models: List[str] = []
    # Response is a top-level list of model objects with an 'id' field
    if isinstance(data, dict):
        items = data.get('models') or data.get('data') or data.get('items') or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    for item in items:
        if isinstance(item, dict):
            # Prefer 'id' (e.g. "openai/gpt-4.1"), fall back to other keys
            if 'id' in item:
                models.append(item['id'])
            elif 'name' in item:
                models.append(item['name'])
            elif 'model' in item and isinstance(item['model'], str):
                models.append(item['model'])
            elif 'model_id' in item:
                models.append(item['model_id'])
        elif isinstance(item, str):
            models.append(item)

    return models


def get_llmlite_models(gateway_url: str, api_key: str = None, timeout: int = 10) -> List[str]:
    url = gateway_url.rstrip('/') + '/v1/models'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # Expecting a list or {"data": [...]}
    models = []
    if isinstance(data, dict) and 'data' in data:
        items = data['data']
    else:
        items = data
    for item in items:
        if isinstance(item, dict) and 'id' in item:
            models.append(item['id'])
        elif isinstance(item, str):
            models.append(item)
    return models


def get_llmlite_model_infos(gateway_url: str, api_key: str = None, timeout: int = 10) -> List[Dict]:
    """Return a list of model info dicts from the gateway, each containing 'model_name' and 'model_info.id'."""
    url = gateway_url.rstrip('/') + '/model/info'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    items = data.get('data', []) if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def delete_llmlite_model(gateway_url: str, model_db_id: str, api_key: str = None, timeout: int = 10) -> Dict:
    """Delete a model from the gateway using its internal model_info.id."""
    url = gateway_url.rstrip('/') + '/model/delete'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    resp = requests.post(url, json={'id': model_db_id}, headers=headers, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


def list_llmlite_credentials(gateway_url: str, api_key: str = None, timeout: int = 10) -> List[Dict]:
    """Return all credentials configured on the gateway."""
    url = gateway_url.rstrip('/') + '/credentials'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get('credentials', []) if isinstance(data, dict) else []


def upsert_llmlite_credential(gateway_url: str, credential_name: str, provider: str, values: Dict, api_key: str = None, timeout: int = 10) -> Dict:
    """Create or update a named credential on the gateway via POST /credentials.

    credential_name: name to identify this credential (e.g. "ollama-local")
    provider:        LiteLLM provider string (e.g. "OPENAI_LIKE", "openai", "anthropic")
    values:          dict of credential values (e.g. {"api_key": "sk-...", "api_base": "http://..."})
    """
    url = gateway_url.rstrip('/') + '/credentials'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'credential_name': credential_name,
        'credential_values': values,
        'credential_info': {'custom_llm_provider': provider},
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


def add_llmlite_model(gateway_url: str, model_id: str, openai_url: str, backend_model: str = None, api_key: str = None, model_key: str = None, credential_name: str = None, access_group: str = None, timeout: int = 10) -> Dict:
    """Register a model with LiteLLM proxy via POST /model/new.

    model_id:       public name used on the gateway (may include a prefix).
    backend_model:  exact model name as returned by the provider backend.
    credential_name: optional name of an existing LLM Credential on the gateway to associate with this model.
    """
    url = gateway_url.rstrip('/') + '/model/new'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    # Use the exact provider model name in litellm_params; LiteLLM routes via "openai/" provider prefix.
    provider_model = backend_model or model_id

    payload: Dict = {
        'model_name': model_id,
        'litellm_params': {
            'model': provider_model,
            'custom_llm_provider': 'openai',
            'api_base': openai_url.rstrip('/'),
            'api_key': model_key or 'none',
        },
        'model_info': {},
    }
    if access_group:
        payload['model_info']['access_groups'] = [access_group]
    if credential_name:
        payload['model_info']['credential_name'] = credential_name

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


def parse_args():
    p = argparse.ArgumentParser(description='Sync models from an OpenAI-compatible API to an llmlite gateway')
    p.add_argument('--openai-url', default=os.environ.get('OPENAI_API_URL', 'https://api.openai.com'), help='OpenAI-compatible base URL')
    p.add_argument('--openai-key', default=os.environ.get('OPENAI_API_KEY'), help='OpenAI API key')
    p.add_argument('--github-url', default=os.environ.get('GITHUB_API_URL', 'https://models.github.ai'), help='GitHub Models base URL')
    p.add_argument('--github-token', default=os.environ.get('GITHUB_API_TOKEN'), help='GitHub API token for Copilot models catalog')
    p.add_argument('--include-github', action='store_true', help='Include GitHub Copilot models when discovering models')
    p.add_argument('--llmgateway-url', default=os.environ.get('LLMGATEWAY_URL', 'http://localhost:4000'), help='llmlite gateway base URL')
    p.add_argument('--llmgateway-key', default=os.environ.get('LLMGATEWAY_API_KEY'), help='llmlite gateway API key (if required)')
    p.add_argument('--provider-cred', action='append', help='Provider credential mapping: provider:key=value (can repeat)')
    p.add_argument('--provider-creds-file', help='File with provider:key=value per line')
    p.add_argument('--set-credential', action='append', metavar='NAME:PROVIDER:key=value,...',
                   help='Create/update a named gateway credential. Format: name:provider:key=value,key2=value2 (can repeat)')
    p.add_argument('--list-credentials', action='store_true', help='List credentials configured on the gateway and exit')
    p.add_argument('--dry-run', action='store_true', help='Show actions without performing POSTs')
    p.add_argument('--delete-all', action='store_true', help='Delete all models currently configured in the gateway and exit')
    p.add_argument('--timeout', type=int, default=10, help='HTTP timeout seconds')
    p.add_argument('--public-prefix', default=os.environ.get('MODEL_PUBLIC_PREFIX', ''), help='Prefix to prepend to public model id')
    p.add_argument('--access-group', default=os.environ.get('LLM_ACCESS_GROUP'), help='Access group name to assign models to (creates group if missing)')
    return p.parse_args()


def main():
    args = parse_args()

    if args.list_credentials:
        try:
            creds = list_llmlite_credentials(args.llmgateway_url, api_key=args.llmgateway_key, timeout=args.timeout)
        except Exception as e:
            print(f'Failed to list credentials: {e}', file=sys.stderr)
            sys.exit(1)
        if not creds:
            print('No credentials configured on gateway.')
        else:
            print(f'{len(creds)} credential(s) on {args.llmgateway_url}:')
            for c in creds:
                name = c.get('credential_name', '?')
                provider = c.get('credential_info', {}).get('custom_llm_provider', '?')
                keys = ', '.join(c.get('credential_values', {}).keys())
                print(f'  {name}  [{provider}]  keys: {keys}')
        return

    if args.set_credential:
        errors = 0
        for entry in args.set_credential:
            # Format: name:provider:key=value,key2=value2
            parts = entry.split(':', 2)
            if len(parts) != 3:
                print(f'Invalid --set-credential format (expected name:provider:key=value,...): {entry!r}', file=sys.stderr)
                errors += 1
                continue
            cred_name, provider, kv_str = parts
            values: Dict = {}
            for kv in kv_str.split(','):
                kv = kv.strip()
                if '=' not in kv:
                    continue
                k, v = kv.split('=', 1)
                values[k.strip()] = v.strip()
            if not values:
                print(f'No key=value pairs found in --set-credential entry: {entry!r}', file=sys.stderr)
                errors += 1
                continue
            print(f'Setting credential {cred_name!r} [{provider}] keys={list(values.keys())}... ', end='', flush=True)
            if args.dry_run:
                print('(dry run)')
                continue
            try:
                upsert_llmlite_credential(args.llmgateway_url, cred_name, provider, values, api_key=args.llmgateway_key, timeout=args.timeout)
                print('OK')
            except Exception as e:
                print(f'FAILED: {e}', file=sys.stderr)
                errors += 1
        if errors:
            sys.exit(1)
        # If only --set-credential was given (no model-sync needed), exit
        if not args.openai_key and not args.include_github:
            return

    if args.delete_all:
        print(f'Fetching all models from gateway {args.llmgateway_url}...')
        try:
            infos = get_llmlite_model_infos(args.llmgateway_url, api_key=args.llmgateway_key, timeout=args.timeout)
        except Exception as e:
            print(f'Failed to fetch models from gateway: {e}', file=sys.stderr)
            sys.exit(1)
        if not infos:
            print('No models found on gateway.')
            return
        print(f'{len(infos)} model(s) to delete:')
        for info in infos:
            name = info.get('model_name', '?')
            db_id = info.get('model_info', {}).get('id', '')
            print(f'  - {name} (id={db_id})')
        if args.dry_run:
            print('Dry run enabled; no models will be deleted.')
            return
        errors = 0
        for info in infos:
            name = info.get('model_name', '?')
            db_id = info.get('model_info', {}).get('id', '')
            if not db_id:
                print(f'  Skipping {name}: no internal id found', file=sys.stderr)
                errors += 1
                continue
            try:
                print(f'  Deleting {name}... ', end='', flush=True)
                delete_llmlite_model(args.llmgateway_url, db_id, api_key=args.llmgateway_key, timeout=args.timeout)
                print('OK')
            except Exception as e:
                print(f'FAILED: {e}', file=sys.stderr)
                errors += 1
        if errors:
            sys.exit(1)
        return

    if not args.openai_key:
        print('Error: OpenAI API key required (env OPENAI_API_KEY or --openai-key)', file=sys.stderr)
        sys.exit(2)

    print(f'Fetching models from {args.openai_url}...')
    try:
        openai_models = fetch_openai_models(args.openai_url, args.openai_key, timeout=args.timeout)
    except Exception as e:
        print(f'Failed to fetch OpenAI models: {e}', file=sys.stderr)
        sys.exit(1)

    print(f'Found {len(openai_models)} models on OpenAI-compatible endpoint.')

    # Collect remote models with source tag
    remote_models: List[tuple] = []  # (raw_name, source)
    for m in openai_models:
        remote_models.append((m, 'openai'))
    if args.include_github:
        if not args.github_token:
            print('Error: GitHub token required to include GitHub models (env GITHUB_API_TOKEN or --github-token)', file=sys.stderr)
            sys.exit(2)
        print(f'Fetching models from GitHub Copilot catalog at {args.github_url}...')
        try:
            gh = fetch_github_models(args.github_url, args.github_token, timeout=args.timeout)
            print(f'Found {len(gh)} models on GitHub.')
            for m in gh:
                remote_models.append((m, 'github'))
        except Exception as e:
            print(f'Failed to fetch GitHub models: {e}', file=sys.stderr)
            sys.exit(1)

    try:
        gateway_models = get_llmlite_models(args.llmgateway_url, api_key=args.llmgateway_key, timeout=args.timeout)
    except Exception as e:
        print(f'Failed to fetch models from llmlite gateway: {e}', file=sys.stderr)
        sys.exit(1)

    # Parse provider credentials from CLI arguments or a file. Format: provider:key=value
    def parse_provider_creds(arg_list, file_path):
        creds = {}
        items = []
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln or ln.startswith('#'):
                            continue
                        items.append(ln)
            except Exception:
                pass
        if arg_list:
            items.extend(arg_list)
        for it in items:
            if ':' in it and '=' in it:
                provider, rest = it.split(':', 1)
                key, val = rest.split('=', 1)
                provider = provider.strip()
                key = key.strip()
                val = val.strip()
                creds.setdefault(provider, {})[key] = val
        return creds

    provider_creds = parse_provider_creds(args.provider_cred, args.provider_creds_file)

    def normalize(raw: str) -> str:
        # Remove anything before the last '/'
        if not raw:
            return raw
        short = raw.rsplit('/', 1)[-1].strip()
        # Replace any remaining slashes and collapse whitespace
        short = short.replace('/', '-')
        short = "".join(short.split())
        return short

    raw_prefix = (args.public_prefix or '')
    if raw_prefix:
        prefix = raw_prefix.rstrip('/') + '/'
    else:
        prefix = ''
    missing: List[tuple] = []  # (raw, source, short, public_id)
    seen_public = set()
    for raw, source in remote_models:
        short = normalize(raw)
        if source == 'github':
            effective_prefix = 'github_copilot/'
        else:
            effective_prefix = prefix
        public_id = f"{effective_prefix}{short}"
        if public_id in seen_public:
            continue
        seen_public.add(public_id)
        if public_id not in gateway_models:
            missing.append((raw, source, short, public_id))

    print(f'{len(missing)} models to add to llmlite gateway ({args.llmgateway_url}).')
    for _raw, _src, _short, public_id in missing:
        print(f'- {public_id}')
    if args.dry_run:
        print('Dry run enabled; no models will be posted.')
        return

    for raw, source, short, public_id in missing:
        try:
            print(f'Adding model {public_id}... ', end='', flush=True)
            endpoint = args.openai_url if source == 'openai' else args.github_url
            source_creds = provider_creds.get(source, {}) if provider_creds else {}
            source_key = source_creds.get('api_key') or (args.openai_key if source == 'openai' else args.github_token)
            credential_name = source_creds.get('credential_name') or source_creds.get('credential') or source_creds.get('credential_id')
            res = add_llmlite_model(args.llmgateway_url, public_id, endpoint, backend_model=raw, api_key=args.llmgateway_key, model_key=source_key, credential_name=credential_name, access_group=args.access_group, timeout=args.timeout)
            # Verify the model actually appears in the gateway list
            try:
                gateway_now = get_llmlite_models(args.llmgateway_url, api_key=args.llmgateway_key, timeout=args.timeout)
                if public_id in gateway_now:
                    print('OK')
                else:
                    print('WARNING (not present):', res)
            except Exception as e:
                # If verification fails, report the add response but don't crash
                print('Added (verification failed):', res)
        except Exception as e:
            print(f'FAILED: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
