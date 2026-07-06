from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from kline.access import AccessDenied, CloudflareAccessVerifier
from kline.api import create_app
from kline.config import Settings


class FakeSource:
    def list_securities(self):
        return []

    def stock_history(self, *args, **kwargs):
        return pd.DataFrame()

    def adjustment_factors(self, *args, **kwargs):
        return pd.DataFrame([{
            "date": date(1900, 1, 1), "qfq_factor": 1.0, "hfq_factor": 1.0,
        }])

    def index_history(self, *args, **kwargs):
        return pd.DataFrame()


class SigningKey:
    key = "public-key"


class JwksClient:
    def get_signing_key_from_jwt(self, token):
        assert token == "signed-token"
        return SigningKey()


def test_verifier_validates_cloudflare_claim_contract():
    calls = []

    def decode(token, key, **kwargs):
        calls.append((token, key, kwargs))
        return {"email": "AcevedaCambero@Gmail.com"}

    settings = Settings(
        cloudflare_access_required=True,
        cloudflare_access_team_domain="example.cloudflareaccess.com",
        cloudflare_access_audience="aud-123",
        cloudflare_access_allowed_emails="acevedacambero@gmail.com",
    )

    claims = CloudflareAccessVerifier(
        settings, jwks_client=JwksClient(), decoder=decode
    ).verify("signed-token")

    assert claims["email"] == "AcevedaCambero@Gmail.com"
    assert calls == [("signed-token", "public-key", {
        "algorithms": ["RS256"],
        "audience": "aud-123",
        "issuer": "https://example.cloudflareaccess.com",
    })]


def test_verifier_rejects_email_outside_allowlist():
    settings = Settings(
        cloudflare_access_required=True,
        cloudflare_access_team_domain="example.cloudflareaccess.com",
        cloudflare_access_audience="aud-123",
        cloudflare_access_allowed_emails="allowed@example.com",
    )
    verifier = CloudflareAccessVerifier(
        settings,
        jwks_client=JwksClient(),
        decoder=lambda *_args, **_kwargs: {"email": "other@example.com"},
    )

    with pytest.raises(AccessDenied, match="email"):
        verifier.verify("signed-token")


class StubVerifier:
    def verify(self, token):
        if token != "valid":
            raise AccessDenied("invalid token")
        return {"email": "allowed@example.com"}


def test_production_api_requires_access_token_but_healthz_and_static_are_public(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>production-ui</h1>", encoding="utf-8")
    settings = Settings(
        data_path=tmp_path / "data",
        frontend_dist_path=dist,
        cloudflare_access_required=True,
        cloudflare_access_team_domain="example.cloudflareaccess.com",
        cloudflare_access_audience="aud-123",
        cloudflare_access_allowed_emails="allowed@example.com",
    )
    app = create_app(settings, FakeSource(), access_verifier=StubVerifier())

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert "production-ui" in client.get("/").text
        missing = client.get("/api/system/health")
        invalid = client.get(
            "/api/system/health", headers={"Cf-Access-Jwt-Assertion": "bad"}
        )
        valid = client.get(
            "/api/system/health", headers={"Cf-Access-Jwt-Assertion": "valid"}
        )

    assert missing.status_code == 403
    assert missing.json()["detail"]["code"] == "ACCESS_DENIED"
    assert invalid.status_code == 403
    assert valid.status_code == 200
