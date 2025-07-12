# Tokyo Transit Scraper

**[English](#tokyo-transit-scraper) | [日本語](#東京交通情報スクレイパー-日本語)**

A Python-based web scraper that collects real-time train operation information for Tokyo area railways, designed to run on GitHub Actions with automatic notifications.

## Features

- Scrapes train delay/suspension information from Yahoo! Japan Transit
- Filters for Tokyo metropolitan area lines only (JR, Tokyo Metro, Toei, private railways)
- Outputs structured JSON data
- Automatic GitHub Pages deployment for web dashboard
- Synology Chat notifications
- Scheduled runs (8:00 AM and 5:30 PM JST)

## Project Structure

```
.
├── app.py                  # Main scraper script
├── index.html              # Web dashboard (GitHub Pages)
├── transit_data.json       # Scraped data (auto-generated)
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container configuration
└── .github/workflows/
    ├── run-scraper.yml     # Scraper + notification workflow
    ├── ci.yml              # Docker image build workflow
    ├── cd.yml              # Azure VM deployment workflow
    ├── backup-databases.yml # Database backup workflow
    └── start-pdf-server.yml # PDF server workflow
```

## Monitored Railway Lines

The scraper monitors the following Tokyo area lines:

| Category | Lines |
|----------|-------|
| JR East | Yamanote, Chuo-Sobu Local, Chuo Rapid, Keihin-Tohoku, Saikyo-Kawagoe, Shonan-Shinjuku, Ueno-Tokyo, Sobu Rapid, Keiyo, Musashino, Joban Rapid/Local, Nambu, Yokosuka |
| Tokyo Metro | Ginza, Marunouchi, Hibiya, Tozai, Chiyoda, Yurakucho, Hanzomon, Namboku, Fukutoshin |
| Toei Subway | Asakusa, Mita, Shinjuku, Oedo |
| Keio | Main, New, Sagamihara, Takao, Inokashira |
| Odakyu | Odawara, Enoshima, Tama |
| Tokyu | Toyoko, Meguro, Den-en-toshi, Oimachi, Tamagawa, Ikegami, Setagaya |
| Seibu | Ikebukuro/Chichibu, Shinjuku, Kokubunji, Tamako, Yurakucho, Haijima |
| Other | Nippori-Toneri Liner, Yurikamome, Tokyo Monorail, Tama Monorail |

## Usage

### Local Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Run scraper
python app.py
```

### Output Example

```json
{
    "update_time": "2026-02-08 12:00:00",
    "data_source": "https://transit.yahoo.co.jp/diainfo/area/4",
    "monitored_lines_count": 45,
    "issue_count": 2,
    "status": "issues_found",
    "issues": [
        {
            "line": "Chuo-Sobu Line (Local)",
            "status": "Delays",
            "detail": "Due to overhead wire freezing near Mitaka Station...",
            "url": "https://transit.yahoo.co.jp/diainfo/40/0"
        }
    ]
}
```

## GitHub Actions Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| Run Scraper | 8:00 AM, 5:30 PM JST | Scrape transit data, update GitHub Pages, send Synology Chat notification |
| CI Build | On push to main | Build multi-arch Docker image, push to Docker Hub |
| CD Deploy | Manual | Deploy scraper to Azure VM |
| Database Backup | Monday 4:00 AM JST | Backup PostgreSQL databases to Azure Blob Storage |

## Required Secrets

For GitHub Actions workflows to function, configure the following secrets:

```
SYNOLOGY_CHAT_WEBHOOK          # Synology Chat incoming webhook URL
DOCKERHUB_USERNAME             # Docker Hub username
DOCKERHUB_TOKEN                # Docker Hub access token
AZURE_CREDENTIALS              # Azure service principal credentials
SSH_PRIVATE_KEY                # SSH key for Azure VM
AZURE_STORAGE_CONNECTION_STRING # Azure Blob Storage connection string
NEON_LOBECHAT_DB_URL           # Neon database connection URL
SUPABASE_VAULTWARDEN_DB_URL    # Supabase database connection URL
```

## Web Dashboard

The `index.html` file provides a simple web dashboard that displays the latest transit information. It is designed to be embedded in Glance or similar dashboard applications.

Features:
- Dark/Light theme auto-detection
- Responsive design
- Click to expand line details
- Auto-refresh every 5 minutes

## Technologies

- Python 3.11+
- Requests + BeautifulSoup4
- GitHub Actions
- GitHub Pages
- Docker (multi-arch: amd64/arm64)
- Azure Blob Storage


---

# 東京交通情報スクレイパー (日本語)

Yahoo!路線情報から東京圏の鉄道運行情報をリアルタイムで取得するPythonスクレイパーです。GitHub Actionsで定期実行し、自動通知を行います。

## 機能

- Yahoo!路線情報から遅延・運休情報を取得
- 東京都内の路線のみをフィルタリング（JR、東京メトロ、都営、私鉄）
- 構造化されたJSON形式で出力
- GitHub Pagesへの自動デプロイ（Webダッシュボード）
- Synology Chat通知
- 定期実行（毎日 8:00、17:30 JST）

## 監視対象路線

| カテゴリ | 路線 |
|----------|------|
| JR東日本 | 山手線、中央総武線(各停)、中央線(快速)、京浜東北根岸線、埼京川越線、湘南新宿ライン、上野東京ライン、総武線(快速)、京葉線、武蔵野線、常磐線(快速/各停)、南武線、横須賀線 |
| 東京メトロ | 銀座線、丸ノ内線、日比谷線、東西線、千代田線、有楽町線、半蔵門線、南北線、副都心線 |
| 都営地下鉄 | 浅草線、三田線、新宿線、大江戸線 |
| 京王電鉄 | 京王線、京王新線、相模原線、高尾線、井の頭線 |
| 小田急電鉄 | 小田原線、江ノ島線、多摩線 |
| 東急電鉄 | 東横線、目黒線、田園都市線、大井町線、多摩川線、池上線、世田谷線 |
| 西武鉄道 | 池袋線・秩父線、新宿線、国分寺線、多摩湖線、有楽町線、拝島線 |
| その他 | 日暮里・舎人ライナー、ゆりかもめ線、東京モノレール線、多摩都市モノレール線 |

## 使用方法

```bash
# 仮想環境を作成
python -m venv .venv
source .venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt

# スクレイパーを実行
python app.py
```

## GitHub Actions ワークフロー

| ワークフロー | スケジュール | 説明 |
|-------------|-------------|------|
| Run Scraper | 8:00、17:30 JST | 交通情報を取得し、GitHub Pages更新、Synology Chat通知 |
| CI Build | mainへのpush時 | マルチアーチDockerイメージをビルド、Docker Hubへプッシュ |
| CD Deploy | 手動 | Azure VMにデプロイ |
| Database Backup | 毎週月曜 4:00 JST | PostgreSQLデータベースをAzure Blobにバックアップ |

## Webダッシュボード

`index.html` は最新の交通情報を表示するシンプルなWebダッシュボードです。Glanceなどのダッシュボードアプリに埋め込んで使用できます。

機能:
- ダーク/ライトテーマ自動検出
- レスポンシブデザイン
- クリックで詳細を展開
- 5分ごとに自動更新

## 使用技術

- Python 3.11+
- Requests + BeautifulSoup4
- GitHub Actions / GitHub Pages
- Docker (マルチアーチ: amd64/arm64)
- Azure Blob Storage
