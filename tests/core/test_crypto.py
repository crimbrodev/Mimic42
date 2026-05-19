from __future__ import annotations

from cryptography.fernet import Fernet

from mimic42.core.crypto import FernetSecretCipher


def test_fernet_secret_cipher_round_trips_without_plaintext_leak() -> None:
    cipher = FernetSecretCipher(Fernet.generate_key().decode())

    encrypted = cipher.encrypt("telegram-session-string")

    assert encrypted != "telegram-session-string"
    assert cipher.decrypt(encrypted) == "telegram-session-string"
