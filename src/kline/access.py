from __future__ import annotations

from typing import Any, Callable

import jwt
from jwt import PyJWKClient

from .config import Settings


class AccessDenied(ValueError):
    pass


class CloudflareAccessVerifier:
    def __init__(
        self,
        settings: Settings,
        *,
        jwks_client: Any | None = None,
        decoder: Callable[..., dict[str, Any]] = jwt.decode,
    ) -> None:
        domain = settings.cloudflare_access_team_domain.strip().rstrip("/")
        audience = settings.cloudflare_access_audience.strip()
        allowed = {
            email.strip().lower()
            for email in settings.cloudflare_access_allowed_emails.split(",")
            if email.strip()
        }
        if not domain or not audience or not allowed:
            raise ValueError("Cloudflare Access domain, audience and email allowlist are required")
        self.issuer = domain if domain.startswith("https://") else f"https://{domain}"
        self.audience = audience
        self.allowed_emails = allowed
        self.jwks_client = jwks_client or PyJWKClient(
            f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True
        )
        self.decoder = decoder

    def verify(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = self.decoder(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
        except Exception as exc:
            raise AccessDenied("invalid Cloudflare Access token") from exc
        email = str(claims.get("email", "")).strip().lower()
        if email not in self.allowed_emails:
            raise AccessDenied("email is not allowed")
        return claims
