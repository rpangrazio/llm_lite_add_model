#!/usr/bin/env python3
"""Fetch models from an OpenAI-compatible endpoint and register them with an llmlite gateway via its web API.

Usage examples:
  OPENAI_API_KEY=sk... LITELLM_MASTER_KEY=key... python add_models.py --openai-url https://api.openai.com --llmgateway-url http://localhost:8080 --dry-run

Environment variables:
  OPENAI_API_KEY       OpenAI-compatible API key (or use --openai-key)
  LITELLM_MASTER_KEY   llmlite gateway API key (optional)

The script is idempotent: it will skip models already present on the gateway.
"""

import argparse
import os
import sys
import requests
from typing import Dict, List, Optional, Set


def _load_env_file(path: str = None) -> None:
    """Load KEY=VALUE pairs from an env file into os.environ (existing vars take priority).

    Looks for *path* first; if not given, checks for ``env`` and ``.env`` files
    in the same directory as this script.  Only the first matching file is read.

    Args:
        path: Explicit path to an env file.  When ``None`` the default
            candidates are tried in order.
    """
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
    """Fetch the list of model IDs from an OpenAI-compatible ``/v1/models`` endpoint.

    Args:
        openai_url: Base URL of the OpenAI-compatible API.
        api_key: API key sent as an Authorization header.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of model ID strings.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
    """
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
    """Fetch the list of model IDs from the GitHub Models catalog endpoint.

    The catalog may return either a top-level list or a dict whose values
    contain model objects.  Each model object is inspected for ``id``,
    ``name``, ``model``, or ``model_id`` fields, in that order of preference.

    Args:
        github_url: Base URL of the GitHub Models API
            (e.g. ``https://models.github.ai``).
        token: GitHub personal access token for authentication.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of model ID strings.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
    """
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


def get_llmlite_models(gateway_url: str, api_key: Optional[str] = None, timeout: int = 10) -> List[str]:
    """Fetch the list of public model IDs currently registered on the llmlite gateway.

    Args:
        gateway_url: Base URL of the llmlite gateway.
        api_key: Optional API key sent as an Authorization header.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of model ID strings reported by the gateway.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
    """
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


def get_llmlite_model_infos(gateway_url: str, api_key: Optional[str] = None, timeout: int = 10) -> List[Dict]:
    """Return a list of model info dicts from the gateway, each containing 'model_name' and 'model_info.id'.

    Args:
        gateway_url: Base URL of the llmlite gateway.
        api_key: Optional API key sent as an Authorization header.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of model info dicts as returned by ``GET /model/info``.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
    """
    url = gateway_url.rstrip('/') + '/model/info'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    items = data.get('data', []) if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def delete_llmlite_model(gateway_url: str, model_db_id: str, api_key: Optional[str] = None, timeout: int = 10) -> Dict:
    """Delete a model from the gateway using its internal model_info.id.

    Args:
        gateway_url: Base URL of the llmlite gateway.
        model_db_id: Internal database ID of the model (from ``model_info.id``).
        api_key: Optional API key sent as an Authorization header.
        timeout: HTTP request timeout in seconds.

    Returns:
        Response body as a dict, or an empty dict when the body is not JSON.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
    """
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


def list_llmlite_credentials(gateway_url: str, api_key: Optional[str] = None, timeout: int = 10) -> List[Dict]:
    """Return all credentials configured on the gateway.

    Args:
        gateway_url: Base URL of the llmlite gateway.
        api_key: Optional API key sent as an Authorization header.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of credential dicts as returned by ``GET /credentials``.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
    """
    url = gateway_url.rstrip('/') + '/credentials'
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get('credentials', []) if isinstance(data, dict) else []


def gateway_credential_names(credentials: List[Dict]) -> Set[str]:
    """Extract credential names from a gateway credential listing."""
    return {
        str(c.get('credential_name'))
        for c in credentials
        if c.get('credential_name')
    }


