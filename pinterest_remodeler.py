import sys, io, os, time, json, re, pickle, requests, logging
from pathlib import Path
from googleapiclient.discovery import build

# [1] 설정 (마스터님의 환경에 맞춤)
BASE_DIR = Path(__file__).parent
LINKS_DB_FILE = BASE_DIR / "20_Meta" / "published_links.json"
TOKEN_FILE = BASE_DIR / "token.pickle"
BLOG_ID = "2812259517039331714"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# [2] 구글 인증 함수 (이게 있어야 에러가 안 납니다)
def get_blogger_service():
    if not TOKEN_FILE.exists():
        logging.error("❌ token.pickle이 없습니다. master_hq.py를 먼저 실행해 인증하세요.")
        return None
    with open(TOKEN_FILE, 'rb') as f:
        creds = pickle.load(f)
    return build('blogger', 'v3', credentials=creds)

# [3] 핀터레스트용 세로 이미지 생성 함수 (1000x1500)
def get_remodel_image(topic):
    img_desc = (f"Cinematic vertical photography, {topic} molecular structure, "
                f"minimalist scientific 3D render, soft natural lighting, "
                f"high-end medical journal aesthetic, 8k, highly detailed")
    poll_url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(img_desc)}?width=1000&height=1500&nologo=true"
    
    # [🚨 v5.2 개조] 타임아웃 해결을 위한 3회 재시도 로직
    for i in range(3):
        try:
            logging.info(f"    🎨 이미지 생성 시도 중... ({i+1}/3)")
            # 기다리는 시간을 120초로 늘려 3060이 일할 시간을 충분히 줍니다.
            r = requests.get(poll_url, timeout=120)
            if r.status_code == 200:
                return poll_url
        except Exception as e:
            logging.warning(f"    ⚠️ {i+1}회차 시도 실패 (타임아웃 등): {e}")
            if i < 2: 
                time.sleep(5) # 실패하면 5초 쉬었다가 다시 시도
                
    logging.error(f"    ❌ 3회 시도 모두 실패: {topic[:30]}")
    return None

# [4] 제목으로 포스트 ID 찾아내는 함수 (마스터님의 JSON에 ID가 없으므로 필수!)
def find_post_id_by_title(svc, title):
    try:
        # 블로그의 최근 글 50개를 가져와서 제목 비교
        posts = svc.posts().list(blogId=BLOG_ID, maxResults=50).execute()
        for p in posts.get('items', []):
            if p['title'].strip() == title.strip():
                return p['id']
    except Exception as e:
        logging.error(f"    ❌ ID 검색 실패: {e}")
    return None

# [5] 메인 실행 로직
def remodel_past_posts():
    logging.info("🚀 과거 포스팅 핀터레스트 리모델링(세로 이미지 삽입) 시작")
    
    if not LINKS_DB_FILE.exists():
        logging.error(f"❌ 파일을 찾을 수 없습니다: {LINKS_DB_FILE}")
        return

    db = json.loads(LINKS_DB_FILE.read_text(encoding='utf-8'))
    svc = get_blogger_service()
    if not svc: return

    for entry in db:
        title = entry.get('title')
        topic = entry.get('topic', title)
        
        logging.info(f"🔎 작업 대상: {title}")
        
        # 1. 포스트 ID 찾기
        post_id = find_post_id_by_title(svc, title)
        if not post_id:
            logging.warning(f"⚠️ '{title}'의 ID를 블로그에서 찾을 수 없어 건너뜁니다.")
            continue

        # 2. 이미지 생성
        new_img_url = get_remodel_image(topic)
        
        if new_img_url:
            # 3. 기존 글 내용 가져오기
            post = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
            content = post['content']

            # 이미 리모델링 되었는지 확인 (중복 삽입 방지)
            if "Pinterest Infographic" in content:
                logging.info(f"✅ 이미 리모델링된 글입니다: {title}")
                continue

            # 4. 본문 맨 윗줄에 새 이미지 삽입
            new_img_html = f'<div style="display:none;"><img src="{new_img_url}" alt="{title} Optimization Strategy"></div>'
            updated_content = new_img_html + content

            # 5. 블로거 업데이트 (Patch)
            svc.posts().patch(blogId=BLOG_ID, postId=post_id, body={"content": updated_content}).execute()
            logging.info(f"✨ 업데이트 완료: {title}")
            
            # 3060 GPU 휴식 및 API 제한 준수
            time.sleep(10) 

    logging.info("🎊 모든 과거 포스팅 리모델링 완료!")

if __name__ == "__main__":
    remodel_past_posts()