from __future__ import annotations

import pytest

from scripts.autonomous_test_task_postrun_guard import verify_append_only_test_change


def test_accepts_exactly_one_appended_test_function():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new_boundary():\n    assert target(0) == 0\n"
    assert verify_append_only_test_change(before, after) == "test_new_boundary"


def test_rejects_modification_of_existing_test():
    before = "def test_existing():\n    assert True\n"
    after = "def test_existing():\n    assert False\n\n\ndef test_new():\n    assert True\n"
    with pytest.raises(ValueError, match="existing_test_file_ast_was_modified"):
        verify_append_only_test_change(before, after)


def test_rejects_removal_of_existing_test():
    before = "def test_existing():\n    assert True\n"
    after = "def test_new():\n    assert True\n"
    with pytest.raises(ValueError, match="change_must_append_exactly_one"):
        verify_append_only_test_change(before, after)


def test_rejects_non_test_top_level_append():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\nVALUE = 1\n"
    with pytest.raises(ValueError, match="appended_node_is_not"):
        verify_append_only_test_change(before, after)


def test_rejects_network_or_process_api_in_new_test():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new():\n    subprocess.run(['echo', 'bad'])\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden"):
        verify_append_only_test_change(before, after)


def test_rejects_import_inside_new_test():
    before = "def test_existing():\n    assert True\n"
    after = before + "\n\ndef test_new():\n    import socket\n"
    with pytest.raises(ValueError, match="new_test_must_not_add_imports"):
        verify_append_only_test_change(before, after)


def test_rejects_pathlib_filesystem_mutation():
    before = "def test_existing():\\n    assert True\\n"
    after = before + "\\n\\ndef test_new(tmp_path):\\n    tmp_path.joinpath('x').unlink(missing_ok=True)\\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden_attribute"):
        verify_append_only_test_change(before, after)


def test_rejects_dynamic_attribute_escape_hatch():
    before = "def test_existing():\\n    assert True\\n"
    after = before + "\\n\\ndef test_new():\\n    getattr(__builtins__, 'eval')('1 + 1')\\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden_escape_hatch|new_test_uses_forbidden_attribute"):
        verify_append_only_test_change(before, after)


def test_rejects_os_rename_even_without_direct_os_root_check():
    before = "def test_existing():\\n    assert True\\n"
    after = before + "\\n\\ndef test_new():\\n    os.rename('a', 'b')\\n"
    with pytest.raises(ValueError, match="new_test_uses_forbidden_attribute|new_test_uses_forbidden_os_api"):
        verify_append_only_test_change(before, after)
