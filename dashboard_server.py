"""
NutriStack Lab - 실시간 대시보드 서버
- 파일 변경을 감지해 data.js를 2초마다 자동 갱신
- http://localhost:8080 으로 접속
"""
import http.server
import threading
import time
import webbrowser
from pathlib import Path
import importlib
import dashboard_sync

BASE_DIR    = Path(__file__).parent
DASHBOARD   = BASE_DIR / "dashboard"
PORT        = 8080

# ── 백그라운드 싱크 스레드 ──────────────────────────────────
def auto_sync_loop():
    """2초마다 실제 데이터를 읽어 data.js 갱신"""
    print("  🔄 실시간 동기화 루프 시작 (2초 간격)")
    while True:
        try:
            importlib.reload(dashboard_sync)
            dashboard_sync.sync()
        except Exception as e:
            print(f"  ⚠ sync 오류: {e}")
        time.sleep(2)

# ── HTTP 서버 ────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD), **kwargs)

    def log_message(self, format, *args):
        pass  # 접속 로그 숨김 (터미널 깔끔하게)

if __name__ == "__main__":
    print("=" * 50)
    print("  🖥  NutriStack Lab Dashboard Server")
    print(f"  📡 http://localhost:{PORT}")
    print("  ⏱  실시간 동기화: 2초 간격")
    print("=" * 50)

    # 싱크 스레드 시작
    t = threading.Thread(target=auto_sync_loop, daemon=True)
    t.start()

    # 초기 싱크 1회
    dashboard_sync.sync()

    # 브라우저 자동 오픈
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    # HTTP 서버 시작
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        print(f"  ✅ 서버 가동 중... (종료: Ctrl+C)")
        httpd.serve_forever()