def upsert_llmlite_credential(
    gateway_url: str,
    credential_name: str,
    provider: str,
    values: Dict,
    api_key: Optional[str] = None,
    timeout: int = 10,
) -> Dict:
    """Create or update a named credential on the gateway via ``POST /credentials``.

    Args:
        gateway_url: Base URL of the llmlite gateway.
        credential_name: Name to identify this credential (e.g. ``"ollama-local"``).
        provider: LiteLLM provider string (e.g. ``"OPENAI_LIKE"``, ``"openai"``,
            ``"anthropic"``).
        values: Dict of credential values
            (e.g. ``{"api_key": "sk-...", "api_base": "http://..."}``).
        api_key: Optional API key sent as an Authorization header.
        timeout: HTTP request timeout in seconds.

    Returns:
        Response body as a dict, or an empty dict when the body is not JSON.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
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


def add_llmlite_model(
    gateway_url: str,
    model_id: str,
    openai_url: str,
    backend_model: Optional[str] = None,
    api_key: Optional[str] = None,
    model_key: Optional[str] = None,
    credential_name: Optional[str] = None,
    access_group: Optional[str] = None,
    timeout: int = 10,
) -> Dict:
    """Register a model with the LiteLLM proxy via ``POST /model/new``.

    Args:
        gateway_url: Base URL of the llmlite gateway.
        model_id: Public name used on the gateway (may include a prefix).
        openai_url: Base URL of the upstream provider endpoint.
        backend_model: Exact model name as returned by the provider backend.
            Defaults to *model_id* when not supplied.
        api_key: Optional API key sent as an Authorization header.
        model_key: API key forwarded to the upstream provider.
        credential_name: Optional name of an existing LLM Credential on the
            gateway to associate with this model.
        access_group: Optional access group name to assign the model to.
        timeout: HTTP request timeout in seconds.

    Returns:
        Response body as a dict, or an empty dict when the body is not JSON.

    Raises:
        requests.HTTPError: If the HTTP response status indicates an error.
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
        },
        'model_info': {},
    }
    if not credential_name:
        payload['litellm_params']['api_base'] = openai_url.rstrip('/')
        payload['litellm_params']['api_key'] = model_key or 'none'
    if access_group:
        payload['model_info']['access_groups'] = [access_group]
    if credential_name:
        payload['litellm_params']['litellm_credential_name'] = credential_name

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


def normalize(raw: str) -> str:
    """Derive a short, slug-like model name from a raw provider model ID.

    Strips any namespace segment before the last ``/``, replaces any
    remaining ``/`` characters with ``-``, and collapses internal whitespace.

    Args:
        raw: Raw model ID as returned by the provider (e.g. ``"org/model-name"``).

    Returns:
        Normalised short model name (e.g. ``"model-name"``).
    """
    if not raw:
        return raw
    short = raw.rsplit('/', 1)[-1].strip()
    # Replace any remaining slashes and collapse whitespace
    short = short.replace('/', '-')
    short = "".join(short.split())
    return short


def parse_provider_creds(
    arg_list: Optional[List[str]] = None,
    file_path: Optional[str] = None,
) -> Dict[str, Dict[str, str]]:
    """Parse provider credential mappings from CLI arguments and/or a file.

    Each entry must have the form ``provider:key=value``.  Entries from
    *file_path* are read first; entries in *arg_list* are appended and may
    override file entries.

    Args:
        arg_list: List of ``provider:key=value`` strings from the CLI
            (``--provider-cred``).
        file_path: Path to a text file with one ``provider:key=value`` entry
            per line (``#`` comment lines and blank lines are ignored).

    Returns:
        Nested dict mapping ``{provider: {key: value}}``.
    """
    creds: Dict[str, Dict[str, str]] = {}
    items: List[str] = []
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


def parse_args() -> argparse.Namespace:
    """Build and parse the command-line argument parser.

    Returns:
        Parsed argument namespace.
    """
    p = argparse.ArgumentParser(description='Sync models from an OpenAI-compatible API to an llmlite gateway')
    p.add_argument('--openai-url', default=os.environ.get('OPENAI_API_URL', 'https://api.openai.com'), help='OpenAI-compatible base URL')
    p.add_argument('--openai-key', default=os.environ.get('OPENAI_API_KEY'), help='OpenAI API key')
    p.add_argument('--github-url', default=os.environ.get('GITHUB_API_URL', 'https://models.github.ai'), help='GitHub Models base URL')
    p.add_argument('--github-token', default=os.environ.get('GITHUB_API_TOKEN'), help='GitHub API token for Copilot models catalog')
    p.add_argument('--include-github', action='store_true', help='Include GitHub Copilot models when discovering models')
    p.add_argument('--llmgateway-url', default=os.environ.get('LLMGATEWAY_URL', 'http://localhost:4000'), help='llmlite gateway base URL')
    p.add_argument('--llmgateway-key', default=os.environ.get('LITELLM_MASTER_KEY'), help='llmlite gateway API key (if required)')
    p.add_argument('--provider-cred', action='append', help='Provider credential mapping: provider:key=value (can repeat)')
    p.add_argument('--provider-creds-file', help='File with provider:key=value per line')
    p.add_argument('--gateway-credential', help='Gateway credential name to apply to all imported models')
    p.add_argument('--set-credential', action='append', metavar='NAME:PROVIDER:key=value,...',
                   help='Create/update a named gateway credential. Format: name:provider:key=value,key2=value2 (can repeat)')
    p.add_argument('--list-credentials', action='store_true', help='List credentials configured on the gateway and exit')
    p.add_argument('--dry-run', action='store_true', help='Show actions without performing POSTs')
    p.add_argument('--delete-all', action='store_true', help='Delete all models currently configured in the gateway and exit')
    p.add_argument('--timeout', type=int, default=10, help='HTTP timeout seconds')
    p.add_argument('--public-prefix', default=os.environ.get('MODEL_PUBLIC_PREFIX', ''), help='Prefix to prepend to public model id')
    p.add_argument('--access-group', default=os.environ.get('LLM_ACCESS_GROUP'), help='Access group name to assign models to (creates group if missing)')
    return p.parse_args()


