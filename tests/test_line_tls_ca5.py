import os
import certifi

def test_certifi_path_available():
    assert os.path.exists(certifi.where())
