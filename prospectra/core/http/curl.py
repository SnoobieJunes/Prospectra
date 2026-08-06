# 2026-07-31 (P7): A request as a curl command — the lingua franca for "what exactly will be
# sent?". The playground displays this beside the form, so the user can eyeball the real request
# (and paste it to a colleague) before anything goes over the wire.
#
# Secrets: `to_curl` never has the credential (only `send()` is ever handed it), so an auth header
# always renders masked. `redact=False` only unmasks the *user-typed* headers — never auth.

from __future__ import annotations

from urllib.parse import urlencode

from prospectra.core.http.request import (
    MASK,
    HttpRequest,
    redact_headers,
    redact_params,
)
from prospectra.core.http.send import _BODY_CONTENT_TYPES, auth_headers, auth_params


def _sh_quote(value: str) -> str:
    """Single-quote for a POSIX shell; embedded single quotes are '\\'' -escaped."""
    return "'" + value.replace("'", "'\\''") + "'"


def to_curl(request: HttpRequest, redact: bool = True) -> str:
    """The equivalent curl command, one option per line, credentials masked."""
    # 2026-08-05: user-typed params are redacted by NAME too — a key pasted into `?api_key=` is
    # just as much a credential as one in a header, and this output is meant to be shareable.
    params = redact_params(request.params) if redact else dict(request.params)
    # Auth renders as a masked placeholder in whatever position the real credential would occupy,
    # so the shape of the request is honest even though the secret is not shown.
    params.update({k: MASK for k in auth_params(request.auth, MASK)})
    url = request.url
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)

    parts = ["curl"]
    if request.method.upper() != "GET":
        parts.append(f"-X {request.method.upper()}")
    parts.append(_sh_quote(url))

    headers = redact_headers(request.headers) if redact else dict(request.headers)
    headers.update({k: MASK for k in auth_headers(request.auth, MASK)})
    content_type = _BODY_CONTENT_TYPES.get(request.body_kind)
    if content_type and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = content_type
    for name, value in headers.items():
        parts.append(f"-H {_sh_quote(f'{name}: {value}')}")

    if request.body_kind != "none" and request.body:
        parts.append(f"--data-raw {_sh_quote(request.body)}")

    return " \\\n  ".join(parts)
