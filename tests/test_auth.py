import base64
import hashlib
import hmac
import importlib.util
import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

HAVE = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "jwt", "cryptography"))
if HAVE:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from fastapi.testclient import TestClient

    from shorts_studio.api.app import Deps, Settings, create_app
    from shorts_studio.api.auth import AuthConfig
    from shorts_studio.api.store import ProjectStore

SECRET = "unit-test-secret-that-is-long-enough-for-hs256"
STORYBOARD = {"title": "t", "logline": "l",
              "voices": {"narrator": {"provider": "azure", "voice": "ko-KR-InJoonNeural", "rate": "0%", "pitch": "0%"}},
              "style": "S", "place": "P", "characters": {},
              "shots": [{"n": 1, "who": "narrator", "text": "안녕", "chars": [], "camera": "static",
                         "highlight": [], "scene": "s"}]}


def token(sub, secret=SECRET, alg="HS256", aud="authenticated", exp=3600, iss=None, drop=()):
    claims = {"sub": sub, "aud": aud, "exp": int(time.time()) + exp, "iss": iss}
    claims = {k: v for k, v in claims.items() if v is not None and k not in drop}
    return jwt.encode(claims, secret, algorithm=alg)


def b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


@unittest.skipUnless(HAVE, "needs fastapi, httpx and PyJWT (pip install -e .[api,auth,dev])")
class AuthCase(unittest.TestCase):
    config = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        sb = root / "sb.json"
        sb.write_text(json.dumps(STORYBOARD, ensure_ascii=False), encoding="utf-8")
        self.alice, self.bob = str(uuid.uuid4()), str(uuid.uuid4())
        for who in (self.alice, self.bob):
            ProjectStore(root / "data", who).create("demo", sb)
        ProjectStore(root / "data", self.alice).create("alices-only", sb)
        settings = Settings(root / "data", allowed_hosts=("testserver",), auth=self.config or AuthConfig(secret=SECRET),
                            embedded_workers=0)
        self.client = TestClient(create_app(settings, Deps()))

    def get(self, path, tok=None):
        return self.client.get(path, headers={"Authorization": f"Bearer {tok}"} if tok else {})


