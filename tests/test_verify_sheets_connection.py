"""
Unit tests for scripts/verify_sheets_connection.py.
Verifies read-only check logic, env validation, credential building,
GoogleSheetsClient instantiation, and API call mocking.
"""

import os
import sys
import json
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Dynamically import the script using importlib
script_path = Path(__file__).parent.parent / "scripts" / "verify_sheets_connection.py"
spec = importlib.util.spec_from_file_location("verify_sheets_connection", str(script_path))
verify_sheets_connection = importlib.util.module_from_spec(spec)
sys.modules["verify_sheets_connection"] = verify_sheets_connection
spec.loader.exec_module(verify_sheets_connection)


@pytest.fixture
def clean_env():
    """Backup and restore original environment variables."""
    old_env = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(old_env)


def test_missing_spreadsheet_id(clean_env):
    """Should return False if GOOGLE_SHEETS_SPREADSHEET_ID is missing or empty."""
    if "GOOGLE_SHEETS_SPREADSHEET_ID" in os.environ:
        del os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"]
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = "{}"

    success = verify_sheets_connection.run_verification()
    assert success is False


def test_missing_credentials(clean_env):
    """Should return False if both credentials variables are missing."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    if "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON" in os.environ:
        del os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"]
    if "GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE" in os.environ:
        del os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE"]

    success = verify_sheets_connection.run_verification()
    assert success is False


@patch("verify_sheets_connection.Credentials")
def test_invalid_json_format(mock_credentials, clean_env):
    """Should return False if credentials JSON contains invalid format."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = "invalid-json"

    success = verify_sheets_connection.run_verification()
    assert success is False


@patch("verify_sheets_connection.Credentials")
def test_missing_json_keys(mock_credentials, clean_env):
    """Should return False if required service account keys are missing in the JSON."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = '{"type": "service_account"}'

    success = verify_sheets_connection.run_verification()
    assert success is False


@patch("verify_sheets_connection.Credentials")
def test_credentials_file_not_found(mock_credentials, clean_env):
    """Should return False if credentials file path does not exist."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    if "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON" in os.environ:
        del os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"]
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE"] = "non-existent-credentials-file.json"

    success = verify_sheets_connection.run_verification()
    assert success is False


@patch("verify_sheets_connection.Credentials")
@patch("verify_sheets_connection.GoogleSheetsClient")
def test_client_instantiation_failure(mock_client, mock_credentials, clean_env):
    """Should return False if GoogleSheetsClient constructor raises an exception."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = json.dumps({
        "type": "service_account",
        "project_id": "proj",
        "private_key_id": "keyid",
        "private_key": "key",
        "client_email": "email"
    })

    mock_client.side_effect = Exception("client construction failed")

    success = verify_sheets_connection.run_verification()
    assert success is False


@patch("verify_sheets_connection.Credentials")
@patch("verify_sheets_connection.GoogleSheetsClient")
def test_api_access_failure(mock_client, mock_credentials, clean_env):
    """Should return False and not call append/delete if API call fails."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = json.dumps({
        "type": "service_account",
        "project_id": "proj",
        "private_key_id": "keyid",
        "private_key": "key",
        "client_email": "email"
    })

    instance = MagicMock()
    mock_client.return_value = instance
    instance.service.spreadsheets().get().execute.side_effect = Exception("API fetch error")

    success = verify_sheets_connection.run_verification()
    assert success is False

    # Assert append_row and delete_row are never called
    instance.append_row.assert_not_called()
    instance.delete_row.assert_not_called()


@patch("verify_sheets_connection.Credentials")
@patch("verify_sheets_connection.GoogleSheetsClient")
def test_api_access_success(mock_client, mock_credentials, clean_env):
    """Should return True and verify no writing methods are called on success."""
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = "test-id"
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = json.dumps({
        "type": "service_account",
        "project_id": "proj",
        "private_key_id": "keyid",
        "private_key": "key",
        "client_email": "email"
    })

    instance = MagicMock()
    mock_client.return_value = instance
    instance.spreadsheet_id = "test-id"
    instance.service.spreadsheets().get().execute.return_value = {
        "properties": {"title": "My SpreadSheet"},
        "sheets": [{"properties": {"title": "Sheet1"}}]
    }

    success = verify_sheets_connection.run_verification()
    assert success is True

    # Assert write methods are never called
    instance.append_row.assert_not_called()
    instance.delete_row.assert_not_called()


@patch("verify_sheets_connection.Credentials")
@patch("verify_sheets_connection.GoogleSheetsClient")
def test_api_access_failure_does_not_leak_secrets(mock_client, mock_credentials, clean_env, capsys):
    """Should return False and print a generic error message, redacting any raw exception secrets."""
    secret_spreadsheet_id = "secret-spreadsheet-12345"
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = secret_spreadsheet_id
    os.environ["GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"] = json.dumps({
        "type": "service_account",
        "project_id": "proj",
        "private_key_id": "keyid",
        "private_key": "secret-private-key-data",
        "client_email": "email"
    })

    instance = MagicMock()
    instance.spreadsheet_id = secret_spreadsheet_id
    mock_client.return_value = instance

    # Raise exception containing sensitive information
    sensitive_error_msg = f"Failed to connect to spreadsheet {secret_spreadsheet_id} with key secret-private-key-data"
    instance.service.spreadsheets().get().execute.side_effect = Exception(sensitive_error_msg)

    success = verify_sheets_connection.run_verification()
    assert success is False

    captured = capsys.readouterr()
    # Check that the print statement does not contain the secret details
    assert secret_spreadsheet_id not in captured.out
    assert "secret-private-key-data" not in captured.out
    # Check that it outputted the generic message
    assert "⑤ Read-only API access check: ❌ NG (Google Sheets API access failed)" in captured.out


@patch("verify_sheets_connection.run_verification")
def test_main_exits_0(mock_verify):
    """Main should exit with 0 when verification succeeds."""
    mock_verify.return_value = True
    with pytest.raises(SystemExit) as excinfo:
        verify_sheets_connection.main()
    assert excinfo.value.code == 0


@patch("verify_sheets_connection.run_verification")
def test_main_exits_1(mock_verify):
    """Main should exit with 1 when verification fails."""
    mock_verify.return_value = False
    with pytest.raises(SystemExit) as excinfo:
        verify_sheets_connection.main()
    assert excinfo.value.code == 1
