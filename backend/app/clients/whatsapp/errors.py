"""Provider error hierarchy.

Every subclass carries a stable `code` that maps directly to the SSE `failed`
event payload — the public contract with the frontend.
"""


class UazapiError(Exception):
    """Base error for the WhatsApp provider layer."""

    code: str = "unknown"


class UazapiUnavailable(UazapiError):
    """5xx or network-level failure from uazapi."""

    code = "uazapi_unavailable"


class UazapiTimeout(UazapiError):
    """httpx timeout against uazapi."""

    code = "timeout"


class UazapiBanned(UazapiError):
    """provider_code 463 — WhatsApp signaled the number is banned/throttled."""

    code = "banned"


class UazapiQrExpired(UazapiError):
    """QR window expired without a scan; provider needs `instance/connect` again."""

    code = "qr_expired"


class UazapiUnauthorized(UazapiError):
    """HTTP 401 — token foi rotacionado/invalidado pela uazapi.

    Diferente de UazapiUnavailable (5xx, transitório que vale tentar de novo),
    401 é terminal: o token nunca mais vai funcionar. Callers que dependem do
    token (poll loops, extract pipelines) devem abortar imediatamente em vez
    de gastar retry budget.
    """

    code = "token_invalid"


class UazapiUnknown(UazapiError):
    """4xx not otherwise classified."""

    code = "unknown"


class ProviderNotApplicable(Exception):
    """F8: raised when a provider-specific method is called on the wrong adapter.

    Used by ``ExtensionProvider`` to short-circuit uazapi-only operations
    (QR generation, /chat/find, etc.) — the extension reads WhatsApp Web
    directly in the user's browser, so the backend has no equivalent.
    """

    code: str = "provider_not_applicable"
