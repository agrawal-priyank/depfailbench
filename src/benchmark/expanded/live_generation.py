"""Prepared authenticated sender. No calls occur without a reviewed permit.

Importing this module does not load credentials or authorize expenditure.
"""
from contextlib import asynccontextmanager
import httpx

from .execution_authorization import ExecutionPermit
from .live_transport import AuthenticatedTransport, environment_credential
from .provider_generation import _Generator
from .spending import DispatchPaused


class LiveGenerator(_Generator):
    simulation_only = False

    def __init__(self, *, output, ledger, rates, authorization, root=None,
                 credential_loader=environment_credential, wire_transport=None):
        if not isinstance(authorization, ExecutionPermit):
            raise DispatchPaused("explicit reviewed execution authorization is required")
        authorization.validate()
        if ledger.simulation_only or ledger.authorization is None or ledger.authorization.fingerprint != authorization.fingerprint:
            raise DispatchPaused("live sender requires its own authorized live ledger")
        self.authorization = authorization
        self.synthetic_data = wire_transport is not None
        transport = AuthenticatedTransport(permit=authorization, credential_loader=credential_loader,
                                           wire_transport=wire_transport)
        super().__init__(output=output, ledger=ledger, transport=transport, rates=rates, root=root)
        if self.root.resolve() != authorization.root.resolve():
            raise DispatchPaused("sender and authorization refer to different protocol roots")
        self.http_client = httpx.AsyncClient(transport=transport, trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(1800, connect=30))

    def authorize_slot(self, slot):
        super().authorize_slot(slot)
        self.authorization.validate_slot(slot, self.rates)

    @asynccontextmanager
    async def client(self):
        yield self.http_client

    async def aclose(self):
        await self.http_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()
