import pickle, re, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from googleapiclient.discovery import build

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
svc = build("blogger", "v3", credentials=creds)

result = svc.posts().list(blogId="2812259517039331714", status=["LIVE"], maxResults=50).execute()
for p in result.get("items", []):
    if "vitamin d" in p["title"].lower() or "vitd" in p["title"].lower():
        print(f"ID: {p['id']}")
        print(f"Title: {p['title']}")
        print(f"URL: {p.get('url','')}")
        with open("vitd3_current.html", "w", encoding="utf-8") as f:
            f.write(p.get("content", ""))
        print(f"HTML saved ({len(p.get('content',''))} chars)")
