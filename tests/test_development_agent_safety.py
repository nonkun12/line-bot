import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone-agent"))

from agents.development import node


def test_patch_paths_reject_protected_files():
    patch = """diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-OLD\n+SECRET=bad\n"""
    with pytest.raises(RuntimeError, match="protected files"):
        node._validate_patch_paths(patch)


def test_patch_paths_allow_normal_source_file():
    patch = """diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"""
    node._validate_patch_paths(patch)
