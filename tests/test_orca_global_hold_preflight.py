import io
import json
import unittest
from unittest.mock import patch

from scripts.check_orca_global_hold import read_global_hold


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


class OrcaGlobalHoldPreflightTests(unittest.TestCase):
    def call(self, payload, status=200, api_url="https://orca.example", token="secret"):
        response = FakeResponse(json.dumps(payload).encode(), status)
        with patch("scripts.check_orca_global_hold.urlopen", return_value=response) as opener:
            result = read_global_hold(api_url, token, opener=opener)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://orca.example/control/global-hold")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(opener.call_args.kwargs["timeout"], 10)
        return result

    def test_only_explicit_off_is_accepted(self):
        result = self.call({"clear": True, "value": "off", "blocked": False})
        self.assertIs(result["clear"], True)

    def test_hold_on_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "active"):
            self.call({"clear": False, "value": "on", "blocked": True})

    def test_missing_or_unknown_control_is_blocked(self):
        for payload in (
            {"clear": False, "value": None, "blocked": True},
            {"clear": True, "value": "unknown", "blocked": False},
            {"clear": 1, "value": "off", "blocked": False},
            {"clear": True, "value": "off", "blocked": True},
        ):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                self.call(payload)

    def test_missing_api_url_or_token_fails_closed_without_network(self):
        for url, token in (("", "secret"), ("https://orca.example", "")):
            with self.subTest(url=url, token=token), self.assertRaises(RuntimeError):
                read_global_hold(url, token, opener=lambda *_a, **_k: self.fail("network must not be called"))

    def test_unavailable_or_invalid_endpoint_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            read_global_hold("https://orca.example", "secret",
                             opener=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError()))
        response = FakeResponse(b"not-json")
        with self.assertRaises(RuntimeError):
            read_global_hold("https://orca.example", "secret", opener=lambda *_a, **_k: response)

    def test_non_200_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "non-200"):
            self.call({"clear": True, "value": "off", "blocked": False}, status=503)


if __name__ == "__main__":
    unittest.main()