def _run_list_credentials(args: argparse.Namespace) -> None:
    """Print all credentials configured on the gateway and exit.

    Args:
        args: Parsed command-line arguments.
    """
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


def _run_set_credentials(args: argparse.Namespace) -> bool:
    """Create or update the named credentials supplied via ``--set-credential``.

    Args:
        args: Parsed command-line arguments.

    Returns:
        ``True`` when the caller should exit after this step (i.e. no model
        sync was requested), ``False`` otherwise.
    """
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
    # If only --set-credential was given (no model-sync needed), signal the caller to exit
    return not args.openai_key and not args.include_github


def _run_delete_all(args: argparse.Namespace) -> None:
    """Delete every model currently registered on the gateway.

    Args:
        args: Parsed command-line arguments.
    """
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


def _run_sync_models(args: argparse.Namespace) -> None:
    """Fetch remote models and register any that are missing on the gateway.

    Discovers models from the configured OpenAI-compatible endpoint and,
    optionally, from the GitHub Models catalog.  Models already present on
    the gateway are silently skipped (idempotent).

    Args:
        args: Parsed command-line arguments.
    """
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

    try:
        gateway_credentials = list_llmlite_credentials(args.llmgateway_url, api_key=args.llmgateway_key, timeout=args.timeout)
    except Exception as e:
        print(f'Failed to fetch credentials from llmlite gateway: {e}', file=sys.stderr)
        sys.exit(1)
    credential_names = gateway_credential_names(gateway_credentials)

    provider_creds = parse_provider_creds(args.provider_cred, args.provider_creds_file)

    raw_prefix = (args.public_prefix or '')
    prefix = raw_prefix.rstrip('/') + '/' if raw_prefix else ''

    missing: List[tuple] = []  # (raw, source, short, public_id)
    seen_public: Set[str] = set()
    for raw, source in remote_models:
        short = normalize(raw)
        effective_prefix = 'github_copilot/' if source == 'github' else prefix
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

    errors = 0
    for raw, source, short, public_id in missing:
        try:
            print(f'Adding model {public_id}... ', end='', flush=True)
            endpoint = args.openai_url if source == 'openai' else args.github_url
            source_creds = provider_creds.get(source, {}) if provider_creds else {}
            source_key = source_creds.get('api_key') or (args.openai_key if source == 'openai' else args.github_token)
            credential_name = (
                args.gateway_credential
                or source_creds.get('credential_name')
                or source_creds.get('credential')
                or source_creds.get('credential_id')
            )
            if credential_name and credential_name not in credential_names:
                raise ValueError(
                    f"gateway credential {credential_name!r} was not found on {args.llmgateway_url}"
                )
            res = add_llmlite_model(
                args.llmgateway_url,
                public_id,
                endpoint,
                backend_model=raw,
                api_key=args.llmgateway_key,
                model_key=source_key,
                credential_name=credential_name,
                access_group=args.access_group,
                timeout=args.timeout,
            )
            # Verify the model actually appears in the gateway list
            try:
                gateway_now = get_llmlite_models(args.llmgateway_url, api_key=args.llmgateway_key, timeout=args.timeout)
                if public_id in gateway_now:
                    print('OK')
                else:
                    print('WARNING (not present):', res)
            except Exception as verify_exc:
                # Verification request failed; report the add response but don't crash
                print(f'Added (verification failed: {verify_exc}):', res)
        except Exception as e:
            print(f'FAILED: {e}', file=sys.stderr)
            errors += 1

    if errors:
        sys.exit(1)


def main() -> None:
    """Entry point: parse arguments and run the requested operation.

    Operations are evaluated in the following order:

    1. ``--list-credentials`` — print gateway credentials and exit.
    2. ``--set-credential``   — create or update named credentials on the gateway.
    3. ``--delete-all``       — delete every model from the gateway and exit.
    4. Default               — fetch remote models and register any that are missing.
    """
    args = parse_args()

    if args.list_credentials:
        _run_list_credentials(args)
        return

    if args.set_credential:
        should_exit = _run_set_credentials(args)
        if should_exit:
            return

    if args.delete_all:
        _run_delete_all(args)
        return

    _run_sync_models(args)


if __name__ == '__main__':
    main()
