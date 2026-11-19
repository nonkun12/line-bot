import os

import certifi


def test_ssl_cert_file_defaults_to_certifi(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    assert os.environ["SSL_CERT_FILE"] == certifi.where()