class SharedSecret(AuthCase):
    def test_health_is_open_everything_else_needs_a_token(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        for path in ("/api/projects", "/api/projects/demo", "/api/settings", "/api/voices", "/api/bgm-styles",
                     "/api/voices/sample?voice=ko-KR-InJoonNeural", "/api/projects/demo/renders"):
            r = self.get(path)
            self.assertEqual(r.status_code, 401, path)
            self.assertEqual(r.headers.get("www-authenticate"), "Bearer")
        self.assertEqual(self.client.post("/api/subtitles/preview", json={"text": "a"}).status_code, 401)
        self.assertEqual(self.client.post("/api/projects/demo/render", json={}).status_code, 401)

    def test_each_token_sees_only_its_own_user(self):
        a = [p["id"] for p in self.get("/api/projects", token(self.alice)).json()]
        b = [p["id"] for p in self.get("/api/projects", token(self.bob)).json()]
        self.assertEqual((a, b), (["alices-only", "demo"], ["demo"]))
        self.assertEqual(self.get("/api/projects/alices-only", token(self.bob)).status_code, 404)
        self.assertEqual(self.get("/api/projects/alices-only", token(self.alice)).status_code, 200)

    def test_bad_tokens_are_rejected(self):
        good = {"sub": self.alice}
        unsigned = jwt.encode({"sub": self.alice, "aud": "authenticated", "exp": int(time.time()) + 600}, None,
                              algorithm="none")
        bad = {
            "wrong secret": token(**good, secret="another-secret-that-is-also-long-enough-xx"),
            "expired": token(**good, exp=-10),
            "wrong audience": token(**good, aud="anon"),
            "no expiry": token(**good, drop=("exp",)),
            "no subject": token("x", drop=("sub",)),
            "alg none": unsigned,
            "other HMAC algorithm": token(**good, alg="HS512"),
            "garbage": "not.a.jwt",
        }
        for name, tok in bad.items():
            self.assertEqual(self.get("/api/projects", tok).status_code, 401, name)

    def test_malformed_authorization_headers_are_rejected(self):
        ok = token(self.alice)
        for value in ("", "Basic abc", "Bearer", f"Bearer {ok} extra", f"bearer{ok}", f"Token {ok}"):
            r = self.client.get("/api/projects", headers={"Authorization": value})
            self.assertEqual(r.status_code, 401, value)

    def test_a_subject_that_is_not_a_safe_folder_name_is_rejected(self):
        for sub in ("../etc", "a/b", "x" * 80, ""):
            self.assertEqual(self.get("/api/projects", token(sub)).status_code, 401, sub)


class Issuer(AuthCase):
    config = AuthConfig(secret=SECRET, issuer="https://proj.supabase.co/auth/v1") if HAVE else None

    def test_issuer_is_enforced_when_configured(self):
        good = token(self.alice, iss="https://proj.supabase.co/auth/v1")
        self.assertEqual(self.get("/api/projects", good).status_code, 200)
        self.assertEqual(self.get("/api/projects", token(self.alice, iss="https://evil.example")).status_code, 401)
        self.assertEqual(self.get("/api/projects", token(self.alice)).status_code, 401)   # no issuer at all


class PublicKeys(AuthCase):
    """ES256 tokens verified with a public key (what newer Supabase projects use)."""

    @staticmethod
    def new_key():
        priv = ec.generate_private_key(ec.SECP256R1())
        pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
        return priv, pem

    def setUp(self):
        self.priv, self.priv_pem = self.new_key()
        public = self.priv.public_key()
        self.public_pem = public.public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)

        class FakeJwks:
            def get_signing_key_from_jwt(self, tok):
                return type("K", (), {"key": public})()

        self.config = AuthConfig(jwks_client=FakeJwks())
        super().setUp()

    def test_a_token_signed_with_the_matching_private_key_is_accepted(self):
        tok = token(self.alice, secret=self.priv_pem, alg="ES256")
        self.assertEqual([p["id"] for p in self.get("/api/projects", tok).json()], ["alices-only", "demo"])

    def test_a_token_signed_by_someone_elses_key_is_rejected(self):
        _, other_pem = self.new_key()
        self.assertEqual(self.get("/api/projects", token(self.alice, secret=other_pem, alg="ES256")).status_code, 401)

    def test_algorithm_confusion_is_rejected(self):
        # An attacker who knows the PUBLIC key signs an HMAC token with it. PyJWT refuses to create that token, so
        # it is built by hand here; the server must still not accept it.
        head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = b64(json.dumps({"sub": self.alice, "aud": "authenticated", "exp": int(time.time()) + 600}).encode())
        sig = b64(hmac.new(self.public_pem, head + b"." + body, hashlib.sha256).digest())
        forged = (head + b"." + body + b"." + sig).decode()
        self.assertEqual(self.get("/api/projects", forged).status_code, 401)

    def test_hs256_tokens_are_not_accepted_in_public_key_mode(self):
        self.assertEqual(self.get("/api/projects", token(self.alice)).status_code, 401)


@unittest.skipUnless(HAVE, "needs PyJWT")
class FromEnv(unittest.TestCase):
    def test_configuration_from_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(AuthConfig.from_env())
        env = {"SUPABASE_URL": "https://p.supabase.co/", "SUPABASE_JWT_SECRET": "s"}
        with mock.patch.dict(os.environ, env, clear=True):
            c = AuthConfig.from_env()
            self.assertEqual((c.secret, c.jwks_url, c.issuer), ("s", None, "https://p.supabase.co/auth/v1"))
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://p.supabase.co"}, clear=True):
            c = AuthConfig.from_env()
            self.assertEqual((c.secret, c.jwks_url), (None, "https://p.supabase.co/auth/v1/.well-known/jwks.json"))


if __name__ == "__main__":
    unittest.main()
