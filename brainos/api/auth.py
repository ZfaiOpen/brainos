# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See the LICENSE file for details.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.auth")


class AuthMethod(Enum):
    API_KEY = "api_key"
    JWT = "jwt"
    BEARER = "bearer"


@dataclass
class AuthToken:
    token_id: str
    method: AuthMethod
    client_id: str
    scopes: list[str] = field(default_factory=list)
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    @logged()
    @safe_execute
    def to_dict(self):
        pass


    @property
    def is_expired(self):
        pass



@dataclass
class AuthResult:
    authenticated: bool
    client_id: str = ""
    scopes: list[str] = field(default_factory=list)
    error: str = ""

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, object]:
        return {
            "authenticated": self.authenticated,
            "client_id": self.client_id,
            "scopes": list(self.scopes),
            "error": self.error,
        }


class AuthManager:
    def __init__(self, secret_key: str = "") -> None:
        self._secret_key = secret_key or os.environ.get("BRAINOS_AUTH_SECRET", "") or secrets.token_hex(32)
        self._api_keys: dict[str, str] = {}
        self._tokens: dict[str, AuthToken] = {}
        self._revoked: set[str] = set()
        self._client_scopes: dict[str, list[str]] = {}

    @logged()
    @safe_execute
    def register_api_key(self, client_id: str, scopes: list[str] | None = None) -> str:
        raw_key = secrets.token_urlsafe(32)
        hashed = self._hash_api_key(raw_key)
        self._api_keys[hashed] = client_id
        self._client_scopes[client_id] = scopes or ["read"]
        logger.info("API key registered for client: %s", client_id)
        return raw_key

    @logged()
    @safe_execute
    def authenticate(self, credentials: dict[str, str]) -> AuthResult:
        method = credentials.get("method", "")
        if method == "api_key" or "api_key" in credentials:
            return self._authenticate_api_key(credentials.get("api_key", ""))
        if method == "bearer" or "token" in credentials:
            return self._authenticate_bearer(credentials.get("token", ""))
        if method == "jwt" or "jwt" in credentials:
            return self._authenticate_jwt(credentials.get("jwt", ""))
        return AuthResult(authenticated=False, error="Unknown auth method")

    @logged()
    @safe_execute
    def create_token(
        self,
        client_id: str,
        scopes: list[str],
        ttl_seconds: float = 3600.0,
    ) -> AuthToken:
        token_id = secrets.token_hex(16)
        expires_at = time.time() + ttl_seconds if ttl_seconds != 0 else 0.0
        token = AuthToken(
            token_id=token_id,
            method=AuthMethod.BEARER,
            client_id=client_id,
            scopes=list(scopes),
            expires_at=expires_at,
        )
        self._tokens[token_id] = token
        self._client_scopes[client_id] = list(scopes)
        logger.debug("Token created for client: %s", client_id)
        return token

    @logged()
    @safe_execute
    def validate_token(self, token: str) -> AuthResult:
        if token in self._revoked:
            return AuthResult(authenticated=False, error="Token revoked")
        auth_token = self._tokens.get(token)
        if auth_token is not None:
            if auth_token.is_expired:
                return AuthResult(authenticated=False, error="Token expired")
            return AuthResult(
                authenticated=True,
                client_id=auth_token.client_id,
                scopes=auth_token.scopes,
            )
        jwt_payload = self._verify_jwt(token)
        if jwt_payload is not None:
            client_id = str(jwt_payload.get("client_id", ""))
            scopes = jwt_payload.get("scopes", [])
            if isinstance(scopes, list):
                scopes = [str(s) for s in scopes]
            else:
                scopes = []
            token_id = str(jwt_payload.get("token_id", ""))
            if token_id in self._revoked:
                return AuthResult(authenticated=False, error="Token revoked")
            return AuthResult(
                authenticated=True,
                client_id=client_id,
                scopes=scopes,
            )
        return AuthResult(authenticated=False, error="Invalid token")

    @logged()
    @safe_execute
    def revoke_token(self, token_id: str) -> bool:
        self._revoked.add(token_id)
        self._tokens.pop(token_id, None)
        logger.info("Token revoked: %s", token_id)
        return True

    @logged()
    @safe_execute
    def check_scope(self, token: str, required_scope: str) -> bool:
        result = self.validate_token(token)
        if not result.authenticated:
            return False
        if "*" in result.scopes:
            return True
        return required_scope in result.scopes

    def _hash_api_key(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def _generate_jwt(self, payload: dict[str, object]) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=")
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
        signing_input = header_b64 + b"." + payload_b64
        signature = hmac.new(self._secret_key.encode(), signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
        return (signing_input + b"." + sig_b64).decode()

    def _verify_jwt(self, token: str) -> dict[str, object] | None:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            header_b64 = parts[0].encode()
            payload_b64 = parts[1].encode()
            sig_b64 = parts[2].encode()
            signing_input = header_b64 + b"." + payload_b64
            padding = 4 - len(sig_b64) % 4
            if padding != 4:
                sig_b64 += b"=" * padding
            expected_sig = hmac.new(self._secret_key.encode(), signing_input, hashlib.sha256).digest()
            actual_sig = base64.urlsafe_b64decode(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                return None
            payload_padding = 4 - len(payload_b64) % 4
            if payload_padding != 4:
                payload_b64 += b"=" * payload_padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            if "exp" in payload:
                if time.time() > float(payload["exp"]):
                    return None
            return payload
        except Exception as _exc:
            logger.warning("JWT verification failed")
            return None

    def _authenticate_api_key(self, api_key: str) -> AuthResult:
        if not api_key:
            return AuthResult(authenticated=False, error="Missing API key")
        hashed = self._hash_api_key(api_key)
        client_id = self._api_keys.get(hashed)
        if client_id is None:
            return AuthResult(authenticated=False, error="Invalid API key")
        scopes = self._client_scopes.get(client_id, ["read"])
        return AuthResult(authenticated=True, client_id=client_id, scopes=scopes)

    def _authenticate_bearer(self, token: str) -> AuthResult:
        if not token:
            return AuthResult(authenticated=False, error="Missing token")
        return self.validate_token(token)

    def _authenticate_jwt(self, jwt_str: str) -> AuthResult:
        if not jwt_str:
            return AuthResult(authenticated=False, error="Missing JWT")
        payload = self._verify_jwt(jwt_str)
        if payload is None:
            return AuthResult(authenticated=False, error="Invalid JWT")
        client_id = str(payload.get("client_id", ""))
        scopes = payload.get("scopes", [])
        if isinstance(scopes, list):
            scopes = [str(s) for s in scopes]
        else:
            scopes = []
        return AuthResult(authenticated=True, client_id=client_id, scopes=scopes)
