import os
import json
import logging
import requests
from pathlib import Path

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

def post_to_twitter(title, url, image_url_or_path=None, tweet_text=None):
    """
    트위터(X)에 블로그 포스팅 소식을 자동 업로드합니다.
    """
    try:
        import tweepy
    except ImportError:
        logging.error("❌ tweepy 라이브러리가 설치되어 있지 않습니다. 'pip install tweepy'를 실행해 주세요.")
        return False

    # 설정 로드
    config_path = Path(__file__).parent / "twitter_config.json"
    if not config_path.exists():
        logging.error("❌ twitter_config.json 파일이 없습니다.")
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    try:
        # 1. 인증 설정 (OAuth 1.0a - V2 API 및 미디어 업로드용)
        auth = tweepy.OAuth1UserHandler(
            config['api_key'], config['api_secret'],
            config['access_token'], config['access_token_secret']
        )
        api_v1 = tweepy.API(auth) # 미디어 업로드용 (V1.1)
        client_v2 = tweepy.Client( # 트윗 작성용 (V2)
            bearer_token=config.get('bearer_token'),
            consumer_key=config['api_key'],
            consumer_secret=config['api_secret'],
            access_token=config['access_token'],
            access_token_secret=config['access_token_secret']
        )

        media_ids = []
        
        # 2. 이미지 처리 (있는 경우)
        if image_url_or_path:
            img_path = None
            if str(image_url_or_path).startswith("http"):
                # URL인 경우 다운로드
                logging.info(f"  📷 트위터용 이미지 다운로드 중: {image_url_or_path}")
                temp_path = Path(__file__).parent / "temp_twitter_img.png"
                r = requests.get(image_url_or_path, stream=True)
                if r.status_code == 200:
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)
                    img_path = temp_path
            else:
                img_path = Path(image_url_or_path)

            if img_path and img_path.exists():
                # 미디어 업로드 (V1.1 API 사용)
                media = api_v1.media_upload(filename=str(img_path))
                media_ids.append(media.media_id)
                logging.info(f"  ✅ 트위터 미디어 업로드 성공 (ID: {media.media_id})")
                
                # 임시 파일 삭제
                if "temp_twitter_img.png" in str(img_path):
                    os.remove(img_path)

        # 3. 트윗 내용 구성
        # 전달받은 tweet_text가 있으면 사용, 없으면 기본값 사용
        if not tweet_text:
            tweet_text = f"🆕 Nordic Health Update\n\n{title}\n\nRead more at: {url}\n\n#NutriStackLab #NordicHealth #Longevity"
        
        # 4. 트윗 게시 (V2 API 사용)
        response = client_v2.create_tweet(
            text=tweet_text,
            media_ids=media_ids if media_ids else None
        )
        
        tweet_id = response.data['id']
        logging.info(f"  ✅ 트위터 포스팅 성공! (Tweet ID: {tweet_id})")
        return True

    except Exception as e:
        logging.error(f"  ❌ 트위터 포스팅 오류: {e}")
        return False

if __name__ == "__main__":
    # 테스트 코드
    import sys
    if len(sys.argv) > 1:
        test_title = sys.argv[1]
        test_url = "https://www.nutristacklab.com"
        post_to_twitter(test_title, test_url)
