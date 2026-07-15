"""Caller-owned key and authenticated payload-encryption contracts."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import importlib
import json
import secrets
from typing import Mapping, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    key_id: str
    algorithm: str
    nonce_b64: str
    ciphertext_b64: str
    associated_data_sha256: str


class KeyProvider(Protocol):
    def get_key(self, key_id: str) -> bytes: ...


class PayloadCipher(Protocol):
    algorithm: str

    def encrypt(
        self, key: bytes, plaintext: bytes, associated_data: bytes
    ) -> tuple[bytes, bytes]: ...

    def decrypt(
        self, key: bytes, nonce: bytes, ciphertext: bytes, associated_data: bytes
    ) -> bytes: ...


class AesGcmCipher:
    algorithm = "AES-256-GCM"

    def __init__(self) -> None:
        try:
            module = importlib.import_module(
                "cryptography.hazmat.primitives.ciphers.aead"
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Encryption requires `pip install sophiagraph[encryption]`"
            ) from exc
        self._aesgcm = module.AESGCM

    def encrypt(
        self, key: bytes, plaintext: bytes, associated_data: bytes
    ) -> tuple[bytes, bytes]:
        if len(key) != 32:
            raise InvalidArgumentError("AES-256-GCM requires a 32-byte key")
        nonce = secrets.token_bytes(12)
        return nonce, self._aesgcm(key).encrypt(nonce, plaintext, associated_data)

    def decrypt(
        self, key: bytes, nonce: bytes, ciphertext: bytes, associated_data: bytes
    ) -> bytes:
        if len(key) != 32:
            raise InvalidArgumentError("AES-256-GCM requires a 32-byte key")
        return self._aesgcm(key).decrypt(nonce, ciphertext, associated_data)


class MappingKeyProvider:
    """In-process key provider for tests and caller-managed secret loaders."""

    def __init__(self, keys: Mapping[str, bytes]) -> None:
        self._keys = dict(keys)

    def get_key(self, key_id: str) -> bytes:
        try:
            return self._keys[key_id]
        except KeyError as exc:
            raise InvalidArgumentError(f"unknown encryption key: {key_id!r}") from exc


def encrypt_json_payload(
    payload: Mapping[str, object],
    *,
    key_id: str,
    key_provider: KeyProvider,
    cipher: PayloadCipher,
    associated_data: bytes = b"",
) -> EncryptedPayload:
    if not key_id:
        raise InvalidArgumentError("key_id is required")
    plaintext = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    nonce, ciphertext = cipher.encrypt(
        key_provider.get_key(key_id), plaintext, associated_data
    )
    return EncryptedPayload(
        key_id=key_id,
        algorithm=cipher.algorithm,
        nonce_b64=base64.b64encode(nonce).decode("ascii"),
        ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
        associated_data_sha256=sha256(associated_data).hexdigest(),
    )


def decrypt_json_payload(
    payload: EncryptedPayload,
    *,
    key_provider: KeyProvider,
    cipher: PayloadCipher,
    associated_data: bytes = b"",
) -> dict[str, object]:
    if payload.algorithm != cipher.algorithm:
        raise InvalidArgumentError("cipher does not match encrypted payload algorithm")
    if sha256(associated_data).hexdigest() != payload.associated_data_sha256:
        raise InvalidArgumentError("associated data does not match encrypted payload")
    plaintext = cipher.decrypt(
        key_provider.get_key(payload.key_id),
        base64.b64decode(payload.nonce_b64),
        base64.b64decode(payload.ciphertext_b64),
        associated_data,
    )
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise InvalidArgumentError("decrypted payload must be a JSON object")
    return decoded


__all__ = [
    "AesGcmCipher",
    "EncryptedPayload",
    "KeyProvider",
    "MappingKeyProvider",
    "PayloadCipher",
    "decrypt_json_payload",
    "encrypt_json_payload",
]
