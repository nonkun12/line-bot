import sqlite3
import time
from contextlib import contextmanager

import httpx
import pytest

import db
import mcp_client
import note_save_guard as guard
from agents.notes.handlers import handle_save_note

USER="Utest"
BODY="今日MCPの自動起動テストを実施した"


def _resp(status, headers=None, json_data=None, method="POST"):
    req=httpx.Request(method,"https://example.test/x")
    return httpx.Response(status, headers=headers, json=json_data, request=req) if json_data is not None else httpx.Response(status, headers=headers, request=req)

def _status_error(status, headers=None):
    r=_resp(status,headers)
    return httpx.HTTPStatusError("err",request=r.request,response=r)

def _rows():
    with db.get_conn() as conn:
        try: return conn.execute("SELECT key,state FROM note_save_attempts").fetchall()
        except sqlite3.OperationalError: return []

@pytest.fixture(autouse=True)
def _off_render(monkeypatch):
    monkeypatch.delenv("MCP_RENDER_ON_DEMAND",raising=False)
    monkeypatch.setenv("MCP_SAVE_MAX_ATTEMPTS","2")


def test_verified_success_requires_readback(fake_notes_mcp):
    fake=fake_notes_mcp(); result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.SAVED
    assert [c[0] for c in fake.calls]==["save_note","search_notes"]
    assert _rows()==[]


def test_saved_text_without_readback_is_unknown(fake_notes_mcp):
    fake=fake_notes_mcp(search_script=["該当するメモはありません。"])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.UNKNOWN
    assert [r[1] for r in _rows()]==["unknown"]


def test_readback_error_is_unknown(fake_notes_mcp):
    fake=fake_notes_mcp(search_script=[httpx.ReadTimeout("slow")])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.UNKNOWN


def test_server_error_is_not_relayed(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=["保存エラー: secret"])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.FAILED and "secret" not in result.message and "保存エラー" not in result.message


def test_unknown_text_is_not_success(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=["saved"])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.UNKNOWN and len(fake.notes)==0


def test_duplicate_text_is_not_new_save(fake_notes_mcp):
    fake=fake_notes_mcp(); guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.ALREADY_EXISTS and len(fake.notes)==1


def test_lost_response_is_verified_without_resend(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=[("lose",httpx.ReadTimeout("lost"))])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.SAVED and len(fake.saves())==1 and len(fake.notes)==1


def test_ambiguous_failure_never_blindly_resent(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=[httpx.ReadTimeout("lost")])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.UNKNOWN and len(fake.saves())==1


@pytest.mark.parametrize("exc",[httpx.ReadTimeout("x"),_status_error(500),_status_error(504),httpx.RemoteProtocolError("x")])
def test_ambiguous_failures_have_one_write(fake_notes_mcp,exc):
    fake=fake_notes_mcp(save_script=[exc]); result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.UNKNOWN and len(fake.saves())==1


def test_connect_error_can_retry_once(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=[httpx.ConnectError("refused")])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.SAVED and len(fake.saves())==2 and len(fake.notes)==1


def test_hibernate_429_is_bounded(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=[_status_error(429,{"x-render-routing":"hibernate-rate-limited"})]*5)
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.FAILED and len(fake.saves())==2


def test_4xx_is_not_resent(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=[_status_error(401)])
    result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.FAILED and len(fake.saves())==1


def test_pending_blocks_resend(fake_notes_mcp):
    first=fake_notes_mcp(save_script=[httpx.ReadTimeout("lost")]); guard.save_note_safely(first,USER,"LINEメモ",BODY,"一般")
    second=fake_notes_mcp(); result=guard.save_note_safely(second,USER,"LINEメモ",BODY,"一般")
    assert second.saves()==[] and [c[0] for c in second.calls]==["search_notes"] and result.status==guard.UNKNOWN


