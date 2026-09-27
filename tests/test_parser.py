"""
Yahoo! 路線情報のHTML構造が変わったときに、
本番で気づく前にローカルで落ちるようにするための回帰テスト。

fixtures/area4_all_clear.html は実ページから取得したもの。
Yahoo! が改版したら新しいHTMLで差し替えて再実行すること。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> "app.BeautifulSoup":
    return app.make_soup((FIXTURES / name).read_bytes())


@pytest.fixture(scope="module")
def monitored() -> set[str]:
    return app.load_monitored_lines()


# --- ホワイトリスト ---

def test_lines_config_loads(monitored):
    assert len(monitored) == 52
    assert "山手線" in monitored
    assert "東京メトロ千代田線" in monitored


# --- 平常時 ---

def test_all_clear_returns_empty(monitored):
    assert app.parse_trouble_rows(load("area4_all_clear.html"), monitored) == []


def test_all_clear_page_contains_monitored_lines(monitored):
    """実ページに監視対象路線が載っていること = ホワイトリストの表記が正しいこと。"""
    page_lines = app.collect_page_line_names(load("area4_all_clear.html"))
    missing = monitored - page_lines
    assert not missing, f"ページ上に存在しない監視対象路線: {sorted(missing)}"


# --- 異常時 ---

def test_trouble_rows_parsed(monitored):
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)
    assert [i["line"] for i in issues] == ["京葉線", "横須賀線", "東京メトロ千代田線"]
    assert issues[0]["status"] == "運転見合わせ"
    assert issues[0]["url"] == "https://transit.yahoo.co.jp/diainfo/69/0"


def test_unmonitored_line_is_filtered(monitored):
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)
    assert "東海道新幹線" not in [i["line"] for i in issues]


def test_truncation_is_flagged(monitored):
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)
    assert all(i["detail_truncated"] for i in issues)


# --- 構造変更の検知 ---

def test_missing_section_raises(monitored):
    soup = app.make_soup(b"<html><body><p>hello</p></body></html>")
    with pytest.raises(app.TransitParseError):
        app.parse_trouble_rows(soup, monitored)


def test_broken_table_raises_instead_of_false_all_clear(monitored):
    """行が取れず「ありません」文言も無い場合、all_clear と誤判定してはいけない。"""
    with pytest.raises(app.TransitParseError):
        app.parse_trouble_rows(load("area4_broken.html"), monitored)


@pytest.mark.parametrize("bad_cells", [
    "<td>京葉線</td><td>列車遅延</td><td></td>",
    "<td>京葉線</td><td></td><td>遅延情報</td>",
    "<td>京葉線</td><td>列車遅延</td>",
    "<td></td><td>列車遅延</td><td>遅延情報</td>",
])
def test_partial_parse_cannot_publish_all_clear(monitored, bad_cells):
    html = (
        '<div id="mdStatusTroubleLine"><table>'
        f'<tr>{bad_cells}</tr>'
        '<tr><td>東海道新幹線</td><td>列車遅延</td><td>遅延情報</td></tr>'
        '</table></div>'
    )
    with pytest.raises(app.TransitParseError):
        app.parse_trouble_rows(app.make_soup(html), monitored)


def test_renamed_line_is_reported():
    page_lines = app.collect_page_line_names(load("area4_all_clear.html"))
    missing = app.warn_missing_lines(page_lines, {"山手線", "存在しない線"})
    assert missing == ["存在しない線"]


# --- 詳細ページ ---

def test_detail_page_full_text():
    result = app.parse_detail_page((FIXTURES / "detail_trouble.html").read_bytes())
    assert result is not None
    assert result["status"] == "運転見合わせ"
    assert result["all_clear"] is False
    assert not result["detail"].endswith("...")
    assert "運転再開見込みは8時30分頃です" in result["detail"]


def test_detail_page_normal():
    result = app.parse_detail_page((FIXTURES / "detail_normal.html").read_bytes())
    assert result is not None and "情報はありません" in result["detail"]
    assert result["all_clear"] is True


def test_detail_page_unparseable_returns_none():
    assert app.parse_detail_page(b"<html><body>nope</body></html>") is None


# --- 出力形式 ---

def test_build_output_shape(monitored):
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)
    out = app.build_output(issues, monitored, [])
    assert out["status"] == "issues_found"
    assert out["issue_count"] == 3
    assert out["monitored_lines_count"] == 52
    assert out["update_time_iso"].endswith("+09:00")


def test_build_output_all_clear(monitored):
    out = app.build_output([], monitored, [])
    assert out["status"] == "all_clear"
    assert out["issue_count"] == 0


class _FakeResponse:
    content = (FIXTURES / "detail_trouble.html").read_bytes()

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        return _FakeResponse()


def test_enrich_stops_at_time_budget(monitored, monkeypatch):
    """詳細取得が時間上限を超えたら打ち切り、残りは一覧の要約のまま返すこと。"""
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)
    clock = iter([0.0, 0.0, app.DETAIL_FETCH_BUDGET + 1, app.DETAIL_FETCH_BUDGET + 2])
    monkeypatch.setattr(app.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(app.time, "sleep", lambda _: None)

    session = _FakeSession()
    app.enrich_with_details(session, issues)

    assert session.calls == 1
    assert issues[0]["detail_truncated"] is False
    assert all(i["detail_truncated"] for i in issues[1:])


def test_session_caps_retry_after():
    """Retry-After が長大でも job の timeout 内に収まる上限が設定されていること。"""
    with app.create_session() as session:
        retry = session.get_adapter(app.TARGET_URL).max_retries
    assert retry.retry_after_max <= 60


def test_detail_page_multiple_dd():
    """1路線に複数の dd がある場合、全て結合されること。"""
    html = (
        b'<div id="mdServiceStatus"><dl>'
        b'<dt>\xe9\x81\x8b\xe8\xbb\xa2\xe8\xa6\x8b\xe5\x90\x88\xe3\x82\x8f\xe3\x81\x9b</dt>'
        b'<dd class="trouble"><p>AAA</p></dd>'
        b'<dt>\xe9\x81\x8b\xe4\xbc\x91</dt>'
        b'<dd class="trouble"><p>BBB</p></dd>'
        b'</dl></div>'
    )
    result = app.parse_detail_page(html)
    assert "AAA" in result["detail"] and "BBB" in result["detail"]
    assert result["status"] == "運転見合わせ・運休"


def test_enrich_removes_recovered_line_and_updates_counts(monitored, monkeypatch):
    monkeypatch.setattr(_FakeResponse, "content", (FIXTURES / "detail_normal.html").read_bytes())
    monkeypatch.setattr(app.time, "sleep", lambda _: None)
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)
    session = _FakeSession()
    app.enrich_with_details(session, issues)
    out = app.build_output(issues, monitored, [])
    assert session.calls == 3
    assert out["issues"] == []
    assert out["issue_count"] == 0
    assert out["status"] == "all_clear"


def test_enrich_updates_status_with_detail(monitored):
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)[1:2]
    assert issues[0]["status"] == "列車遅延"
    app.enrich_with_details(_FakeSession(), issues)
    assert issues[0]["status"] == "運転見合わせ"
    assert "運転を見合わせています" in issues[0]["detail"]


@pytest.mark.parametrize("markup", [
    '<dd class="normal">情報はありません</dd>',
    '<dt>平常運転</dt><dd></dd>',
    '<dt>平常運転</dt><dd>不明な内容</dd>',
    '<dt>運転見合わせ</dt><dd>運転見合わせ中</dd><dt>運休</dt><dd></dd>',
])
def test_incomplete_detail_preserves_area_snapshot(monitored, monkeypatch, markup):
    monkeypatch.setattr(_FakeResponse, "content", f'<div id="mdServiceStatus"><dl>{markup}</dl></div>'.encode())
    issues = app.parse_trouble_rows(load("area4_trouble.html"), monitored)[:1]
    original = issues[0].copy()
    app.enrich_with_details(_FakeSession(), issues)
    assert issues == [original]


def test_active_detail_takes_precedence_over_normal():
    html = (
        '<div id="mdServiceStatus"><dl>'
        '<dt>平常運転</dt><dd>事故・遅延情報はありません</dd>'
        '<dt>運休</dt><dd>一部列車は運休します</dd>'
        '</dl></div>'
    )
    result = app.parse_detail_page(html.encode())
    assert result == {"status": "運休", "detail": "一部列車は運休します", "all_clear": False}
