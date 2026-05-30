import pickle, json
from pathlib import Path
from googleapiclient.discovery import build

with open('D:/블로그/nutristack/pipeline/token.pickle', 'rb') as f:
    creds = pickle.load(f)

svc = build('blogger', 'v3', credentials=creds)
BLOG_ID = '2812259517039331714'
POST_ID = '4225522812606428004'

post = json.loads(Path('D:/블로그/nutristack/pipeline/20_Meta/berberine_current.json').read_text(encoding='utf-8'))
new_content = Path('D:/블로그/nutristack/pipeline/20_Meta/berberine_fixed.html').read_text(encoding='utf-8')
new_title = 'The Berberine Mistake That Made Me Want to Quit'

body = {
    'title': new_title,
    'content': new_content,
}

result = svc.posts().update(blogId=BLOG_ID, postId=POST_ID, body=body).execute()
print('업로드 완료: ' + result.get('title', ''))
print('URL: ' + result.get('url', ''))
