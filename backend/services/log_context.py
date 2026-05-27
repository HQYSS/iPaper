"""
Request-scoped logging context.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Optional, Tuple

_request_id_var = contextvars.ContextVar("request_id", default="-")
_user_id_var = contextvars.ContextVar("user_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        record.user_id = _user_id_var.get()
        return True


def set_request_context(request_id: str) -> contextvars.Token:
    return _request_id_var.set(request_id)


def set_log_user_id(user_id: Optional[str]) -> contextvars.Token:
    return _user_id_var.set(user_id or "-")


def reset_request_context(request_token: contextvars.Token, user_token: contextvars.Token) -> None:
    _request_id_var.reset(request_token)
    _user_id_var.reset(user_token)


def current_request_context() -> Tuple[str, str]:
    return _request_id_var.get(), _user_id_var.get()
