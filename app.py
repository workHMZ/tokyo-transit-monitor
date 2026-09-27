import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 設定 ---
TARGET_URL = "https://transit.yahoo.co.jp/diainfo/area/4"
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "transit_data.json"
LINES_FILE = BASE_DIR / "lines.json"

# 詳細ページ取得の設定
FETCH_DETAIL_PAGES = True
DETAIL_FETCH_DELAY = 1.0   # 秒。Yahoo! への負荷を避けるための間隔
DETAIL_FETCH_LIMIT = 20    # 1回の実行で詳細ページを取得する最大件数
# 詳細取得全体の時間上限（秒）。大規模障害時は Yahoo! 側も遅くなりがちで、
# 20件 × リトライ込みの最悪ケースが job の timeout-minutes (10分) を超えうる。
# 上限に達したら残りは一覧の要約のまま出力し、Pages の更新を優先する。
DETAIL_FETCH_BUDGET = 120

# 「異常なし」を示す文言。全角/半角の中点ゆらぎに対応するため正規化して判定する
NO_TROUBLE_PATTERN = re.compile(r"(事故.遅延(に関する)?情報はありません|情報はありません)")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}


class TransitParseError(RuntimeError):
    pass


def log(message: str) -> None:
    """進捗ログは stderr へ。stdout は JSON 専用に保つ。"""
    print(message, file=sys.stderr, flush=True)


