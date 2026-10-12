"""
Rate limiting.

A local Ollama box answers one question at a time; a loop of requests will
queue up and make the machine crawl. Limits are per API key where there is
one, and per IP otherwise, so one noisy caller cannot starve the rest.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address


def rate_limit_key(request):
    api_key = request.headers.get("X-API-Key")

    if api_key:
        # Group by key, not by IP: several tenants may share one address.
        return f"key:{api_key[:24]}"

    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=rate_limit_key, default_limits=["240/minute"])
