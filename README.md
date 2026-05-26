# llmlite model sync

Small utility to fetch models from an OpenAI-compatible endpoint and register them with an llmlite gateway.

Usage:

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run (dry-run first):

	```bash
	OPENAI_API_KEY=sk-... LLMGATEWAY_API_KEY=key... python add_models.py --openai-url https://api.openai.com --llmgateway-url http://localhost:4000 --dry-run
	```

3. Remove `--dry-run` to perform registration.

Environment variables:

- `OPENAI_API_KEY` - required
- `LLMGATEWAY_API_KEY` - optional (used as Bearer token when talking to the gateway)
 - `GITHUB_API_TOKEN` - optional (Bearer token to fetch Copilot models)
 - `MODEL_PUBLIC_PREFIX` - optional prefix to prepend to public model id (can also use `--public-prefix`)

Notes:
- The script expects OpenAI-compatible `/v1/models` responses.
- The llmlite gateway is expected to expose a `/v1/models` GET (list) and POST (register) endpoint. Adjust URLs or payloads in `add_models.py` if your gateway API differs.
- To fetch GitHub Copilot models, set `GITHUB_API_TOKEN` and pass `--include-github` (and optionally `--github-url`, default `https://api.github.com`). The script will call the `/models/catalog` endpoint as described in GitHub's REST documentation.
- Public model naming: use `--public-prefix` (or `MODEL_PUBLIC_PREFIX`) to set a prefix that will be prepended to the short model name when registering with the gateway. The prefix and short name are joined with a single `/` (so `org` or `org/` both produce `org/model`). The script will strip any namespace segments before the last `/` from discovered model names (for example `org/model` becomes `model`).
