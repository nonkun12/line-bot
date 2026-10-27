from pathlib import Path

import pytest

from scripts.create_app_scaffold import create_app, is_new_app_request, render_index, safe_slug


@pytest.mark.parametrize("instruction", [
    "TODO管理Webアプリを作って",
    "新しいアプリを開発して",
    "create a new app",
    "build a new web app",
])
def test_explicit_new_app_requests_are_detected(instruction):
    assert is_new_app_request(instruction)


@pytest.mark.parametrize("instruction", [
    "既存アプリの通知機能を改善して",
    "天気機能を改善して",
    "",
])
def test_maintenance_requests_stay_on_normal_workflow(instruction):
    assert not is_new_app_request(instruction)


def test_slug_is_path_safe_for_japanese_and_traversal_text():
    slug = safe_slug("../../ 新しいアプリ", "run/123")
    assert slug == "app-run123"
    assert "/" not in slug and "\\" not in slug and ".." not in slug


def test_create_app_writes_functional_starter_only_under_generated_root(tmp_path):
    paths = create_app("TODO管理Webアプリを作って", root=tmp_path, run_id="42")
    assert [p.relative_to(tmp_path).as_posix() for p in paths] == [
        "apps/generated/todo-web/index.html",
        "apps/generated/todo-web/README.md",
    ]
    page = paths[0].read_text(encoding="utf-8")
    assert 'id="task-form"' in page
    assert "localStorage" in page
    assert "textContent = task.text" in page
    assert "<script src=" not in page
    assert paths[1].exists()


def test_title_is_html_escaped():
    page = render_index('<script>alert("x")</script>')
    assert "&lt;script&gt;" in page
    assert "<script>alert(" not in page


def test_existing_app_is_never_overwritten(tmp_path):
    paths = create_app("TODO管理Webアプリを作って", root=tmp_path, run_id="42")
    paths[0].write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_app("TODO管理Webアプリを作って", root=tmp_path, run_id="42")
    assert paths[0].read_text(encoding="utf-8") == "keep"


def test_non_app_instruction_cannot_create_files(tmp_path):
    with pytest.raises(ValueError):
        create_app("既存アプリの通知機能を改善して", root=tmp_path, run_id="42")
    assert not (tmp_path / "apps").exists()
