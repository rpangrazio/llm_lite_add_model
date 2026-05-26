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
from urllib.parse import quote
from typing import List, Dict


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
    url = github_url.rstrip('/') + '/models/catalog'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2026-03-10',
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    models: List[str] = []
    # Try common response shapes: {'models': [...]}, {'data': [...]}, or a top-level list
    if isinstance(data, dict):
        items = data.get('models') or data.get('data') or data.get('items') or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    for item in items:
        if isinstance(item, dict):
            # common keys: 'id', 'name', 'model', 'model_id'
            if 'name' in item:
                models.append(item['name'])
            elif 'id' in item:
                models.append(item['id'])
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


def add_llmlite_model(gateway_url: str, model_id: str, openai_url: str, api_key: str = None, access_group: str = None, timeout: int = 10) -> Dict:
    url = gateway_url.rstrip('/') + '/v1/models'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'id': model_id,
        'source': 'openai-compatible',
        'endpoint': openai_url.rstrip('/'),
        'model_name': model_id,
    }
    attempts = []
    def _is_runtime_response(obj: object) -> bool:
        # Heuristic: responses coming from runtime endpoints (completions/chat) often
        # include keys like 'choices', 'usage', 'totalTokens' or 'promptTokensDetails'.
        if not isinstance(obj, dict):
            return False
        runtime_indicators = ('choices', 'usage', 'totalTokens', 'promptTokensDetails')
        return any(k in obj for k in runtime_indicators)

    # Try the common POST to /v1/models first
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            data = None
        if _is_runtime_response(data):
            attempts.append(('POST-runtime', url, resp.status_code, str(data)))
        else:
            return data
    except requests.RequestException as exc:
        resp = getattr(exc, 'response', None)
        status = resp.status_code if resp is not None else None
        text = resp.text if resp is not None else str(exc)
        attempts.append(('POST', url, status, text))

        # If gateway rejects POST (405) or other failures, try a sequence of fallbacks
        # Keep track of attempts to provide a useful error message later.
        # 1) PUT to /v1/models/{id}
        try:
            quoted = quote(model_id, safe='')
            url_put = gateway_url.rstrip('/') + f'/v1/models/{quoted}'
            resp2 = requests.put(url_put, json=payload, headers=headers, timeout=timeout)
            resp2.raise_for_status()
            try:
                data2 = resp2.json()
            except Exception:
                data2 = None
            if _is_runtime_response(data2):
                attempts.append(('PUT-runtime', url_put, resp2.status_code, str(data2)))
            else:
                return data2
        except requests.RequestException as exc2:
            r2 = getattr(exc2, 'response', None)
            s2 = r2.status_code if r2 is not None else None
            t2 = r2.text if r2 is not None else str(exc2)
            attempts.append(('PUT', url_put, s2, t2))

        # 2) POST to /v1/models/register
        try:
            url_reg = gateway_url.rstrip('/') + '/v1/models/register'
            resp3 = requests.post(url_reg, json=payload, headers=headers, timeout=timeout)
            resp3.raise_for_status()
            try:
                data3 = resp3.json()
            except Exception:
                data3 = None
            if _is_runtime_response(data3):
                attempts.append(('POST-register-runtime', url_reg, resp3.status_code, str(data3)))
            else:
                return data3
        except requests.RequestException as exc3:
            r3 = getattr(exc3, 'response', None)
            s3 = r3.status_code if r3 is not None else None
            t3 = r3.text if r3 is not None else str(exc3)
            attempts.append(('POST', url_reg, s3, t3))

        # 3) Some gateways expect payload without an explicit 'id' on POST
        try:
            payload_no_id = {k: v for k, v in payload.items() if k != 'id'}
            resp4 = requests.post(url, json=payload_no_id, headers=headers, timeout=timeout)
            resp4.raise_for_status()
            try:
                data4 = resp4.json()
            except Exception:
                data4 = None
            if _is_runtime_response(data4):
                attempts.append(('POST-no-id-runtime', url, resp4.status_code, str(data4)))
            else:
                return data4
        except requests.RequestException as exc4:
            r4 = getattr(exc4, 'response', None)
            s4 = r4.status_code if r4 is not None else None
            t4 = r4.text if r4 is not None else str(exc4)
            attempts.append(('POST-no-id', url, s4, t4))

        # 4) Try register endpoint with alternate key 'model' instead of 'model_name'
        try:
            payload_alt = payload.copy()
            payload_alt['model'] = payload_alt.pop('model_name')
            url_reg = gateway_url.rstrip('/') + '/v1/models/register'
            resp5 = requests.post(url_reg, json=payload_alt, headers=headers, timeout=timeout)
            resp5.raise_for_status()
            try:
                data5 = resp5.json()
            except Exception:
                data5 = None
            if _is_runtime_response(data5):
                attempts.append(('POST-register-alt-runtime', url_reg, resp5.status_code, str(data5)))
            else:
                return data5
        except requests.RequestException as exc5:
            r5 = getattr(exc5, 'response', None)
            s5 = r5.status_code if r5 is not None else None
            t5 = r5.text if r5 is not None else str(exc5)
            attempts.append(('POST-register-alt', url_reg, s5, t5))

        # 5) Discover POST-capable model endpoints from openapi.json and try them
        try:
            candidates = discover_model_post_paths(gateway_url, headers=headers, timeout=timeout)
            for path in candidates:
                try_url = gateway_url.rstrip('/') + path
                try:
                    resp_c = requests.post(try_url, json=payload, headers=headers, timeout=timeout)
                    resp_c.raise_for_status()
                    try:
                        data_c = resp_c.json()
                    except Exception:
                        data_c = None
                    if _is_runtime_response(data_c):
                        attempts.append((f'POST-discovered-runtime', try_url, resp_c.status_code, str(data_c)))
                    else:
                        return data_c
                except requests.RequestException as exc_c:
                    rc = getattr(exc_c, 'response', None)
                    sc = rc.status_code if rc is not None else None
                    tc = rc.text if rc is not None else str(exc_c)
                    attempts.append((f'POST-discovered', try_url, sc, tc))
                    # If gateway complains about missing access_group_name, try to ensure it exists and retry
                    if rc is not None and sc == 422:
                        try:
                            body = rc.json()
                        except Exception:
                            body = {}
                        detail = body.get('detail') if isinstance(body, dict) else None
                        if detail and any(isinstance(d, dict) and d.get('loc') and 'access_group_name' in d.get('loc') for d in detail if isinstance(d, dict)):
                            # Ensure access group exists, then retry the model POST with access_group_name
                            ag = access_group or 'public'
                            try:
                                ensure_access_group(gateway_url, ag, headers=headers, timeout=timeout)
                            except Exception:
                                pass
                            # After ensuring the group exists, try canonical model endpoints
                            payload_with_group = payload.copy()
                            payload_with_group['access_group_name'] = ag
                            base = gateway_url.rstrip('/')
                            model_endpoints = [base + '/v1/models', base + '/v1/models/register', try_url]
                            for model_ep in model_endpoints:
                                try:
                                    resp_retry = requests.post(model_ep, json=payload_with_group, headers=headers, timeout=timeout)
                                    resp_retry.raise_for_status()
                                    try:
                                        data_retry = resp_retry.json()
                                    except Exception:
                                        data_retry = None
                                    if _is_runtime_response(data_retry):
                                        attempts.append((f'POST-{model_ep}-runtime-after-ag', model_ep, resp_retry.status_code, str(data_retry)))
                                    else:
                                        return data_retry
                                except requests.RequestException as exc_retry:
                                    rr = getattr(exc_retry, 'response', None)
                                    sr = rr.status_code if rr is not None else None
                                    tr = rr.text if rr is not None else str(exc_retry)
                                    attempts.append((f'POST-{model_ep}-after-ag', model_ep, sr, tr))
                    # also try without id
                    try:
                        resp_c2 = requests.post(try_url, json={k: v for k, v in payload.items() if k != 'id'}, headers=headers, timeout=timeout)
                        resp_c2.raise_for_status()
                        try:
                            data_c2 = resp_c2.json()
                        except Exception:
                            data_c2 = None
                        if _is_runtime_response(data_c2):
                            attempts.append((f'POST-discovered-no-id-runtime', try_url, resp_c2.status_code, str(data_c2)))
                        else:
                            return data_c2
                    except requests.RequestException as exc_c2:
                        rc2 = getattr(exc_c2, 'response', None)
                        sc2 = rc2.status_code if rc2 is not None else None
                        tc2 = rc2.text if rc2 is not None else str(exc_c2)
                        attempts.append((f'POST-discovered-no-id', try_url, sc2, tc2))
        except Exception:
            pass

        # All attempts failed — compose a helpful error message listing attempts
        msgs = []
        for method, u, st, tx in attempts:
            msgs.append(f'{method} {u} -> status={st} resp={tx}')
        # Run a quick probe of gateway endpoints to aid debugging
        try:
            probe = probe_gateway(gateway_url, headers=headers, timeout=timeout)
        except Exception as _:
            probe = 'Gateway probe failed'

        raise RuntimeError(f'Failed to register model {model_id}; attempts:\n' + "\n".join(msgs) + "\n\nGateway probe:\n" + probe)