def load_monitored_lines() -> set[str]:
    """
    監視対象路線を lines.json から読み込む。
    コード変更なしに路線を増減できるよう外部化している。
    """
    try:
        raw = json.loads(LINES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TransitParseError(f"{LINES_FILE.name} が見つかりません。") from exc
    except json.JSONDecodeError as exc:
        raise TransitParseError(f"{LINES_FILE.name} のJSONが不正です: {exc}") from exc

    lines: set[str] = set()
    for key, value in raw.items():
        if key.startswith("_"):  # "_comment" などのメタキーは無視
            continue
        if not isinstance(value, list):
            raise TransitParseError(f"{LINES_FILE.name}: '{key}' は配列である必要があります。")
        lines.update(value)

    if not lines:
        raise TransitParseError(f"{LINES_FILE.name} に監視対象路線が1件もありません。")
    return lines


def make_soup(markup: bytes | str) -> BeautifulSoup:
    """lxml があれば使い、無ければ標準の html.parser にフォールバックする。"""
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception:
        return BeautifulSoup(markup, "html.parser")


def create_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
        # urllib3 の既定は最大6時間。429/503 の Retry-After で job ごと固まらないよう抑える。
        retry_after_max=30,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=2,
        pool_maxsize=2,
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", adapter)
    return session


def collect_page_line_names(soup: BeautifulSoup) -> set[str]:
    """
    ページ上に存在する全路線名を集める。
    ホワイトリストとの差分を取ることで「Yahoo!側の路線名変更」を検知する。
    """
    names = set()
    for link in soup.find_all("a", href=True):
        if "/diainfo/" not in link["href"]:
            continue
        name = link.get_text(" ", strip=True)
        if name:
            names.add(name)
    return names


def parse_trouble_rows(soup: BeautifulSoup, monitored: set[str]) -> list[dict]:
    """
    Yahoo! 路線情報の「現在運行情報のある路線」から
    路線 / 状況 / 詳細を直接取得する。
    """
    trouble_section = soup.find(id="mdStatusTroubleLine")
    if trouble_section is None:
        raise TransitParseError(
            "運行情報セクションが見つかりません。"
            "Yahoo! のHTML構造が変更された可能性があります。"
        )

    issues = []
    parsed_rows = 0
    skipped: list[str] = []

    for row in trouble_section.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        if len(cells) < 3:
            raise TransitParseError("運行情報の行に必要な列がありません。")

        link = cells[0].find("a")
        if link:
            line_name = link.get_text(" ", strip=True)
            detail_url = urljoin(TARGET_URL, link.get("href", ""))
        else:
            line_name = cells[0].get_text(" ", strip=True)
            detail_url = TARGET_URL

        status = cells[1].get_text(" ", strip=True)
        detail = cells[2].get_text(" ", strip=True)

        if not line_name or not status or not detail:
            # Never publish an all-clear result after silently dropping an incident.
            raise TransitParseError(
                f"運行情報の行が不完全です: {line_name or '路線名不明'}"
            )

        parsed_rows += 1

        if line_name not in monitored:
            skipped.append(line_name)
            continue

        issues.append({
            "line": line_name,
            "status": status,
            "detail": detail,
            "detail_truncated": detail.endswith("..."),
            "url": detail_url,
        })

    if parsed_rows == 0:
        # 行が取れない場合、本当に平常なのか構造変更なのかを文言で切り分ける。
        section_text = trouble_section.get_text(" ", strip=True)
        if NO_TROUBLE_PATTERN.search(section_text):
            log("ℹ️  現在、運行情報のある路線はありません。")
            return []
        raise TransitParseError(
            "運行情報は存在しますが、路線情報を解析できませんでした。"
        )

    if skipped:
        log(f"ℹ️  監視対象外のため除外: {len(skipped)}件 -> {', '.join(sorted(set(skipped)))}")

    return issues


def warn_missing_lines(page_lines: set[str], monitored: set[str]) -> list[str]:
    """
    ホワイトリストにあるのにページ上に一切現れない路線を警告する。
    Yahoo! 側の改名を黙って取りこぼすのを防ぐ。
    """
    missing = sorted(monitored - page_lines)
    if missing:
        log("⚠️  以下の監視対象路線がページ上に見つかりません（改名/廃止の可能性）:")
        for name in missing:
            log(f"      - {name}")
    return missing


def parse_detail_page(html: bytes) -> dict | None:
    """Read status and detail together from the same upstream snapshot."""
    soup = make_soup(html)
    status_block = soup.find(id="mdServiceStatus")
    if status_block is None:
        return None
    entries = []
    for dd in status_block.find_all("dd"):
        dt = dd.find_previous_sibling()
        status = dt.get_text(" ", strip=True) if dt and dt.name == "dt" else ""
        detail = dd.get_text(" ", strip=True)
        if not status or not detail:
            return None
        if status == "平常運転" and not NO_TROUBLE_PATTERN.search(detail):
            return None
        entries.append({"status": status, "detail": detail})
    if not entries:
        return None

    # An active incident takes precedence over any normal-service entry.
    active = [entry for entry in entries if entry["status"] != "平常運転"]
    selected = active or entries
    return {
        "status": "・".join(dict.fromkeys(entry["status"] for entry in selected)),
        "detail": " ".join(entry["detail"] for entry in selected),
        "all_clear": not active,
    }


def enrich_with_details(session: requests.Session, issues: list[dict]) -> None:
    """
    一覧ページの詳細文はYahoo!側で「...」に切り詰められている。
    問題のある路線だけ詳細ページを引いて全文に差し替える。
    """
    targets = [i for i in issues if i["url"] != TARGET_URL][:DETAIL_FETCH_LIMIT]
    if not targets:
        return

    log(f"📄 詳細ページから全文を取得中... ({len(targets)}件)")
    deadline = time.monotonic() + DETAIL_FETCH_BUDGET
    for index, issue in enumerate(targets):
        if time.monotonic() >= deadline:
            log(
                f"   ⚠️  時間上限 ({DETAIL_FETCH_BUDGET}秒) に達したため、"
                f"残り{len(targets) - index}件は一覧の要約を使用"
            )
            break
        if index > 0:
            time.sleep(DETAIL_FETCH_DELAY)
        try:
            response = session.get(issue["url"], timeout=(5, 15))
            response.raise_for_status()
            snapshot = parse_detail_page(response.content)
        except requests.RequestException as exc:
            log(f"   ⚠️  {issue['line']}: 詳細取得に失敗（一覧の要約を使用）: {exc}")
            continue

        if snapshot and snapshot["all_clear"]:
            issues.remove(issue)
            log(f"   ℹ️  {issue['line']}: 詳細ページで平常運転への復旧を確認")
        elif snapshot:
            issue["status"] = snapshot["status"]
            issue["detail"] = snapshot["detail"]
            issue["detail_truncated"] = False
        else:
            log(f"   ⚠️  {issue['line']}: 詳細ページを解析できませんでした（一覧の要約を使用）")


def scrape_transit_data(monitored: set[str]) -> tuple[list[dict], list[str]]:
    log(f"URL: {TARGET_URL} から最新の運行情報を取得中...")
    with create_session() as session:
        response = session.get(TARGET_URL, timeout=(5, 15))
        response.raise_for_status()

        soup = make_soup(response.content)
        issues = parse_trouble_rows(soup, monitored)
        missing = warn_missing_lines(collect_page_line_names(soup), monitored)

        if issues and FETCH_DETAIL_PAGES:
            enrich_with_details(session, issues)

    return issues, missing


def build_output(issues: list[dict], monitored: set[str], missing: list[str]) -> dict:
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    return {
        "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "update_time_iso": now.isoformat(timespec="seconds"),
        "data_source": TARGET_URL,
        "monitored_lines_count": len(monitored),
        "unmatched_lines": missing,
        "issue_count": len(issues),
        "status": "issues_found" if issues else "all_clear",
        "issues": issues,
    }


def write_json_atomic(data: dict) -> None:
    """中途半端なJSONが残らないよう、一時ファイルからatomic replace。"""
    temp_file = OUTPUT_FILE.with_suffix(".json.tmp")
    temp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_file.replace(OUTPUT_FILE)
    log(f"✅ {OUTPUT_FILE.name} を更新しました。")


def main() -> int:
    try:
        monitored = load_monitored_lines()
        issues, missing = scrape_transit_data(monitored)
        output = build_output(issues, monitored, missing)
        write_json_atomic(output)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (requests.RequestException, TransitParseError) as exc:
        log(f"❌ 運行情報の取得に失敗しました: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
