from pathlib import Path


def test_existing_repository_lookup_present():
    source = Path("scripts/universal_app_builder.py").read_text(encoding="utf-8")
    assert '/repos/{owner}/{name}' in source
    assert 'already exists on this account' in source
