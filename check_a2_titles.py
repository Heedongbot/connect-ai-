import pickle, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from googleapiclient.discovery import build

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
svc = build("blogger", "v3", credentials=creds)

ids = {
    "Probiotics": "7296783476176454996",
    "Berberine":  "4225522812606428004",
    "Iron":       "1947968909150831484",
}
for name, pid in ids.items():
    post = svc.posts().get(blogId="2812259517039331714", postId=pid).execute()
    print(f"{name}: {post['title']}")
