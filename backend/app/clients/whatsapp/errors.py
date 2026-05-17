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


class UazapiUnknown(UazapiError):
    """4xx not otherwise classified."""

    code = "unknown"
