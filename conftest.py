import pytest


@pytest.fixture(autouse=True)
def _isolate_mcp_save_guard(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_HTTP_READY_CHECK", "false")
    import db
    monkeypatch.setattr(db, "DB", str(tmp_path / "chat.db"))


class FakeNotesMcp:
    def __init__(self, save_script=None, search_script=None):
        self.notes=[]; self.calls=[]; self.save_script=list(save_script or []); self.search_script=list(search_script or [])
    def __call__(self, tool, args, timeout=None):
        self.calls.append((tool, dict(args), timeout))
        if tool=="save_note":
            if self.save_script:
                step=self.save_script.pop(0)
                if isinstance(step, Exception): raise step
                if isinstance(step, tuple) and step[0]=="lose":
                    self._store(args); raise step[1]
                if isinstance(step, str): return step
            return self._store(args)
        if tool=="search_notes":
            if self.search_script:
                step=self.search_script.pop(0)
                if isinstance(step, Exception): raise step
                return step
            kw=str(args.get("keyword","")).lower()
            rows=[n for n in self.notes if n["user_id"]==args["user_id"] and (kw in n["title"].lower() or kw in n["body"].lower() or kw in n["category"].lower())]
            if not rows: return "該当するメモはありません。"
            return "\n\n".join(f"ID:{i}\nタイトル:{n['title']}\n内容:{n['body']}\nカテゴリ:{n['category']}" for i,n in enumerate(rows,1))
        raise AssertionError(f"unexpected tool {tool}")
    def _store(self,args):
        if any(n["user_id"]==args["user_id"] and n["body"]==args["body"] for n in self.notes): return "同じ内容のメモが既にあります。"
        self.notes.append(dict(args)); return "メモを保存しました。"
    def saves(self): return [c for c in self.calls if c[0]=="save_note"]


@pytest.fixture
def fake_notes_mcp():
    return FakeNotesMcp
