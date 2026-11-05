"""Who is calling? Verifies a Supabase-style login token (JWT) and returns the user id as the owner.

Two ways to verify, chosen by configuration (never by what the token claims):
  - `secret`: the project's legacy JWT secret, HS256.
  - `jwks_url`: the project's public keys (ES256 / RS256), fetched and cached by PyJWT.
The allowed algorithms are fixed per mode, so a token cannot pick `none` or switch an RSA/EC public key into an
HMAC secret ("algorithm confusion"). Expiry and audience are required; the issuer is checked when configured.

Needs the optional `auth` extra: pip install -e ".[auth]".
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request

BEARER = re.compile(r"^Bearer\s+([A-Za-z0-9._~+/=-]+)$")
ASYMMETRIC = ["ES256", "RS256"]


@dataclass
class AuthConfig:
    secret: str | None = None          # HS256 shared secret
    jwks_url: str | None = None        # public keys for ES256 / RS256
    issuer: str | None = None
    audience: str = "authenticated"    # Supabase sets this for signed-in users
    jwks_client: object | None = None  # injectable for tests: needs get_signing_key_from_jwt(token).key

    @classmethod
    def from_env(cls) -> AuthConfig | None:
        """SUPABASE_URL (+ SUPABASE_JWT_SECRET for HS256 projects); None when auth is not configured."""
        url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        secret = os.environ.get("SUPABASE_JWT_SECRET") or None
        if not url and not secret:
            return None
        base = f"{url}/auth/v1" if url else None
        return cls(secret=secret, jwks_url=f"{base}/.well-known/jwks.json" if base and not secret else None,
                   issuer=base)


def make_owner_resolver(config: AuthConfig) -> Callable[[Request], str]:
    import jwt  # PyJWT, optional dependency

    if not config.secret and not config.jwks_url and config.jwks_client is None:
        raise ValueError("auth needs either a JWT secret or a JWKS url")
    jwks = config.jwks_client
    if jwks is None and not config.secret:
        jwks = jwt.PyJWKClient(config.jwks_url, cache_keys=True, lifespan=3600)

    def resolve(request: Request) -> str:
        match = BEARER.match(request.headers.get("authorization", ""))
        if not match:
            raise HTTPException(401, "not signed in", headers={"WWW-Authenticate": "Bearer"})
        token = match.group(1)
        try:
            if config.secret:
                key, algorithms = config.secret, ["HS256"]
            else:
                key, algorithms = jwks.get_signing_key_from_jwt(token).key, ASYMMETRIC
            claims = jwt.decode(token, key, algorithms=algorithms, audience=config.audience, issuer=config.issuer,
                                options={"require": ["exp", "sub", "aud"]})
        except jwt.PyJWTError as e:
            raise HTTPException(401, "invalid or expired sign-in", headers={"WWW-Authenticate": "Bearer"}) from e
        return str(claims["sub"])

    return resolve
