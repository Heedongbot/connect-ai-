import pickle, json, re
from pathlib import Path
from googleapiclient.discovery import build

post = json.loads(Path('D:/블로그/nutristack/pipeline/20_Meta/berberine_current.json').read_text(encoding='utf-8'))
content = post.get('content', '')
new_title = 'The Berberine Mistake That Made Me Want to Quit'

# 1. H1 교체
content = re.sub(r'<h1[^>]*>.*?</h1>', '<h1>' + new_title + '</h1>', content, flags=re.DOTALL)

# 2. OG title
content = re.sub(r'(property="og:title"[^>]*content=")[^"]*(")', r'\g<1>' + new_title + r'\g<2>', content)
content = re.sub(r'(content="[^"]*"[^>]*property="og:title")', 'content="' + new_title + '" property="og:title"', content)

# 3. JSON-LD headline
content = re.sub(r'("headline"\s*:\s*")[^"]*(")', r'\g<1>' + new_title + r'\g<2>', content)

# 4. 이미지 alt 교체
content = re.sub(
    r'alt="[^"]*[Bb]erberine[^"]*[Cc]omplete[^"]*"',
    'alt="my berberine bottle next to breakfast"',
    content
)
content = content.replace(
    'A bottle of Berberine and Complete on a wooden kitchen counter',
    'my berberine bottle next to breakfast'
)

# 5. 캡션 교체
content = content.replace('Personal observations on Berberine And Complete', 'The bottle I almost stopped taking during week 2.')
content = content.replace('Personal observations on Berberine and Complete', 'The bottle I almost stopped taking during week 2.')

# 6. 템플릿 치환 실패
content = content.replace('Berberine And Complete', 'Berberine')
content = content.replace('Berberine and Complete', 'Berberine')

# 7. thriving → more stable
content = content.replace("I wasn’t just surviving—I was thriving.", "I felt more stable.")
content = content.replace("I wasn't just surviving—I was thriving.", "I felt more stable.")
content = content.replace("I was thriving", "I felt more stable")

# 8. 커피 FAQ 통일
content = content.replace(
    "The author took their first dose with coffee, not food, and experienced no adverse effects. While the label suggested taking it with food, the auth",
    "Taking it with coffee alone—without food—caused GI discomfort in the early weeks. Pairing it with a small meal (even a banana) made a noticeable difference. Coffee itself isn’t the issue; skipping food is."
)

# 검증
h1 = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.DOTALL)
print('H1:', h1.group(1)[:70] if h1 else 'NOT FOUND')
print('alt OK:', 'my berberine bottle' in content)
print('Berberine And Complete 잔존:', 'Berberine And Complete' in content or 'Berberine and Complete' in content)
print('thriving 잔존:', 'thriving' in content)

Path('D:/블로그/nutristack/pipeline/20_Meta/berberine_fixed.html').write_text(content, encoding='utf-8')
print('저장완료')
