import json
import logging
import requests
import os
from pathlib import Path

logger = logging.getLogger(__name__)

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'telegram_config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load telegram_config.json: {e}")
        return None


def _get_guide_progress():
    """topic_bank.json에서 가이드 완료/전체 수 반환."""
    GOAL = 131
    try:
        bank_path = Path(__file__).parent / "20_Meta" / "topic_bank.json"
        if not bank_path.exists():
            return None, GOAL
        data = json.loads(bank_path.read_text(encoding="utf-8"))
        guides    = [x for x in data if x.get("type") == "comprehensive_guide"]
        completed = sum(1 for x in guides if x.get("status") == "completed")
        return completed, GOAL
    except Exception:
        return None, GOAL


def send_publish_notification(title, url, score, word_count, input_tokens, output_tokens):
    """발행 완료 + 가이드 진행 현황 + Claude API 사용량 텔레그램 DM 전송."""
    total_tok = input_tokens + output_tokens

    # 가이드 진행 현황 블록
    completed, goal = _get_guide_progress()
    if completed is not None:
        remaining  = goal - completed
        bar_filled = int((completed / goal) * 10)
        bar        = "█" * bar_filled + "░" * (10 - bar_filled)
        guide_block = (
            f"\n📋 *가이드 진행 현황*\n"
            f"  [{bar}] {completed}/{goal} 완료\n"
            f"  남은 편수: {remaining}편"
        )
    else:
        guide_block = ""

    message = (
        f"🚀 *새 포스팅 발행 완료!*\n\n"
        f"📝 *{title}*\n"
        f"🔗 {url}\n\n"
        f"📊 품질: {score:.0%}  |  {word_count:,} 단어"
        f"{guide_block}\n\n"
        f"🤖 *Claude API 사용량*\n"
        f"  입력: {input_tokens:,} tok\n"
        f"  출력: {output_tokens:,} tok\n"
        f"  합계: {total_tok:,} tok"
    )
    return send_alert(message)

def send_telegram_notification(title, post_url, image_url=None):
    """
    텔레그램 채널로 새 글 발행 알림을 보냅니다.
    """
    config = load_config()
    if not config:
        return False
        
    bot_token = config.get("bot_token")
    channel_id = config.get("channel_id")
    
    if not bot_token or not channel_id:
        logger.error("Telegram config is missing bot_token or channel_id.")
        return False
        
    message = f"🚀 *새로운 포스팅이 발행되었습니다!*\n\n📝 *제목:* {title}\n🔗 *링크:* {post_url}"
    
    try:
        if image_url:
            # 사진과 함께 전송
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            payload = {
                "chat_id": channel_id,
                "photo": image_url,
                "caption": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, json=payload, timeout=10)
        else:
            # 텍스트만 전송
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": channel_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, json=payload, timeout=10)
            
        if response.status_code != 200:
            logger.error(f"Telegram API Error: {response.text}")
        response.raise_for_status()
        logger.info("Successfully sent notification to Telegram.")
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False

def send_alert(message: str) -> bool:
    """시스템 경보 등 자유형식 텍스트를 텔레그램으로 전송."""
    config = load_config()
    if not config:
        return False
    bot_token = config.get("bot_token")
    channel_id = config.get("channel_id")
    if not bot_token or not channel_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        response = requests.post(url, json={
            "chat_id": channel_id,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
        response.raise_for_status()
        logger.info("Alert sent to Telegram.")
        return True
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")
        return False


if __name__ == "__main__":
    # 간단한 테스트 실행
    # 봇이 @NutriStack_Lab 채널에 관리자로 초대되어 있어야 합니다.
    logging.basicConfig(level=logging.INFO)
    send_telegram_notification("텔레그램 연동 테스트", "https://www.nutristacklab.com")
