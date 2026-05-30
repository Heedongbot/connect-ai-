"""
기존 포스트 썸네일 일괄 수정
- base64만 있는 포스트 앞에 Pollinations 숨김 img 삽입
"""
import json, re, time, pickle, sys
from pathlib import Path
from urllib.parse import quote
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

BLOG_ID    = "2812259517039331714"
TOKEN_FILE = Path(__file__).parent / "token.pickle"
LINKS_FILE = Path(__file__).parent / "20_Meta" / "published_links.json"

IMAGE_STYLE_DB = {
    "magnesium":    "magnesium supplement capsules beside a glass of water and almonds on a wooden table",
    "vitamin d":    "vitamin D supplement bottle next to eggs and a sunny window, morning kitchen",
    "vitamin d3":   "vitamin D3 softgel beside salmon and leafy greens, natural light",
    "vitamin k":    "vitamin K supplement beside leafy greens and eggs on a kitchen counter",
    "omega":        "omega-3 fish oil capsules beside sardines and walnuts, casual kitchen table",
    "omega-3":      "fish oil supplement capsule next to sardines and walnuts, kitchen table",
    "zinc":         "zinc supplement tablet beside pumpkin seeds and a snack on a wooden tray",
    "l-theanine":   "L-theanine capsule beside a cup of green tea and a book, calm morning desk",
    "theanine":     "theanine supplement beside a warm mug of tea and a journal on a quiet desk",
    "creatine":     "creatine powder scoop beside a shaker bottle and a banana on a gym bag",
    "lion":         "lion's mane mushroom supplement beside a cup of coffee and morning notes",
    "bacopa":       "bacopa supplement bottle beside a glass of water and study notes on a desk",
    "collagen":     "collagen powder beside a bowl of yogurt and berries on a kitchen counter",
    "vitamin c":    "vitamin C capsule beside a sliced orange and a glass of water, bright kitchen",
    "quercetin":    "quercetin supplement beside apple slices and berries on a breakfast plate",
    "coq10":        "CoQ10 softgel beside a small piece of fatty fish and water, lunch setting",
    "nmn":          "NMN supplement bottle beside a glass of water and pill organizer, morning",
    "resveratrol":  "resveratrol capsule beside a bowl of dark berries and a light breakfast",
    "berberine":    "berberine supplement beside a plate of vegetables and rice, healthy meal",
    "probiotics":   "probiotic capsule beside a bowl of greek yogurt and granola on a table",
    "glutathione":  "glutathione supplement bottle beside green tea and avocado toast, morning",
    "ashwagandha":  "ashwagandha capsule beside a mug of warm milk and a journal, calm evening",
    "selenium":     "selenium supplement beside Brazil nuts and a glass of water on a table",
    "pqq":          "PQQ supplement bottle beside blueberries and dark chocolate on a desk",
    "boron":        "boron supplement beside avocado and leafy greens on a kitchen counter",
    "glucosamine":  "glucosamine supplement beside a knee brace and a glass of water",
}

def get_creds():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def get_thumb_url(topic: str) -> str:
    tl = topic.lower()
    desc = next((v for k, v in IMAGE_STYLE_DB.items() if k in tl),
                f"health supplement on a wooden kitchen counter, natural morning light")
    return (f"https://image.pollinations.ai/prompt/"
            f"{quote(desc[:120])}"
            f"?width=800&height=600&nologo=true")

def has_real_img(html: str) -> bool:
    """포스트 HTML에 실제 https:// 이미지가 있는지 확인 (base64 제외)"""
    imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    return any(src.startswith('http') for src in imgs)

def main():
    posts = json.loads(LINKS_FILE.read_text(encoding='utf-8'))
    posts_with_id = [p for p in posts if p.get('post_id')]
    print(f"총 {len(posts_with_id)}개 포스트 처리 시작\n")

    svc   = build('blogger', 'v3', credentials=get_creds())
    ok    = 0
    skip  = 0
    error = 0

    for i, p in enumerate(posts_with_id):
        post_id = p['post_id']
        topic   = p.get('topic', p.get('title', ''))
        title   = p.get('title', '')

        try:
            post = svc.posts().get(blogId=BLOG_ID, postId=post_id, fields='id,content').execute()
            html = post.get('content', '')

            if has_real_img(html):
                print(f"[{i+1}/{len(posts_with_id)}] SKIP (실제 URL 이미 있음): {title[:50]}")
                skip += 1
                continue

            # 썸네일용 숨김 img 이미 있는지 확인
            if 'image.pollinations.ai' in html:
                print(f"[{i+1}/{len(posts_with_id)}] SKIP (Pollinations 이미 있음): {title[:50]}")
                skip += 1
                continue

            thumb_url = get_thumb_url(topic)
            hidden_img = f'<img src="{thumb_url}" style="display:none;width:1px;height:1px;" alt="" />\n'
            new_html = hidden_img + html

            svc.posts().update(
                blogId=BLOG_ID,
                postId=post_id,
                body={'content': new_html}
            ).execute()

            print(f"[{i+1}/{len(posts_with_id)}] OK: {title[:50]}")
            ok += 1
            time.sleep(1.5)  # API rate limit

        except Exception as e:
            print(f"[{i+1}/{len(posts_with_id)}] ERROR ({title[:40]}): {e}")
            error += 1
            time.sleep(2)

    print(f"\n완료: OK={ok} / SKIP={skip} / ERROR={error}")

if __name__ == '__main__':
    main()
