import json
import logging
import requests
import os

logger = logging.getLogger(__name__)

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'telegram_config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load telegram_config.json: {e}")
        return None

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

if __name__ == "__main__":
    # 간단한 테스트 실행
    # 봇이 @NutriStack_Lab 채널에 관리자로 초대되어 있어야 합니다.
    logging.basicConfig(level=logging.INFO)
    send_telegram_notification("텔레그램 연동 테스트", "https://www.nutristacklab.com")
