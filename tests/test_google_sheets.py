from core.google_sheets import GoogleSheetsWriteDenied, append_rows


def test_append_rows_requires_explicit_write_request():
    try:
        append_rows([["example"]], write_requested=False)
    except GoogleSheetsWriteDenied:
        return
    raise AssertionError("Sheets writes must require an explicit request")
