"""
NutriStack Lab — 전체 파이프라인 시작 스크립트
실행: python start_all.py
- 이미 실행 중인 프로세스는 건너뜀 (중복 실행 방지)
- 새 창(콘솔)이 필요한 프로세스는 별도 창으로 기동
- 백그라운드 프로세스는 숨김 창으로 기동
"""
import sys, os, time, subprocess, socket, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from pathlib import Path

# ── 중복 실행 방지 (이 런처 자체) ───────────────────────
_lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _lock_sock.bind(('127.0.0.1', 19996))
except socket.error:
    print("⚠️  start_all.py 이미 실행 중입니다.")
    sys.exit(0)

import psutil

PIPELINE_DIR = Path(__file__).parent
PY = sys.executable

# script명 : 새 창 여부
PROCESSES = {
    "morning_report.py":                      False,   # 백그라운드
    "hernex_agent.py":                        False,   # 백그라운드 (Telegram 봇)
    "bot_start.py":                           False,   # 백그라운드 (Discord 봇)
    "daily_scheduler_v5.py":                  True,    # 새 콘솔창
    "00_NutriStack_Grand_Orchestrator_v5.py": True,    # 새 콘솔창
}

def get_running() -> set:
    """현재 실행 중인 스크립트명 집합 반환."""
    running = set()
    for p in psutil.process_iter(['cmdline']):
        try:
            cmd = ' '.join(p.info['cmdline'] or [])
            for script in PROCESSES:
                if script in cmd:
                    running.add(script)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return running

def start(script: str, new_window: bool):
    path = str(PIPELINE_DIR / script)
    if new_window:
        subprocess.Popen(
            ["cmd", "/k", PY, path],
            cwd=str(PIPELINE_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        subprocess.Popen(
            [PY, path],
            cwd=str(PIPELINE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

print("=" * 50)
print("  NutriStack Lab — 파이프라인 시작")
print("=" * 50)

already = get_running()
started = []
skipped = []

for script, new_window in PROCESSES.items():
    if script in already:
        print(f"  ↩  {script:<45} (이미 실행 중 — 건너뜀)")
        skipped.append(script)
    else:
        start(script, new_window)
        print(f"  ✓  {script:<45} {'[새 창]' if new_window else '[백그라운드]'}")
        started.append(script)
        time.sleep(0.5)   # 순차 기동 (포트 충돌 방지)

print()
print(f"기동: {len(started)}개  /  스킵: {len(skipped)}개")
if skipped:
    print(f"스킵됨: {', '.join(s.replace('.py','') for s in skipped)}")
print()

# 기동 후 3초 대기 후 최종 상태 확인
time.sleep(3)
final = get_running()
print("─" * 50)
print("  최종 실행 상태")
print("─" * 50)
all_ok = True
for script in PROCESSES:
    ok = script in final
    if not ok: all_ok = False
    mark = "✓" if ok else "✗"
    print(f"  {mark}  {script}")
print()
print(f"{'✅ 전체 정상 가동' if all_ok else '⚠️  일부 미실행 — 위 ✗ 항목 확인 필요'}")
print("=" * 50)

_lock_sock.close()

input("\n아무 키나 누르면 닫힙니다...")
