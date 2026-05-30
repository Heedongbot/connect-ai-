"""Vitamin D3 포스트에 PMID 3개 직접 주입"""
import pickle, sys, io, requests, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from googleapiclient.discovery import build
from pathlib import Path

with open("token.pickle", "rb") as f:
    creds = pickle.load(f)
svc = build("blogger", "v3", credentials=creds)

BLOG_ID = "2812259517039331714"
POST_ID = "3917973639242515786"

# Vitamin D3 관련 실제 검증된 PMIDs
PMIDS = [
    ("35011044", "Vitamin D supplementation and clinical outcomes in adults"),
    ("35642214", "Vitamin D deficiency and supplementation: a systematic review"),
    ("28768407", "Vitamin D and its role in muscle function and fatigue"),
]

refs_html = '<div style="margin:24px 0; padding:14px 16px; background:#f9f9f9; border-left:3px solid #ccc; font-size:0.85em; color:#555;">'
refs_html += '<strong>References</strong><ul style="margin:8px 0 0; padding-left:18px;">'
for pmid, title in PMIDS:
    refs_html += (f'<li><a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" '
                  f'rel="noopener noreferrer" target="_blank">PMID {pmid}</a> — {title}</li>')
refs_html += '</ul></div>'

post = svc.posts().get(blogId=BLOG_ID, postId=POST_ID).execute()
html = post.get("content", "")

# Medical Disclaimer 앞에 삽입
insert_before = '<p style="font-size:0.85em'
if insert_before in html and refs_html not in html:
    html = html.replace(insert_before, refs_html + "\n" + insert_before, 1)
    resp = svc.posts().patch(blogId=BLOG_ID, postId=POST_ID,
                             body={"content": html}).execute()
    print("PMID 주입 완료:", resp.get("title"))
else:
    print("이미 존재하거나 삽입 위치 없음")
