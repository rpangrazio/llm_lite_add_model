# llmlite model sync

Small utility to sync models from an OpenAI-compatible endpoint, optionally from the GitHub Models catalog, and register them with a LiteLLM gateway.

It can also list gateway credentials, create or update named credentials, and delete all registered models.

## Quick start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Dry-run to preview what will be registered:

```bash
OPENAI_API_KEY=sk-... LITELLM_MASTER_KEY=key... python add_models.py \
  --openai-url http://localhost:11434 \
  --llmgateway-url http://localhost:4000 \
  --dry-run
```

3. Remove `--dry-run` to perform registration.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_URL` | no | Source OpenAI-compatible base URL |
| `OPENAI_API_KEY` | yes | API key for the source OpenAI-compatible endpoint |
| `GITHUB_API_URL` | no | GitHub Models base URL |
| `GITHUB_API_TOKEN` | no | GitHub token for the Copilot models catalog |
| `LLMGATEWAY_URL` | no | LiteLLM gateway base URL |
| `LITELLM_MASTER_KEY` | no | Gateway API key |
| `MODEL_PUBLIC_PREFIX` | no | Prefix prepended to model names when registering (e.g. `local`) |
| `LLM_ACCESS_GROUP` | no | Access group assigned to registered models |

All of these can also be passed as CLI flags (see `--help`).

`GITHUB_API_TOKEN` is only needed when `--include-github` is set.

`./env` and `./.env` are auto-loaded at startup if present. Existing shell variables always take priority.

## CLI flags

| Flag | Description |
|---|---|
| `--openai-url` | Source OpenAI-compatible base URL (default: `https://api.openai.com`) |
| `--openai-key` | Source API key |
| `--include-github` | Fetch GitHub Copilot models too |
| `--github-token` | GitHub API token used with `--include-github` |
| `--github-url` | GitHub Models base URL (default: `https://models.github.ai`) |
| `--llmgateway-url` | LiteLLM gateway base URL (default: `http://localhost:4000`) |
| `--llmgateway-key` | LiteLLM gateway master key |
| `--public-prefix` | Prefix to prepend to registered model names |
| `--access-group` | Access group to assign to all registered models |
| `--provider-cred` | Provider credential mapping (`provider:key=value`), repeatable |
| `--provider-creds-file` | File containing provider credential mappings, one per line |
| `--gateway-credential` | Gateway credential name to apply to all imported models |
| `--set-credential` | Create or update a gateway credential (`name:provider:key=value,...`), repeatable |
| `--list-credentials` | List all credentials configured on the gateway and exit |
| `--dry-run` | Print planned actions without registering or deleting |
| `--delete-all` | Delete all models currently in the gateway, then exit |
| `--timeout` | HTTP timeout in seconds (default: `10`) |

## Gateway credentials

Use `--set-credential` to create or update a named credential stored in the gateway, and `--list-credentials` to inspect what's already configured.

**Format:** `name:provider:key=value,key2=value2`

| Part | Example | Description |
|---|---|---|
| `name` | `ollama-local` | Unique credential name on the gateway |
| `provider` | `OPENAI_LIKE` | LiteLLM provider string (e.g. `OPENAI_LIKE`, `openai`, `anthropic`) |
| `key=value,...` | `api_key=sk-...,api_base=http://...` | Comma-separated credential values |

**Examples:**

```bash
# Create a credential for a local Ollama instance
python add_models.py \
  --set-credential "ollama-local:OPENAI_LIKE:api_base=http://localhost:11434/v1,api_key=none"

# List all credentials on the gateway
python add_models.py --list-credentials

# Create a credential and sync models in one step
python add_models.py \
  --set-credential "ollama-local:OPENAI_LIKE:api_base=http://localhost:11434/v1,api_key=none" \
  --openai-url http://localhost:11434 \
  --provider-cred openai:credential_name=ollama-local
```

> Credentials are encrypted and stored in the gateway database.
> See the [LiteLLM UI Credentials docs](https://docs.litellm.ai/docs/proxy/ui_credentials) for details.

## Provider credentials

LiteLLM supports [stored LLM Credentials](https://docs.litellm.ai/docs/proxy/ui_credentials) configured via the UI. To attach an existing credential to every model being registered, pass its name via `--gateway-credential`. You can still use `--provider-cred` or a credentials file for source-specific mappings. If both are provided, `--gateway-credential` takes precedence. The script checks that the named credential already exists on the gateway before attaching it.

**Format:** `provider:key=value`

Supported keys per provider entry:

| Key | Description |
|---|---|
| `credential_name` | Name of an existing LiteLLM credential to attach to the model (stored as `litellm_params.litellm_credential_name`; the script uses the credential's provider when creating the model) |
| `api_key` | API key sent by the gateway when calling the model backend |

**CLI example** — attach a pre-configured credential named `ollama-local` to all Ollama models:

```bash
python add_models.py \
  --openai-url http://localhost:11434 \
  --llmgateway-url http://localhost:4000 \
  --provider-cred openai:credential_name=ollama-local
```

**CLI example** — attach one credential to every imported model (OpenAI-compatible + GitHub when enabled):

```bash
python add_models.py \
  --openai-url http://localhost:11434 \
  --include-github \
  --github-token ghp_... \
  --gateway-credential shared-gateway-cred
```

**File example** (`creds.txt`):

```
# OpenAI-compatible (Ollama) source
openai:credential_name=ollama-local

# GitHub Copilot source
github:credential_name=github-copilot
```

```bash
python add_models.py --provider-creds-file creds.txt ...
```

## Model naming

- The script strips namespace segments before the last `/` from discovered model names (e.g. `org/model-name` → `model-name`).
- Use `--public-prefix` (or `MODEL_PUBLIC_PREFIX`) to prepend a namespace when registering. For example `--public-prefix local` registers `model-name` as `local/model-name`.
- When `--include-github` is set, GitHub Copilot models are always registered under the `github_copilot/` prefix regardless of `--public-prefix`.
- The script is idempotent: models already present on the gateway are skipped.