def probe_gateway(gateway_url: str, headers: Dict = None, timeout: int = 5) -> str:
    """Probe common gateway endpoints with OPTIONS and GET to collect diagnostics."""
    if headers is None:
        headers = {}
    endpoints = [
        '/',
        '/v1',
        '/v1/models',
        '/v1/models/register',
        '/openapi.json',
        '/swagger.json',
        '/docs',
    ]
    out = []
    base = gateway_url.rstrip('/')
    for ep in endpoints:
        url = base + ep
        try:
            # OPTIONS for allowed methods
            opt = requests.options(url, headers=headers, timeout=timeout)
            allow = opt.headers.get('Allow') or opt.headers.get('allow')
            out.append(f'OPTIONS {url} -> status={opt.status_code} allow={allow}')
        except Exception as e:
            out.append(f'OPTIONS {url} -> ERROR: {e}')
        try:
            g = requests.get(url, headers=headers, timeout=timeout)
            # try to show a short snippet
            text = g.text
            snippet = text[:400].replace('\n', ' ')
            out.append(f'GET {url} -> status={g.status_code} resp_snippet="{snippet}"')
        except Exception as e:
            out.append(f'GET {url} -> ERROR: {e}')
    return "\n".join(out)


def discover_model_post_paths(gateway_url: str, headers: Dict = None, timeout: int = 5) -> List[str]:
    """Fetch /openapi.json and return candidate paths that accept POST and mention 'model'."""
    if headers is None:
        headers = {}
    base = gateway_url.rstrip('/')
    url = base + '/openapi.json'
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        spec = resp.json()
    except Exception:
        return []

    paths = spec.get('paths') or {}
    candidates: List[str] = []
    for p, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        # look for POST operations that either refer to model(s) or are admin-like
        if 'post' in ops:
            post = ops.get('post') or {}
            tags = post.get('tags') or []
            summary = post.get('summary') or ''
            operation_id = post.get('operationId') or ''
            if ('model' in p or 'models' in p) or any('admin' in t.lower() for t in tags if isinstance(t, str)) or \
               'admin' in p or 'ui' in p or 'manage' in p or 'create' in summary.lower() or 'create' in operation_id.lower():
                candidates.append(p)
    return candidates


