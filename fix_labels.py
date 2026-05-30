"""라벨 없는 포스팅에 라벨 추가 + Blogger 업데이트"""
import pickle, json, re
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE = Path(__file__).parent / "token.pickle"
BLOG_ID    = "2812259517039331714"
PUB_FILE   = Path(__file__).parent / "20_Meta" / "published_links.json"

# 제목/URL 키워드 → 추가 라벨 매핑
KEYWORD_LABELS = {
    "quercetin":         ["Quercetin", "Antioxidant", "Immunity"],
    "phosphatidylserin": ["PhosphatidylSerine", "BrainHealth", "Memory"],
    "melatonin":         ["Melatonin", "Sleep", "CircadianRhythm"],
    "calcium":           ["Calcium", "BoneHealth", "Minerals"],
    "iodine":            ["Iodine", "Thyroid", "Minerals"],
    "elderberry":        ["Elderberry", "Immunity", "WinterHealth"],
    "nmn":               ["NMN", "NAD", "Longevity", "AntiAging"],
    "magnesium":         ["Magnesium", "Minerals", "BrainHealth"],
    "zinc":              ["Zinc", "Immunity", "Minerals"],
    "vitamin-c":         ["VitaminC", "Antioxidant", "Immunity"],
    "vitamin-d":         ["VitaminD3", "Immunity", "BoneHealth"],
    "omega":             ["Omega3", "BrainHealth", "HeartHealth"],
    "collagen":          ["Collagen", "Joints", "Skin"],
    "berberine":         ["Berberine", "Metabolic", "AMPK"],
    "coq10":             ["CoQ10", "Mitochondria", "Energy"],
    "morning-vs-eveni":  ["Timing", "CircadianRhythm"],
    "when-i-take":       ["Timing", "PersonalProtocol"],
    "after-vs":          ["Comparison", "PersonalProtocol"],
    "vitamin-vs":        ["Comparison", "PersonalProtocol"],
    "never-combine":     ["Stacking", "Safety"],
    "side-effect":       ["Safety", "Research"],
}
DEFAULT_LABELS = ["Supplements", "NordicHealth", "NutriStackLab"]

def get_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)

def pick_labels(title: str, url: str) -> list:
    key = (title + " " + url).lower()
    extra = []
    for kw, tags in KEYWORD_LABELS.items():
        if kw in key:
            extra.extend(tags)
    return DEFAULT_LABELS + list(dict.fromkeys(extra))  # 중복 제거

def url_to_path(url: str) -> str:
    return url.split("nutristacklab.com")[1]

def main():
    svc  = get_service()
    data = json.loads(PUB_FILE.read_text(encoding="utf-8"))

    no_label = [p for p in data if not p.get("labels")]
    print(f"라벨 없는 포스팅: {len(no_label)}개\n")

    updated = 0
    for p in no_label:
        title   = p.get("title", "")
        url     = p.get("url", "")
        post_id = p.get("post_id", "")

        # post_id 없으면 URL로 조회
        if not post_id and url:
            try:
                res     = svc.posts().getByPath(blogId=BLOG_ID, path=url_to_path(url)).execute()
                post_id = res.get("id", "")
                p["post_id"] = post_id
            except Exception as e:
                print(f"  [SKIP] ID 조회 실패: {title[:40]} → {e}")
                continue

        if not post_id:
            print(f"  [SKIP] post_id 없음: {title[:40]}")
            continue

        # Blogger에서 현재 포스트 가져오기
        try:
            post = svc.posts().get(blogId=BLOG_ID, postId=post_id).execute()
        except Exception as e:
            print(f"  [SKIP] 포스트 조회 실패: {title[:40]} → {e}")
            continue

        existing = post.get("labels", [])
        if existing:
            print(f"  [OK 이미 있음] {title[:40]} → {existing}")
            p["labels"] = existing
            continue

        labels = pick_labels(title, url)
        try:
            svc.posts().update(
                blogId=BLOG_ID,
                postId=post_id,
                body={
                    "id":      post_id,
                    "title":   post.get("title", title),
                    "content": post.get("content", ""),
                    "labels":  labels,
                }
            ).execute()
            p["labels"] = labels
            print(f"  [OK] {title[:45]}")
            print(f"       라벨: {', '.join(labels)}")
            updated += 1
        except Exception as e:
            print(f"  [FAIL] {title[:40]} → {e}")

    # published_links.json 업데이트
    PUB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n완료: {updated}개 업데이트, published_links.json 저장")

if __name__ == "__main__":
    main()
