"""
NutriStack Lab — Morning Report v1.0
매일 06:50 → Discord로 GA4 + Search Console 일일 보고
"""

import json
import logging
import os
import schedule
import socket
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
        if not response.rows:
            return {"sessions": 0, "users": 0, "top_pages": []}
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
def send_discord_report(ga_data, sc_data, claude_data=None, creds=None):
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

        # ── Claude API 사용량 섹션 ───────────────────────
        lines.append("")
        lines.append("🤖 **Claude API 사용량:**")
        if claude_data:
            today_d = claude_data.get("today")
            month_d = claude_data.get("month_total")
            credits = claude_data.get("credits_remaining")

            if today_d:
                t_in   = today_d.get("input_tokens", 0)
                t_out  = today_d.get("output_tokens", 0)
                t_art  = today_d.get("articles", 0)
                lines.append(f"오늘: 입력 {t_in:,} / 출력 {t_out:,} tok ({t_art}편)")
            else:
                lines.append("오늘: 사용 없음")

            if month_d:
                m_in   = month_d.get("input_tokens", 0)
                m_out  = month_d.get("output_tokens", 0)
                m_art  = month_d.get("articles", 0)
                lines.append(f"이번 달: {m_in:,} / {m_out:,} tok ({m_art}편)")
        else:
            lines.append("사용량 데이터 없음")

        # ── 가이드 진행 현황 ────────────────────────────────
        lines.append("")
        completed, total = _get_guide_progress()
        if completed is not None:
            remaining = total - completed
            bar_filled = int((completed / total) * 10) if total else 0
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            lines.append(f"📋 **가이드 진행 현황:**")
            lines.append(f"  [{bar}] {completed}/{total} 완료 (남은 {remaining}편)")
        else:
            lines.append("📋 **가이드 진행 현황:** 조회 실패")

        # ── GA4 아티클별 성과 섹션 ──────────────────────────
        lines.append("")
        lines.append("📰 **가이드 성과 (GA4 최근 30일):**")
        try:
            ga4_articles = _get_ga4_article_performance(creds)
            if ga4_articles:
                for item in ga4_articles[:5]:
                    bar = "🟢" if item["sessions"] >= 20 else ("🟡" if item["sessions"] >= 5 else "🔴")
                    lines.append(f"  {bar} {item['title'][:35]}... | {item['sessions']}세션 | {item['engagement']:.0%}참여")
            else:
                lines.append("  데이터 없음 (발행 7일 미만 또는 색인 대기 중)")
        except Exception as _ge:
            lines.append(f"  GA4 조회 실패: {_ge}")

        message = "\n".join(lines)
        requests.post(webhook_url, json={"content": message})
        logging.info("✅ Discord 보고 전송 완료")

        # 텔레그램에도 동일 보고 전송
        _send_telegram_report(message)

    except Exception as e:
        logging.error(f"Discord 전송 오류: {e}")


def _send_telegram_report(message: str):
    """텔레그램으로 아침 보고 전송."""
    try:
        tg_config_path = BASE_DIR / "telegram_config.json"
        if not tg_config_path.exists():
            return
        cfg = json.loads(tg_config_path.read_text(encoding="utf-8"))
        bot_token = cfg.get("bot_token")
        channel_id = cfg.get("channel_id")
        if not bot_token or not channel_id:
            return
        # 텔레그램 마크다운용 변환 (* → 기울임 충돌 방지)
        tg_msg = message.replace("**", "*")
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": channel_id,
            "text": tg_msg,
            "parse_mode": "Markdown"
        }, timeout=10)
        logging.info("✅ 텔레그램 보고 전송 완료")
    except Exception as e:
        logging.warning(f"텔레그램 전송 오류: {e}")


# ============================================================
# Claude API 사용량 + 잔액 조회
# ============================================================
def _load_anthropic_key():
    candidates = [BASE_DIR / ".env", BASE_DIR.parent / ".env"]
    for p in candidates:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if key and key != "your_key_here":
                        return key
    return os.environ.get("ANTHROPIC_API_KEY", "")