def ensure_access_group(gateway_url: str, group_name: str, headers: Dict = None, timeout: int = 5) -> Dict:
    """Ensure an access group exists by POSTing to common access-group endpoints.
    Returns the created/existing group response or raises on unexpected failure.
    """
    if headers is None:
        headers = {}
    base = gateway_url.rstrip('/')
    payload = {'access_group_name': group_name}
    endpoints = ['/v1/access_group', '/v1/unified_access_group']
    last_exc = None
    for ep in endpoints:
        url = base + ep
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            # 200/201 created, 409 conflict means already exists
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code == 409:
                try:
                    return resp.json()
                except Exception:
                    return {'status': 'exists'}
            # For other statuses, raise to try next endpoint
            resp.raise_for_status()
        except requests.RequestException as exc:
            last_exc = exc
            continue
    # If we get here, all endpoints failed
    if last_exc:
        raise last_exc
    raise RuntimeError('Failed to ensure access group')


def parse_args():
    p = argparse.ArgumentParser(description='Sync models from an OpenAI-compatible API to an llmlite gateway')
    p.add_argument('--openai-url', default=os.environ.get('OPENAI_API_URL', 'https://api.openai.com'), help='OpenAI-compatible base URL')
    p.add_argument('--openai-key', default=os.environ.get('OPENAI_API_KEY'), help='OpenAI API key')
    p.add_argument('--github-url', default=os.environ.get('GITHUB_API_URL', 'https://api.github.com'), help='GitHub API base URL')
    p.add_argument('--github-token', default=os.environ.get('GITHUB_API_TOKEN'), help='GitHub API token for Copilot models catalog')
    p.add_argument('--include-github', action='store_true', help='Include GitHub Copilot models when discovering models')
    p.add_argument('--llmgateway-url', default=os.environ.get('LLMGATEWAY_URL', 'http://localhost:4000'), help='llmlite gateway base URL')
    p.add_argument('--llmgateway-key', default=os.environ.get('LLMGATEWAY_API_KEY'), help='llmlite gateway API key (if required)')
    p.add_argument('--dry-run', action='store_true', help='Show actions without performing POSTs')
    p.add_argument('--timeout', type=int, default=10, help='HTTP timeout seconds')
    p.add_argument('--public-prefix', default=os.environ.get('MODEL_PUBLIC_PREFIX', ''), help='Prefix to prepend to public model id')
    p.add_argument('--access-group', default=os.environ.get('LLM_ACCESS_GROUP'), help='Access group name to assign models to (creates group if missing)')
    return p.parse_args()


def main():
    args = parse_args()
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
        public_id = f"{prefix}{short}"
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
            res = add_llmlite_model(args.llmgateway_url, public_id, endpoint, api_key=args.llmgateway_key, access_group=args.access_group, timeout=args.timeout)
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
