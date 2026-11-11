"""Unit tests for the Ayla LAN encryption, session and settings bitmap."""

import json

import pytest

from custom_components.aeh_w4e1.encryption import (
    KeyIdMismatch,
    LanEncryption,
    LanSession,
    MessageSignatureError,
)

LAN_KEY = "GT2V4DKAAABBCDDS"


def test_key_roundtrip_matches_reference_formula():
    """Keys derive as hmac(lanip_key, hmac(lanip_key, msg) + msg)."""
    import hashlib
    import hmac as hmac_mod

    msg = b"abcdefgh12345678" + b"zyxwvuts98765432" + b"123456" + b"654321"
    lanip_key = LAN_KEY.encode()
    for suffix in (b"0", b"1", b"2"):
        inner = hmac_mod.digest(lanip_key, msg + suffix, hashlib.sha256)
        expected = hmac_mod.digest(lanip_key, inner + msg + suffix, hashlib.sha256)
        enc = LanEncryption(lanip_key, msg)
        if suffix == b"0":
            assert enc.sign_key == expected
        elif suffix == b"1":
            assert enc.crypto_key == expected
        else:
            assert enc.iv == expected[:16]


def test_encrypt_decrypt_roundtrip():
    """Each direction round-trips its own messages (server<->device roles)."""
    app = LanEncryption(LAN_KEY.encode(), b"aaaabbbb11112222")
    dev = LanEncryption(LAN_KEY.encode(), b"bbbbaaaa22221111")
    payload = {"seq_no": 1, "data": {"name": "t_temp", "value": 23}}

    signed = app.encrypt_signed(json.dumps(payload).encode())
    assert "enc" in signed and "sign" in signed
    assert app.decrypt_signed(signed) == json.dumps(payload).encode()

    # The other direction has independent keys and cipher state.
    back = dev.encrypt_signed(b"hello")
    assert dev.decrypt_signed(back) == b"hello"


def test_session_message_roundtrip_both_directions():
    """A LanSession exchanges keys once and both directions interoperate."""
    session = LanSession(LAN_KEY, 7)
    reply = session.start_exchange(
        {"ver": 1, "proto": 1, "key_id": 7, "random_1": "abcdef0123456789", "time_1": 123}
    )

    # Mirror the device side: it derives both directions from the exchange.
    random_1, time_1 = "abcdef0123456789", "123"
    random_2, time_2 = reply["random_2"], str(reply["time_2"])
    device_app = LanEncryption(  # used to decrypt server->device messages
        LAN_KEY.encode(), (random_1 + random_2 + time_1 + time_2).encode()
    )
    device_dev = LanEncryption(  # used to encrypt device->server messages
        LAN_KEY.encode(), (random_2 + random_1 + time_2 + time_1).encode()
    )

    commands = {"seq_no": 1, "data": {}}
    on_wire = session.encrypt_message(commands)
    assert json.loads(device_app.decrypt_signed(on_wire)) == commands

    datapoint = {"seq_no": 1, "data": {"name": "f_temp_in", "value": 81.5}}
    encrypted = device_dev.encrypt_signed(json.dumps(datapoint).encode())
    assert session.decrypt_message(encrypted) == datapoint


def test_signature_validation():
    enc = LanEncryption(LAN_KEY.encode(), b"aaaabbbb11112222")
    signed = enc.encrypt_signed(b"data")
    bad = dict(signed, sign="AAAA" + signed["sign"][4:])
    with pytest.raises(MessageSignatureError):
        enc.decrypt_signed(bad)


def test_cipher_state_persists_across_messages():
    enc = LanEncryption(LAN_KEY.encode(), b"msg0msg0msg0msg0")
    first = enc.encrypt(b"same-input")
    second = enc.encrypt(b"same-input")
    assert first != second  # CBC chaining continues across messages


def test_zero_padding():
    enc = LanEncryption(LAN_KEY.encode(), b"m" * 16)
    for size in (1, 15, 16, 17, 33):
        data = b"x" * size
        encrypted = enc.encrypt(data)
        assert len(encrypted) % 16 == 0
        assert len(encrypted) >= size


def test_key_exchange():
    session = LanSession(LAN_KEY, 12345)
    reply = session.start_exchange(
        {"ver": 1, "proto": 1, "key_id": 12345, "random_1": "abcdef0123456789", "time_1": 123456}
    )
    assert len(reply["random_2"]) == 16
    assert 0 <= reply["time_2"] < 2**40

    with pytest.raises(KeyIdMismatch):
        session.start_exchange(
            {"ver": 1, "proto": 1, "key_id": 999, "random_1": "abcdef0123456789", "time_1": 1}
        )
    with pytest.raises(KeyIdMismatch):
        session.start_exchange(
            {"ver": 2, "proto": 1, "key_id": 12345, "random_1": "abcdef0123456789", "time_1": 1}
        )


def test_settings_bitmap():
    from custom_components.aeh_w4e1.bitmap import SettingsBitmap

    bitmap = SettingsBitmap(0)
    bitmap = bitmap.with_field("t_power", 1)
    bitmap = bitmap.with_field("t_work_mode", 2)  # cool
    bitmap = bitmap.with_field("t_temp", 23)
    bitmap = bitmap.with_field("t_fan_speed", 7)  # medium
    bitmap = bitmap.with_field("t_fan_power", 1)
    bitmap = bitmap.with_field("t_fan_leftright", 1)

    assert bitmap.get("t_power") == 1
    assert bitmap.get("t_work_mode") == 2
    assert bitmap.get("t_temp") == 23
    assert bitmap.get("t_fan_speed") == 7
    assert bitmap.get("t_fan_power") == 1
    assert bitmap.get("t_fan_leftright") == 1
    assert bitmap.get("t_fan_mute") == 0
    assert bitmap.get("t_eco") == 0

    decoded = bitmap.to_properties()
    assert decoded["t_power"] == 1 and decoded["t_temp"] == 23

    # A partial write keeps only its own present-flag: other fields stay
    # encoded but inactive, exactly like the module interprets updates.
    partial = bitmap.with_field("t_temp", 25)
    assert partial.get("t_temp") == 25
    raw_prev, raw_new = bitmap.raw, partial.raw
    assert bin(raw_new).count("1") < bin(raw_prev).count("1") + 16

    # The Fahrenheit range must survive the bitmap (7 value bits).
    assert SettingsBitmap(0).with_field("t_temp", 86).get("t_temp") == 86
    assert SettingsBitmap(0).with_field("t_temp", 61).get("t_temp") == 61

    # Round-trip through the present-flag clear mask keeps values readable.
    from custom_components.aeh_w4e1.bitmap import _PRESENT_FLAG_MASK

    masked = SettingsBitmap(bitmap.raw & _PRESENT_FLAG_MASK)
    assert masked.to_properties() == decoded