def get_claude_usage_and_credits():
    """오늘 + 이번 달 토큰 사용량, 잔여 크레딧 조회."""
    result = {
        "today": None,
        "month_total": None,
        "credits_remaining": None,
        "credits_currency": "USD",
    }

    # ── 1. 로컬 누적 로그 읽기 ───────────────────────────
    usage_log = BASE_DIR / "20_Meta" / "api_usage_log.json"
    if usage_log.exists():
        try:
            data  = json.loads(usage_log.read_text(encoding="utf-8"))
            today = datetime.now().strftime("%Y-%m-%d")
            month = datetime.now().strftime("%Y-%m")

            # 오늘
            if today in data:
                result["today"] = data[today]

            # 이번 달 합산
            month_in  = sum(v["input_tokens"]  for k, v in data.items() if k.startswith(month))
            month_out = sum(v["output_tokens"] for k, v in data.items() if k.startswith(month))
            month_cost= sum(v["cost_usd"]      for k, v in data.items() if k.startswith(month))
            month_art = sum(v["articles"]       for k, v in data.items() if k.startswith(month))
            result["month_total"] = {
                "input_tokens": month_in,
                "output_tokens": month_out,
                "cost_usd": round(month_cost, 4),
                "articles": month_art,
            }
        except Exception as e:
            logging.warning(f"사용량 로그 읽기 실패: {e}")

    # ── 2. Anthropic API — 잔여 크레딧 조회 시도 ──────────
    api_key = _load_anthropic_key()
    if api_key:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        # 잔액 엔드포인트 순서대로 시도
        for endpoint in [
            "https://api.anthropic.com/v1/credit_grants",
            "https://api.anthropic.com/v1/organizations/billing/credit_grants",
        ]:
            try:
                r = requests.get(endpoint, headers=headers, timeout=8)
                if r.status_code == 200:
                    body = r.json()
                    if "remaining" in body:
                        result["credits_remaining"] = body["remaining"]
                    elif "credits" in body:
                        result["credits_remaining"] = body["credits"]
                    elif "data" in body and body["data"]:
                        item = body["data"][0]
                        result["credits_remaining"] = item.get("remaining_credits",
                                                     item.get("balance",
                                                     item.get("amount_remaining")))
                    if result["credits_remaining"] is not None:
                        break
            except Exception:
                continue

        # 잔액 조회 실패 시 → 수동 기준선 파일에서 추정 잔액 계산
        if result["credits_remaining"] is None:
            credits_file = BASE_DIR / "20_Meta" / "claude_credits.json"
            if credits_file.exists():
                try:
                    cr = json.loads(credits_file.read_text(encoding="utf-8"))
                    baseline_balance  = float(cr.get("balance_at_update", 0))
                    baseline_date     = cr.get("last_updated", "")
                    # 기준선 날짜 이후 누적 비용 계산
                    usage_log = BASE_DIR / "20_Meta" / "api_usage_log.json"
                    cost_since = 0.0
                    if usage_log.exists():
                        log_data = json.loads(usage_log.read_text(encoding="utf-8"))
                        cost_since = sum(
                            v.get("cost_usd", 0.0)
                            for k, v in log_data.items()
                            if k >= baseline_date
                        )
                    estimated = round(baseline_balance - cost_since, 4)
                    result["credits_remaining"] = max(estimated, 0.0)
                    result["credits_estimated"] = True
                    result["credits_baseline_date"] = baseline_date
                except Exception as e:
                    logging.warning(f"크레딧 추정 실패: {e}")
                    result["credits_note"] = "console.anthropic.com/settings/billing"
            else:
                result["credits_note"] = "console.anthropic.com/settings/billing"

    return result


# ============================================================
# 메인 작업
# ============================================================
def _send_low_credit_alert(credits_remaining):
    """잔여 크레딧 $1 이하 시 텔레그램 긴급 알림."""
    try:
        tg_config_path = BASE_DIR / "telegram_config.json"
        if not tg_config_path.exists():
            return
        cfg = json.loads(tg_config_path.read_text(encoding="utf-8"))
        bot_token  = cfg.get("bot_token")
        channel_id = cfg.get("channel_id")
        if not bot_token or not channel_id:
            return
        message = (
            f"⚠️ *Claude API 크레딧 부족 경고!*\n\n"
            f"💳 잔여 크레딧: *${float(credits_remaining):.2f} USD*\n\n"
            f"파이프라인이 곧 멈출 수 있습니다.\n"
            f"지금 바로 충전해주세요 👇\n"
            f"https://console.anthropic.com/settings/billing"
        )
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": channel_id,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
        logging.warning(f"⚠️ 크레딧 부족 알림 전송: ${float(credits_remaining):.2f}")
    except Exception as e:
        logging.warning(f"크레딧 알림 전송 오류: {e}")


