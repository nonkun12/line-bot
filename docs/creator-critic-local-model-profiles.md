# Local Creator/Critic model profiles

Creator and Critic can use separate local OpenAI-compatible endpoints. This
configuration is opt-in; Groq remains the backward-compatible default unless a
provider is selected explicitly.

## Select providers

Use one provider for both roles:

```sh
export CREATOR_CRITIC_PROVIDER=bonsai
```

Or use Bonsai for Creator and LFM for Critic:

```sh
export CREATOR_CRITIC_CREATOR_PROVIDER=bonsai
export CREATOR_CRITIC_CRITIC_PROVIDER=lfm
```

Each selected local provider requires its own explicit profile:

```sh
export CREATOR_CRITIC_BONSAI_BASE_URL=http://127.0.0.1:8081/v1
export CREATOR_CRITIC_BONSAI_MODEL='<exact model id returned by the Bonsai server>'

export CREATOR_CRITIC_LFM_BASE_URL='http://127.0.0.1:<verified-port>/v1'
export CREATOR_CRITIC_LFM_MODEL='<exact model id returned by the LFM server>'
```

The LFM port and served model ID are intentionally placeholders. Discover them
from the running local server; do not assume a port or infer the ID from the
Hugging Face repository name. Optional per-profile settings are
`CREATOR_CRITIC_BONSAI_API_KEY`, `CREATOR_CRITIC_LFM_API_KEY`, and
`CREATOR_CRITIC_<PROVIDER>_TIMEOUT` (1–120 seconds; default 30).

## Safety boundary

- Only plain HTTP loopback endpoints are accepted: `localhost`, `127.0.0.1`,
  or `::1`.
- Credentials embedded in URLs, query strings, fragments, external hosts, and
  HTTPS URLs are rejected.
- HTTP redirects are rejected so prompts cannot be forwarded to another host.
- No endpoint or model ID is guessed. A missing selected profile fails closed.
- This adapter does not make GitHub-hosted Actions able to reach a Mac's
  loopback interface. Run local inference on the Mac or use an explicitly
  secured runner/relay; never expose the local model port publicly.

Provider selection is for model routing only. It does not authorize code
execution, patch application, merging, or deployment.
