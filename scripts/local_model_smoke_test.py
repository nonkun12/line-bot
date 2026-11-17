"""One-command, read-only smoke test for the configured local model endpoint."""
from __future__ import annotations

from core.local_model_client import LocalModelError, create_local_model_client_from_env


def main() -> int:
    try:
        client = create_local_model_client_from_env()
        response = client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": "Reply with exactly LOCAL_MODEL_OK."},
                {"role": "user", "content": "Local connection smoke test."},
            ],
            temperature=0.0,
            max_completion_tokens=16,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            print("LOCAL_MODEL=FAIL reason=empty_response")
            return 1
        print(
            f"LOCAL_MODEL=PASS protocol={client.protocol} "
            f"model={client.model} response_chars={len(content)}"
        )
        return 0
    except LocalModelError as exc:
        print(f"LOCAL_MODEL=BLOCKED reason={exc}")
        return 2
    except Exception as exc:
        print(f"LOCAL_MODEL=FAIL reason={type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
