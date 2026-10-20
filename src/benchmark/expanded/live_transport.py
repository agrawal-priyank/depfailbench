"""Credential injection at dispatch only, on exact allowlisted HTTPS endpoints.

The credential-free request remains the saved scientific record. This module
never reads a key during import or preparation and never follows a redirect.
"""
import os
import httpx

from .providers import ENDPOINTS
from .spending import DispatchPaused

SECRET_NAMES = {"OpenAI": "OPENAI_API_KEY", "Anthropic": "ANTHROPIC_API_KEY",
                "Google": "GEMINI_API_KEY", "xAI": "XAI_API_KEY", "Mistral": "MISTRAL_API_KEY"}


def environment_credential(provider):
    name = SECRET_NAMES[provider]
    value = os.environ.get(name)
    if not value or any(c in value for c in "\r\n"):
        raise DispatchPaused(f"a valid {name} must be configured through secret settings")
    return value


class AuthenticatedTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, permit, credential_loader=environment_credential, wire_transport=None):
        permit.validate()
        self.permit, self.credential_loader = permit, credential_loader
        if permit.document['execution_mode'] == 'mock_validation' and type(wire_transport) is not httpx.MockTransport:
            raise DispatchPaused('mock-validation permission cannot open a real network transport')
        if permit.document['execution_mode'] == 'live' and wire_transport is not None:
            raise DispatchPaused('live execution cannot substitute synthetic HTTP responses')
        # Injection is only for deterministic tests. Production uses the fixed
        # HTTPS transport with certificate verification and no connection retries.
        if wire_transport is not None and type(wire_transport) is not httpx.MockTransport:
            raise ValueError("only MockTransport may replace the production wire transport")
        self.wire_transport = wire_transport or httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        self.permit.validate()
        providers = [p for p, (_, url) in ENDPOINTS.items() if str(request.url) == url]
        if len(providers) != 1 or request.method != "POST":
            raise DispatchPaused("request is outside the exact approved provider endpoint")
        if any(k in request.headers for k in ("authorization", "x-api-key", "x-goog-api-key")):
            raise DispatchPaused("persisted request must not already contain credentials")
        provider = providers[0]
        key = self.credential_loader(provider)
        if not isinstance(key, str) or not key or any(c in key for c in "\r\n"):
            raise DispatchPaused("invalid provider credential")
        headers = request.headers.copy()
        if provider == "Anthropic":
            headers["x-api-key"] = key
        elif provider == "Google":
            headers["x-goog-api-key"] = key
        else:
            headers["Authorization"] = "Bearer " + key
        authenticated = httpx.Request(request.method, request.url, headers=headers,
                                      stream=request.stream, extensions=request.extensions)
        return await self.wire_transport.handle_async_request(authenticated)

    async def aclose(self):
        await self.wire_transport.aclose()
