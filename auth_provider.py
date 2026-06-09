"""Minimal in-memory OAuth 2.0 Authorization Server for the MCP connector.

Why this exists
---------------
claude.ai's *web* custom connector requires the remote MCP server to speak
OAuth (Dynamic Client Registration + authorization code + PKCE). An
unauthenticated server makes claude.ai fail with "Couldn't register with the
sign-in service" (Anthropic issue anthropics/claude-ai-mcp#402). This provider
implements just enough of the OAuth flow for that connector to succeed.

Security model (IMPORTANT)
--------------------------
Authorization is **auto-approved** — there is no login/consent screen. The
practical access control is therefore: (1) the unguessable public tunnel URL,
(2) read-only + path-sandboxed tools. Anyone who learns the URL can complete
the flow and read the exposed folder. For a real deployment, add a real
consent/login step or a pre-shared client secret. See README.
"""

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

AUTH_CODE_TTL = 600   # seconds
ACCESS_TOKEN_TTL = 3600  # seconds
_PURGE_EVERY = 500    # purge expired entries every N operations to bound memory


class SimpleOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self._op_count = 0

    def _purge_expired(self) -> None:
        """Remove expired tokens/codes to prevent unbounded memory growth."""
        self._op_count += 1
        if self._op_count % _PURGE_EVERY != 0:
            return
        now = time.time()
        self.auth_codes = {k: v for k, v in self.auth_codes.items() if v.expires_at > now}
        self.access_tokens = {
            k: v for k, v in self.access_tokens.items()
            if v.expires_at is None or v.expires_at > now
        }

    # --- Client registration (DCR) ---
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients[client_info.client_id] = client_info

    # --- Authorization (auto-approved) ---
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        self._purge_expired()
        code = secrets.token_urlsafe(32)
        self.auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(
            str(params.redirect_uri), code=code, state=params.state
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self.auth_codes.get(authorization_code)
        if code and code.client_id == client.client_id and code.expires_at > time.time():
            return code
        return None

    # --- Token issuance ---
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self.auth_codes.pop(authorization_code.code, None)
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        rt = self.refresh_tokens.get(refresh_token)
        if rt and rt.client_id == client.client_id:
            return rt
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self.refresh_tokens.pop(refresh_token.token, None)
        return self._issue(client.client_id, scopes or refresh_token.scopes, None)

    async def load_access_token(self, token: str) -> AccessToken | None:
        self._purge_expired()
        at = self.access_tokens.get(token)
        if at and (at.expires_at is None or at.expires_at > time.time()):
            return at
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.access_tokens.pop(token.token, None)
        self.refresh_tokens.pop(token.token, None)

    # --- helper ---
    def _issue(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        self.access_tokens[access] = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + ACCESS_TOKEN_TTL,
            resource=resource,
        )
        self.refresh_tokens[refresh] = RefreshToken(
            token=refresh, client_id=client_id, scopes=scopes
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL,
            refresh_token=refresh,
            scope=" ".join(scopes) or None,
        )
