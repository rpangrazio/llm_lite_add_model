# llmlite model sync

Small utility to fetch models from an OpenAI-compatible endpoint and register them with a [LiteLLM proxy](https://docs.litellm.ai/docs/simple_proxy) gateway.

## Quick start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Dry-run to preview what will be registered:

```bash
OPENAI_API_KEY=sk-... LLMGATEWAY_API_KEY=key... python add_models.py \
  --openai-url http://localhost:11434 \
  --llmgateway-url http://localhost:4000 \
  --dry-run
```

3. Remove `--dry-run` to perform registration.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | yes | API key for the source OpenAI-compatible endpoint |
| `LLMGATEWAY_API_KEY` | no | Master key for the LiteLLM gateway (Bearer token) |
| `GITHUB_API_TOKEN` | no | GitHub token to fetch Copilot models catalog |
| `MODEL_PUBLIC_PREFIX` | no | Prefix prepended to model names when registering (e.g. `local`) |
| `LLM_ACCESS_GROUP` | no | Access group to assign models to on the gateway |

All environment variables can also be passed as CLI flags (see `--help`).

A `./env` or `./.env` file is auto-loaded at startup if present. Existing shell variables always take priority.

## CLI flags

```
--openai-url          Source OpenAI-compatible base URL (default: https://api.openai.com)
--openai-key          Source API key
--llmgateway-url      LiteLLM gateway base URL (default: http://localhost:4000)
--llmgateway-key      LiteLLM gateway master key
--public-prefix       Prefix to prepend to registered model names
--access-group        Access group to assign to all registered models
--provider-cred       Provider credential: provider:key=value  (repeatable)
--provider-creds-file File containing provider:key=value lines (# comments allowed)
--set-credential      Create/update a gateway credential: name:provider:key=value,... (repeatable)
--list-credentials    List all credentials configured on the gateway and exit
--include-github      Also fetch GitHub Copilot models catalog
--github-url          GitHub Models base URL (default: https://models.github.ai)
--github-token        GitHub API token
--dry-run             Print planned actions without registering or deleting
--delete-all          Delete all models currently in the gateway, then exit
--timeout             HTTP timeout in seconds (default: 10)
```

## Gateway credentials

Use `--set-credential` to create or update a named credential stored in the LiteLLM gateway, and `--list-credentials` to inspect what's already configured.

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

> Credentials are encrypted and stored in the LiteLLM database.
> See the [LiteLLM UI Credentials docs](https://docs.litellm.ai/docs/proxy/ui_credentials) for details.

## Provider credentials

LiteLLM supports [stored LLM Credentials](https://docs.litellm.ai/docs/proxy/ui_credentials) configured via the UI. To attach an existing credential to every model being registered, pass its name via `--provider-cred` or a credentials file.

**Format:** `provider:key=value`

Supported keys per provider entry:

| Key | Description |
|---|---|
| `credential_name` | Name of an existing LiteLLM credential to attach to the model |
| `api_key` | API key sent by the gateway when calling the model backend |

**CLI example** — attach a pre-configured credential named `ollama-local` to all Ollama models:

```bash
python add_models.py \
  --openai-url http://localhost:11434 \
  --llmgateway-url http://localhost:4000 \
  --provider-cred openai:credential_name=ollama-local
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
