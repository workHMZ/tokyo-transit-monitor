import json
from datetime import datetime, timezone, timedelta
import time
import requests
from bs4 import BeautifulSoup

# --- 設定 ---
TARGET_URL = 'https://transit.yahoo.co.jp/diainfo/area/4'
BASE_URL = 'https://transit.yahoo.co.jp'

# 東京都内常用路線のホワイトリスト
TOKYO_LINES = {
    # JR東日本（東京都内常用路線）
    "山手線",
    "中央総武線(各停)",
    "中央線(快速)[東京～高尾]",
    "京浜東北根岸線",
    "埼京川越線[羽沢横浜国大～川越]",
    "湘南新宿ライン",
    "上野東京ライン",
    "総武線(快速)[東京～千葉]",
    "京葉線",
    "武蔵野線",
    "常磐線(快速)[品川～取手]",
    "常磐線(各停)",
    "南武線[川崎～立川]",
    "横須賀線",
    
    # 東京メトロ
    "東京メトロ銀座線",
    "東京メトロ丸ノ内線",
    "東京メトロ日比谷線",
    "東京メトロ東西線",
    "東京メトロ千代田線",
    "東京メトロ有楽町線",
    "東京メトロ半蔵門線",
    "東京メトロ南北線",
    "東京メトロ副都心線",
    
    # 都営地下鉄
    "都営浅草線",
    "都営三田線",
    "都営新宿線",
    "都営大江戸線",
    
    # 京王電鉄
    "京王線",
    "京王新線",
    "京王相模原線",
    "京王高尾線",
    "京王井の頭線",
    
    # 小田急電鉄
    "小田急小田原線",
    "小田急江ノ島線",
    "小田急多摩線",
    
    # 東急電鉄
    "東急東横線",
    "東急目黒線",
    "東急田園都市線",
    "東急大井町線",
    "東急多摩川線",
    "東急池上線",
    "東急世田谷線",
    
    # 西武鉄道
    "西武池袋線・秩父線",
    "西武新宿線",
    "西武国分寺線",
    "西武多摩湖線",
    "西武有楽町線",
    "西武拝島線",
    
    # その他東京都内便利な路線
    "日暮里・舎人ライナー",
    "ゆりかもめ線",
    "東京モノレール線",
    "多摩都市モノレール線",
}

# リクエスト用のヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
}


def get_detail_page_info(session, detail_url, line_name, max_retries=3):
    """
    詳細ページから完全な運行情報を取得する。
    
    Returns:
        dict: 路線情報 or None（取得失敗時）
    """
    for attempt in range(max_retries):
        try:
            response = session.get(detail_url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 詳細情報を取得（ページ内の主要テキスト）
            detail_text = ""
            
            # 運行情報のメインテキストを探す
            contents_body = soup.find(id='contents-body')
            if contents_body:
                # pタグから詳細テキストを取得
                for p in contents_body.find_all('p'):
                    text = p.get_text(strip=True)
                    # 意味のある長さのテキストで、路線登録などのUIテキストを除外
                    if len(text) > 20 and '路線を登録' not in text and '迂回ルート' not in text:
                        detail_text = text
                        break
            
            # 状態ラベルを取得
            status = "運転状況"
            status_elem = soup.find(class_='labelStatus')
            if status_elem:
                status = status_elem.get_text(strip=True) or status
            
            if detail_text:
                return {
                    "line": line_name,
                    "status": status,
                    "detail": detail_text,
                    "url": detail_url
                }
            else:
                print(f"  ⚠️ 詳細テキストが見つかりません: {line_name}")
                return None
                
        except requests.exceptions.Timeout:
            print(f"  ⚠️ タイムアウト ({attempt + 1}/{max_retries}): {line_name}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None
        except requests.exceptions.RequestException as e:
            print(f"  ❌ リクエストエラー: {line_name} - {e}")
            return None
        except Exception as e:
            print(f"  ❌ エラー: {line_name} - {e}")
            return None
    
    return None


def scrape_transit_data():
    """
    交通情報をスクレイピングし、東京都内の路線情報のリストを返す。
    """
    print("交通情報を取得中...")
    scraped_data = []
    
    try:
        # セッションを使用して接続を再利用
        session = requests.Session()
        
        print(f"URL: {TARGET_URL} から最新の運行情報を取得中...")
        response = session.get(TARGET_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        print("✅ 主要コンテンツの取得完了。データ解析を開始します。")
        
        # 現在運行情報のある路線のリンクを収集
        troubled_line_links = {}
        
        # elmTblLstLine テーブル内のリンクを取得
        table = soup.find(class_='elmTblLstLine')
        if table:
            for link in table.find_all('a'):
                line_name = link.get_text(strip=True)
                href = link.get('href')
                
                if line_name and href and line_name in TOKYO_LINES:
                    # 相対URLを絶対URLに変換
                    if href.startswith('/'):
                        href = BASE_URL + href
                    troubled_line_links[line_name] = href
        
        if not troubled_line_links:
            print("✅ 東京都内の路線で運行情報のある路線はありません。")
            return []
        
        print(f"\n📋 運行情報のある東京都内路線: {len(troubled_line_links)}件")
        for name in troubled_line_links:
            print(f"  - {name}")
        
        # 各路線の詳細ページから完全な情報を取得
        print("\n📖 詳細情報を取得中...")
        for line_name, detail_url in troubled_line_links.items():
            print(f"  取得中: {line_name}")
            result = get_detail_page_info(session, detail_url, line_name)
            if result:
                scraped_data.append(result)
                print(f"  ✅ 取得完了: {line_name}")
            else:
                # 詳細取得に失敗しても、基本情報は記録
                scraped_data.append({
                    "line": line_name,
                    "status": "運転状況",
                    "detail": "詳細情報の取得に失敗しました。",
                    "url": detail_url
                })
            
            # サーバー負荷軽減のため少し待機
            time.sleep(0.3)
        
        return scraped_data

    except requests.exceptions.RequestException as e:
        print(f"リクエスト中にエラーが発生しました: {e}")
        return None
    except Exception as e:
        print(f"処理中に予期せぬエラーが発生しました: {e}")
        return None


if __name__ == '__main__':
    # データをスクレイピング
    all_lines_data = scrape_transit_data()
    
    # JSON出力処理
    if all_lines_data is not None:
        # 最終的なJSON構造を作成 (JST時間を使用)
        JST = timezone(timedelta(hours=9))
        output_json = {
            "update_time": datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S'),
            "data_source": TARGET_URL,
            "monitored_lines_count": len(TOKYO_LINES),
            "issue_count": len(all_lines_data),
            "status": "issues_found" if all_lines_data else "all_clear",
            "issues": all_lines_data
        }
        
        # JSONを整形してプリント
        print("\n--- JSON Output ---")
        print(json.dumps(output_json, ensure_ascii=False, indent=4))
        
    else:
        print("\n❌ 運行情報の取得に失敗しました。")