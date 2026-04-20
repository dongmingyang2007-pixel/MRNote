"""Authlib OAuth client registrations.

Centralizes provider config so routes stay thin. Import `oauth` to access
registered providers (e.g. `oauth.google.authorize_redirect(...)`).
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