def test_pending_resolves_from_readback(fake_notes_mcp):
    first=fake_notes_mcp(save_script=[httpx.ReadTimeout("lost")]); guard.save_note_safely(first,USER,"LINEメモ",BODY,"一般")
    second=fake_notes_mcp(); second.notes.append({"user_id":USER,"title":"LINEメモ","body":BODY,"category":"一般"})
    result=guard.save_note_safely(second,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.SAVED and second.saves()==[] and _rows()==[]


def test_stale_pending_can_retry(fake_notes_mcp,monkeypatch):
    first=fake_notes_mcp(save_script=[httpx.ReadTimeout("lost")]); guard.save_note_safely(first,USER,"LINEメモ",BODY,"一般")
    monkeypatch.setenv("MCP_SAVE_PENDING_TTL_SEC","1"); now=time.time(); monkeypatch.setattr(guard.time,"time",lambda:now+5)
    second=fake_notes_mcp(); result=guard.save_note_safely(second,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.SAVED and len(second.saves())==1


def test_ledger_never_stores_note_text(fake_notes_mcp):
    fake=fake_notes_mcp(save_script=[httpx.ReadTimeout("lost")]); guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    with db.get_conn() as conn: dump="\n".join(conn.iterdump())
    assert BODY not in dump and USER not in dump


def test_single_on_demand_session_wraps_save_and_readback(fake_notes_mcp,monkeypatch):
    events=[]
    @contextmanager
    def session():
        events.append("enter"); yield; events.append("exit")
    monkeypatch.setattr("render_client.mcp_service_session",session)
    fake=fake_notes_mcp(); guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert events==["enter","exit"]


def test_render_session_failure_sends_nothing(fake_notes_mcp,monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("not ready")
        yield
    monkeypatch.setattr("render_client.mcp_service_session",broken)
    fake=fake_notes_mcp(); result=guard.save_note_safely(fake,USER,"LINEメモ",BODY,"一般")
    assert result.status==guard.FAILED and fake.calls==[]


def test_health_url_derived(monkeypatch):
    monkeypatch.setattr(mcp_client,"MCP_SERVER_URL","https://my-mcp-server-dqbx.onrender.com/mcp")
    monkeypatch.delenv("MCP_HEALTH_URL",raising=False)
    assert mcp_client.mcp_health_url()=="https://my-mcp-server-dqbx.onrender.com/health"


def test_readiness_requires_two_stable_ok(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_READY_CHECK","true"); monkeypatch.setenv("MCP_READY_POLL_SEC","1"); monkeypatch.setenv("MCP_READY_MAX_SEC","10")
    clock=[0.0]; monkeypatch.setattr(mcp_client.time,"monotonic",lambda:clock[0]); monkeypatch.setattr(mcp_client.time,"sleep",lambda s:clock.__setitem__(0,clock[0]+s))
    responses=[_resp(429,{"x-render-routing":"hibernate-rate-limited"},method="GET"),_resp(503,method="GET"),_resp(200,json_data={"ok":True},method="GET"),_resp(200,json_data={"ok":True},method="GET")]
    monkeypatch.setattr(mcp_client.httpx,"get",lambda *a,**k:responses.pop(0))
    mcp_client.wait_for_mcp_http_ready()
    assert responses==[]


def test_readiness_does_not_send_api_key(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_READY_CHECK","true"); monkeypatch.setenv("MCP_READY_POLL_SEC","1"); monkeypatch.setenv("MCP_READY_MAX_SEC","2"); monkeypatch.setenv("MCP_READY_STABLE_COUNT","1")
    seen={}
    monkeypatch.setattr(mcp_client.httpx,"get",lambda url,**kw: seen.update(kw) or _resp(200,json_data={"ok":True},method="GET"))
    mcp_client.wait_for_mcp_http_ready()
    assert seen.get("headers") is None


def test_readiness_is_bounded(monkeypatch):
    monkeypatch.setenv("MCP_HTTP_READY_CHECK","true"); monkeypatch.setenv("MCP_READY_POLL_SEC","1"); monkeypatch.setenv("MCP_READY_MAX_SEC","2")
    clock=[0.0]; monkeypatch.setattr(mcp_client.time,"monotonic",lambda:clock[0]); monkeypatch.setattr(mcp_client.time,"sleep",lambda s:clock.__setitem__(0,clock[0]+s))
    monkeypatch.setattr(mcp_client.httpx,"get",lambda *a,**k:_resp(429,{"x-render-routing":"hibernate-rate-limited"},method="GET"))
    with pytest.raises(mcp_client.McpNotReadyError): mcp_client.wait_for_mcp_http_ready()


@pytest.mark.parametrize("exc,expected",[(httpx.ConnectError("x"),"not_delivered"),(httpx.ConnectTimeout("x"),"not_delivered"),(_status_error(429,{"x-render-routing":"hibernate-rate-limited"}),"not_delivered"),(_status_error(429),"rejected"),(_status_error(401),"rejected"),(_status_error(500),"ambiguous"),(httpx.ReadTimeout("x"),"ambiguous")])
def test_failure_classification(exc,expected):
    assert mcp_client.classify_mcp_failure(exc)==expected


def test_line_note_flow_returns_verified_message(fake_notes_mcp):
    fake=fake_notes_mcp()
    result=handle_save_note("メモして "+BODY,USER,fake)
    assert result=="メモを保存しました。（保存を確認済み）"
