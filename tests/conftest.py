import pytest

import app.auth


@pytest.fixture(autouse=True)
def cheap_scrypt(monkeypatch):
    """Tests sign in often; production cost stays in app/auth.py."""
    monkeypatch.setattr(app.auth, "SCRYPT_N", 2**4)
