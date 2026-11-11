"""Ayla LAN mode encryption: AES-128-CBC with zero padding + HMAC-SHA256 signing.

The key material is derived from the per-device `lanip_key` (provisioned by
the Ayla cloud during app setup) and the randoms/times exchanged in
`key_exchange.json`:

  - "app" encryption (us -> device):  msg = random_1 + random_2 + time_1 + time_2
  - "dev" encryption (device -> us):  msg = random_2 + random_1 + time_2 + time_1

Each key is `hmac(lanip_key, hmac(lanip_key, msg) + msg)`; the sign key, the
AES key and the IV seed use messages suffixed '0', '1' and '2'.

The CBC cipher context is persistent across messages (matching the module
firmware), so the chaining state carries over from one message to the next
until a new key exchange resets it.
"""

import base64
import hashlib
import hmac
import json
import random
import secrets
import string
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

AES_BLOCK_SIZE = 16


class KeyIdMismatch(Exception):
    """The device announced a lanip_key_id different from the configured one."""


class MessageSignatureError(InvalidSignature):
    """The signature of a device message did not validate."""


def _hmac_digest(key: bytes, msg: bytes) -> bytes:
    return hmac.digest(key, msg, hashlib.sha256)


def _build_key(lanip_key: bytes, msg: bytes) -> bytes:
    return _hmac_digest(lanip_key, _hmac_digest(lanip_key, msg) + msg)


def _pad(data: bytes) -> bytes:
    # Zero padding, non standard.
    return data + b"\x00" * (-len(data) % AES_BLOCK_SIZE)


class LanEncryption:
    """One direction of the encrypted channel (encryptor and decryptor states persist)."""

    def __init__(self, lanip_key: bytes, msg: bytes) -> None:
        self.sign_key = _build_key(lanip_key, msg + b"0")
        self.crypto_key = _build_key(lanip_key, msg + b"1")
        self.iv = _build_key(lanip_key, msg + b"2")[:AES_BLOCK_SIZE]
        self._cipher = Cipher(algorithms.AES(self.crypto_key), modes.CBC(self.iv))
        self._encryptor = self._cipher.encryptor()
        self._decryptor = self._cipher.decryptor()

    def encrypt(self, data: bytes) -> bytes:
        return self._encryptor.update(_pad(data))

    def decrypt(self, data: bytes) -> bytes:
        return self._decryptor.update(data).rstrip(b"\x00")

    def sign(self, data: bytes) -> str:
        return base64.b64encode(_hmac_digest(self.sign_key, data)).decode("utf-8")

    def encrypt_signed(self, data: bytes) -> dict[str, str]:
        return {
            "enc": base64.b64encode(self.encrypt(data)).decode("utf-8"),
            "sign": self.sign(data),
        }

    def decrypt_signed(self, payload: dict[str, str]) -> bytes:
        text = self.decrypt(base64.b64decode(payload["enc"]))
        if not hmac.compare_digest(self.sign(text), payload["sign"]):
            raise MessageSignatureError("Invalid signature for device message")
        return text


class LanSession:
    """Key exchange state and both encryption directions for one device."""

    def __init__(self, lanip_key: str, lanip_key_id: int) -> None:
        self.lanip_key = lanip_key.encode("utf-8")
        self.lanip_key_id = int(lanip_key_id)
        # Placeholder encryptions until the first key exchange, mirroring the
        # reference implementation (the device always starts with a key
        # exchange before sending meaningful traffic).
        self.app = LanEncryption(self.lanip_key, b"")
        self.dev = LanEncryption(self.lanip_key, b"")

    def start_exchange(self, key: dict) -> dict:
        """Handle a key_exchange request from the device; reply with our part."""
        if key.get("ver") != 1 or key.get("proto") != 1 or key.get("sec"):
            raise KeyIdMismatch(
                f"Invalid key exchange: ver={key.get('ver')} proto={key.get('proto')}"
            )
        key_id = int(key["key_id"])
        if key_id != self.lanip_key_id:
            raise KeyIdMismatch(
                f"The key_id has been replaced: old {self.lanip_key_id}, new {key_id}"
            )
        random_1 = str(key["random_1"])
        time_1 = int(key["time_1"])
        random_2 = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
        time_2 = time.monotonic_ns() % 2**40
        self.app = LanEncryption(
            self.lanip_key, (random_1 + random_2 + str(time_1) + str(time_2)).encode("utf-8")
        )
        self.dev = LanEncryption(
            self.lanip_key, (random_2 + random_1 + str(time_2) + str(time_1)).encode("utf-8")
        )
        return {"random_2": random_2, "time_2": time_2}

    def encrypt_message(self, payload: dict) -> dict:
        return self.app.encrypt_signed(json.dumps(payload).encode("utf-8"))

    def decrypt_message(self, payload: dict) -> dict:
        return json.loads(self.dev.decrypt_signed(payload).decode("utf-8"))