def _get_guide_progress():
    """topic_bank.json에서 comprehensive_guide 완료 수 반환. 목표는 131로 고정."""
    GOAL = 131
    try:
        topic_bank = BASE_DIR / "20_Meta" / "topic_bank.json"
        if not topic_bank.exists():
            return None, GOAL
        data = json.loads(topic_bank.read_text(encoding="utf-8"))
        guides    = [x for x in data if x.get("type") == "comprehensive_guide"]
        completed = sum(1 for x in guides if x.get("status") == "completed")
        return completed, GOAL
    except Exception as e:
        logging.warning(f"가이드 진행 현황 조회 실패: {e}")
        return None, GOAL


def _get_ga4_article_performance(creds):
    """GA4에서 발행된 아티클별 성과를 조회 (세션, 참여율)."""
    try:
        from urllib.parse import urlparse
        client = BetaAnalyticsDataClient(credentials=creds)
        response = client.run_report(RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
            dimensions=[Dimension(name="pagePath")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="engagementRate"),
            ],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=20,
        ))
        # published_links.json과 매핑
        links_file = BASE_DIR / "20_Meta" / "published_links.json"
        if not links_file.exists():
            return []
        db = json.loads(links_file.read_text(encoding="utf-8"))
        path_to_title = {}
        for entry in db:
            url = entry.get("url", "")
            title = entry.get("title", "")
            if url and title:
                path_to_title[urlparse(url).path] = title

        results = []
        for row in response.rows:
            path     = row.dimension_values[0].value
            sessions = int(row.metric_values[0].value)
            engage   = float(row.metric_values[1].value)
            # 현재 live 포스팅에 없는 URL은 제외 (삭제된 포스팅 필터링)
            if path not in path_to_title:
                continue
            title = path_to_title[path]
            if sessions > 0:
                results.append({"title": title, "sessions": sessions, "engagement": engage})
        return results
    except Exception as e:
        logging.warning(f"GA4 아티클 성과 조회 실패: {e}")
        return []


def morning_job():
    # ── 하루 1회만 실행 (재시작해도 중복 방지) ────────────────
    today_str  = datetime.now().strftime('%Y-%m-%d')
    _flag_path = BASE_DIR / "20_Meta" / f"morning_report_{today_str}.flag"
    if _flag_path.exists():
        logging.info(f"  ⏭️ 오늘({today_str}) 보고 이미 완료 — 스킵")
        return
    # 즉시 flag 생성 (중복 실행 방지)
    try:
        _flag_path.parent.mkdir(exist_ok=True)
        _flag_path.touch()
    except Exception:
        pass

    logging.info("=" * 50)
    logging.info("⏰ 07:00 아침 보고 시작")
    logging.info("=" * 50)

    creds = get_credentials()
    ga_data     = get_ga4_data(creds)
    sc_data     = get_search_console_data(creds)
    claude_data = get_claude_usage_and_credits()
    send_discord_report(ga_data, sc_data, claude_data, creds=creds)

    # ── 크레딧 $1 이하 긴급 알림 ───────────────────────────────
    if claude_data:
        remaining = claude_data.get("credits_remaining")
        if remaining is not None:
            try:
                if float(remaining) <= 1.0:
                    _send_low_credit_alert(remaining)
            except Exception:
                pass

    # 학습 엔진 트리거
    try:
        from learning_engine import run_learning
        run_learning()
        logging.info("🧠 학습 엔진 실행 완료")
    except Exception as e:
        logging.warning(f"학습 엔진 오류: {e}")


# 오케스트레이터에서 호출하는 진입점
send_daily_analytics_report = morning_job


def run_scheduler():
    # ── 중복 실행 방지 (포트 19993) ──────────────────────────
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock.bind(('127.0.0.1', 19993))
    except socket.error:
        logging.warning("⚠️ morning_report 이미 실행 중 (포트 19993). 종료합니다.")
        return

    logging.info("🤖 NutriStack Morning Report v1.0 시작")
    logging.info("⏰ 매일 07:00 Discord + 텔레그램 자동 보고")
    logging.info("=" * 50)

    schedule.every().day.at("06:00").do(lambda: __import__('topic_ranker').rank_and_schedule())
    schedule.every().day.at("07:00").do(morning_job)

    # ── 시작 시 오늘 보고 누락 여부 확인 ──────────────────────
    _now = datetime.now()
    if _now.hour >= 7:
        # morning_job 내부에서 flag 체크 → 이미 실행됐으면 자동 스킵
        logging.info(f"  📬 시작 시각 {_now.strftime('%H:%M')} (07:00 이후) → 오늘 보고 확인")
        morning_job()

    logging.info(f"⏳ 다음 정기 보고: {schedule.next_run()}")

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
