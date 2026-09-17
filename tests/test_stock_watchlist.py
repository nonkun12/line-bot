import db
import stock_watchlist


def test_watchlist_add_remove_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "watch.db"))
    db.init_db()

    assert stock_watchlist.add("u", "7203")
    assert not stock_watchlist.add("u", "7203")
    assert stock_watchlist.add("u", "AAPL", "Apple")
    watches = stock_watchlist.list_all("u")
    assert [item["ticker"] for item in watches] == ["7203.T", "AAPL"]
    assert watches[1]["label"] == "Apple"

    assert stock_watchlist.remove("u", "7203")
    assert not stock_watchlist.remove("u", "7203")
    assert [item["ticker"] for item in stock_watchlist.list_all("u")] == ["AAPL"]
