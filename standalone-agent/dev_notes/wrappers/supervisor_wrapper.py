from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional

from ..base import DevNotesLogAdapter
from ..schema import DEFAULT_CATEGORY


SupervisorFn = Callable[..., Any]


def with_supervisor_logging(
    supervisor_fn: SupervisorFn,
    agent_name: str,
    adapter: DevNotesLogAdapter,
    category: str = DEFAULT_CATEGORY,
) -> SupervisorFn:

    @wraps(supervisor_fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        state: Dict[str, Any] = {}

        if args and isinstance(args[0], dict):
            state = args[0]

        if "state" in kwargs and isinstance(kwargs["state"], dict):
            state = kwargs["state"]

        result = None
        error: Optional[BaseException] = None

        try:
            result = supervisor_fn(*args, **kwargs)
            return result

        except BaseException as exc:
            error = exc
            raise

        finally:
            try:
                adapter.log_execution(
                    agent_name=agent_name,
                    state=state,
                    result=result,
                    error=error,
                    category=category,
                    metadata={"role": "supervisor"},
                )
            except Exception:
                pass

    return wrapped
