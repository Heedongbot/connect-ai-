"""
NutriStack Lab — Morning Report v1.0
매일 06:50 → Discord로 GA4 + Search Console 일일 보고
"""

import json
import logging
import schedule
import time
from pathlib import Path
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Metric, Dimension, OrderBy
)
import pickle
import requests

# ============================================================
# 설정
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('morning_report.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR = Path(__file__).parent
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
TOKEN_PICKLE = BASE_DIR / "morning_report_token.pickle"
CONFIG_FILE = BASE_DIR / "config.json"

# ★ 여기에 본인 GA4 Property ID 입력 (숫자만, 예: 123456789)
GA4_PROPERTY_ID = "527664358"

# ★ 여기에 Search Console 사이트 URL 입력 (예: https://www.nutristacklab.com/)
SEARCH_CONSOLE_SITE = "sc-domain:nutristacklab.com"

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
]


# ============================================================
# 인증
# ============================================================
def get_credentials():
    creds = None
    if TOKEN_PICKLE.exists():
        with open(TOKEN_PICKLE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logging.info("⏳ 토큰 갱신 중...")
                creds.refresh(Request())
            except Exception as e:
                logging.warning(f"❌ 토큰 갱신 실패 (재인증 필요): {e}")
                if TOKEN_PICKLE.exists():
                    TOKEN_PICKLE.unlink()
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        with open(TOKEN_PICKLE, "wb") as f:
            pickle.dump(creds, f)
    return creds


# ============================================================
# GA4 데이터 수집
# ============================================================
def get_ga4_data(creds):
    try:
        client = BetaAnalyticsDataClient(credentials=creds)

        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date="7daysAgo", end_date="today")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="activeUsers"),
            ],
        )
        response = client.run_report(request)
        total_sessions = int(response.rows[0].metric_values[0].value)
        total_users = int(response.rows[0].metric_values[1].value)

        # TOP 3 페이지
        page_request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date="7daysAgo", end_date="today")],
            dimensions=[Dimension(name="pagePath")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=3,
        )
        page_response = client.run_report(page_request)
        top_pages = [
            (row.dimension_values[0].value, int(row.metric_values[0].value))
            for row in page_response.rows
        ]

        return {
            "sessions": total_sessions,
            "users": total_users,
            "top_pages": top_pages,
        }
    except Exception as e:
        logging.error(f"GA4 오류: {e}")
        return None


# ============================================================
# Search Console 데이터 수집
# ============================================================
def get_search_console_data(creds):
    try:
        service = build("searchconsole", "v1", credentials=creds)

        end_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        # 전체 클릭/노출
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "type": "web",
        }
        res = service.searchanalytics().query(
            siteUrl=SEARCH_CONSOLE_SITE, body=body
        ).execute()
        total_clicks = res.get("rows", [{}])[0].get("clicks", 0) if res.get("rows") else 0
        total_impressions = res.get("rows", [{}])[0].get("impressions", 0) if res.get("rows") else 0

        # TOP 검색어
        kw_body = {
            "startDate": start_date,
            "endDate": end_date,
            "type": "web",
            "dimensions": ["query"],
            "rowLimit": 5,
        }
        kw_res = service.searchanalytics().query(
            siteUrl=SEARCH_CONSOLE_SITE, body=kw_body
        ).execute()
        top_queries = [
            {
                "query": row["keys"][0],
                "clicks": int(row["clicks"]),
                "ctr": round(row["ctr"] * 100, 1),
            }
            for row in kw_res.get("rows", [])
        ]

        return {
            "clicks": int(total_clicks),
            "impressions": int(total_impressions),
            "top_queries": top_queries,
        }
    except Exception as e:
        logging.error(f"Search Console 오류: {e}")
        return None


# ============================================================
# Discord 보고
# ============================================================
def send_discord_report(ga_data, sc_data):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            webhook_url = json.load(f).get("webhook_url")
        if not webhook_url:
            logging.error("webhook_url 없음")
            return

        today = datetime.now().strftime("%Y-%m-%d (%a)")

        lines = [
            "📊 **NutriStack 일일 보고**",
            "=" * 30,
            f"📅 **날짜:** {today}",
            "",
        ]

        if ga_data:
            lines += [
                "📈 **방문자 현황 (7일):**",
                f"세션: {ga_data['sessions']:,} | 사용자: {ga_data['users']:,}",
                "TOP 페이지:",
            ]
            for path, sess in ga_data["top_pages"]:
                lines.append(f"  - {path}: {sess:,}세션")
            lines.append("")
        else:
            lines.append("📈 방문자 데이터 수집 실패\n")

        if sc_data:
            lines += [
                "🔍 **검색 현황 (7일):**",
                f"클릭: {sc_data['clicks']:,} | 노출: {sc_data['impressions']:,}",
                "TOP 검색어:",
            ]
            for q in sc_data["top_queries"]:
                lines.append(f"  - {q['query']}: {q['clicks']}클릭 (CTR {q['ctr']}%)")
        else:
            lines.append("🔍 검색 데이터 수집 실패")

        message = "\n".join(lines)
        requests.post(webhook_url, json={"content": message})
        logging.info("✅ Discord 보고 전송 완료")

    except Exception as e:
        logging.error(f"Discord 전송 오류: {e}")


# ============================================================
# 메인 작업
# ============================================================
def morning_job():
    logging.info("=" * 50)
    logging.info("⏰ 06:50 아침 보고 시작")
    logging.info("=" * 50)

    creds = get_credentials()
    ga_data = get_ga4_data(creds)
    sc_data = get_search_console_data(creds)
    send_discord_report(ga_data, sc_data)
# 학습 엔진 트리거
    try:
        from learning_engine import run_learning
        run_learning()
        logging.info("🧠 학습 엔진 실행 완료")
    except Exception as e:
        logging.warning(f"학습 엔진 오류: {e}")

def run_scheduler():
    logging.info("🤖 NutriStack Morning Report v1.0 시작")
    logging.info("⏰ 매일 06:50 Discord 자동 보고")
    logging.info("=" * 50)

    schedule.every().day.at("06:50").do(morning_job)
    logging.info(f"⏳ 다음 보고: {schedule.next_run()}")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        logging.info("🧪 즉시 테스트 실행")
        morning_job()
    else:
        run_scheduler()
