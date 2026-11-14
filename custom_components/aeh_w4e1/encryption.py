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
    """One direction of the encrypted channel with persistent CBC chaining.

    The firmware chains consecutive messages as if they were one CBC stream.
    Keeping the current IV explicitly (rather than retaining an opaque cipher
    context) lets signature verification be transactional: trying a payload
    with the wrong device key does not corrupt that device's receive state.
    """

    def __init__(self, lanip_key: bytes, msg: bytes) -> None:
        self.sign_key = _build_key(lanip_key, msg + b"0")
        self.crypto_key = _build_key(lanip_key, msg + b"1")
        self.iv = _build_key(lanip_key, msg + b"2")[:AES_BLOCK_SIZE]
        self._encrypt_iv = self.iv
        self._decrypt_iv = self.iv

    def _encrypt_with_iv(self, data: bytes, iv: bytes) -> bytes:
        encryptor = Cipher(algorithms.AES(self.crypto_key), modes.CBC(iv)).encryptor()
        return encryptor.update(_pad(data)) + encryptor.finalize()

    def _decrypt_with_iv(self, data: bytes, iv: bytes) -> bytes:
        if not data or len(data) % AES_BLOCK_SIZE:
            raise ValueError("Encrypted payload is not a non-empty AES block sequence")
        decryptor = Cipher(algorithms.AES(self.crypto_key), modes.CBC(iv)).decryptor()
        return (decryptor.update(data) + decryptor.finalize()).rstrip(b"\x00")

    def encrypt(self, data: bytes) -> bytes:
        encrypted = self._encrypt_with_iv(data, self._encrypt_iv)
        self._encrypt_iv = encrypted[-AES_BLOCK_SIZE:]
        return encrypted

    def decrypt(self, data: bytes) -> bytes:
        decrypted = self._decrypt_with_iv(data, self._decrypt_iv)
        self._decrypt_iv = data[-AES_BLOCK_SIZE:]
        return decrypted

    def sign(self, data: bytes) -> str:
        return base64.b64encode(_hmac_digest(self.sign_key, data)).decode("utf-8")

    def encrypt_signed(self, data: bytes) -> dict[str, str]:
        return {
            "enc": base64.b64encode(self.encrypt(data)).decode("utf-8"),
            "sign": self.sign(data),
        }

    def decrypt_signed(self, payload: dict[str, str]) -> bytes:
        encrypted = base64.b64decode(payload["enc"], validate=True)
        text = self._decrypt_with_iv(encrypted, self._decrypt_iv)
        if not hmac.compare_digest(self.sign(text), payload["sign"]):
            raise MessageSignatureError("Invalid signature for device message")
        # Commit the next CBC state only after the signature proves that this
        # payload belongs to this session. This matters when the LAN server
        # tries several devices to recover from an IP-address change.
        self._decrypt_iv = encrypted[-AES_BLOCK_SIZE:]
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
