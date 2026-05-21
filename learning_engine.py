"""
NutriStack Lab — Learning Engine v1.0
성과 데이터 분석 → 패턴 학습 → 다음 포스팅에 반영
성장하는 에이전트 핵심 엔진
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from collections import Counter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

BASE_DIR    = Path(__file__).parent
META_DIR    = BASE_DIR / "20_Meta"
LEARN_DIR   = Path("D:/Users/66683/Documents/Obsidian") / "Decisions"
STATS_FILE  = META_DIR / "daily_stats.json"
LINKS_FILE  = META_DIR / "published_links.json"
MEMORY_FILE = META_DIR / "growth_memory.json"

# ============================================================
# 성장 메모리 로드/저장
# ============================================================
def load_memory():
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding='utf-8'))
        except:
            pass
    return {
        "version": 1,
        "last_updated": "",
        "total_posts": 0,
        "avg_sessions": 0,
        "avg_ctr": 0,

        # 제목 패턴 학습
        "title_patterns": {
            "high_ctr": [],
            "low_ctr": [],
            "best_starters": [],
            "best_length": 0,
        },

        # 카테고리 성과
        "category_performance": {
            "FUNDAMENTAL": {"sessions": 0, "ctr": 0, "count": 0},
            "COGNITIVE":   {"sessions": 0, "ctr": 0, "count": 0},
            "METABOLIC":   {"sessions": 0, "ctr": 0, "count": 0},
            "IMMUNE":      {"sessions": 0, "ctr": 0, "count": 0},
            "STRUCTURAL":  {"sessions": 0, "ctr": 0, "count": 0},
        },

        # 키워드 성과
        "keyword_performance": {},

        # 발행 타이밍 성과
        "timing_performance": {
            "monday": 0, "tuesday": 0, "wednesday": 0,
            "thursday": 0, "friday": 0, "saturday": 0, "sunday": 0
        },

        # 학습된 권장사항
        "recommendations": {
            "best_category": "",
            "best_title_pattern": "",
            "avoid_keywords": [],
            "priority_topics": [],
        },

        # 실패 패턴
        "failure_patterns": [],

        # 성공 포스팅 DB
        "top_posts": [],
    }

def save_memory(memory):
    memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    MEMORY_FILE.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    logging.info("  💾 성장 메모리 저장 완료")

# ============================================================
# 성과 데이터 분석
# ============================================================
def analyze_title_patterns(memory, links, stats):
    """제목 패턴 학습"""
    if not stats or not links:
        return memory

    recent_stats = stats[-7:] if len(stats) >= 7 else stats
    top_paths = {}
    for day in recent_stats:
        for page in day.get("top_pages", []):
            path = page.get("path", "")
            sess = page.get("sessions", 0)
            top_paths[path] = top_paths.get(path, 0) + sess

    high_perf_titles = []
    low_perf_titles  = []

    for link in links:
        url   = link.get("url", "")
        title = link.get("title", "")
        path  = "/" + "/".join(url.split("/")[3:]) if url else ""
        sessions = top_paths.get(path, 0)
        if sessions > 5:
            high_perf_titles.append(title)
        elif sessions == 0:
            low_perf_titles.append(title)

    if high_perf_titles:
        starters = [t.split()[0] for t in high_perf_titles if t]
        best_starters = [w for w, _ in Counter(starters).most_common(5)]
        memory["title_patterns"]["best_starters"] = best_starters
        avg_len = sum(len(t) for t in high_perf_titles) / len(high_perf_titles)
        memory["title_patterns"]["best_length"] = round(avg_len)
        memory["title_patterns"]["high_ctr"] = high_perf_titles[-10:]

    if low_perf_titles:
        memory["title_patterns"]["low_ctr"] = low_perf_titles[-10:]

    logging.info(f"  📊 제목 패턴 학습: 고성과 {len(high_perf_titles)}개 / 저성과 {len(low_perf_titles)}개")
    return memory

def analyze_keywords(memory, stats):
    """키워드 성과 학습"""
    if not stats:
        return memory

    recent = stats[-14:] if len(stats) >= 14 else stats
    keyword_perf = memory.get("keyword_performance", {})

    for day in recent:
        for q in day.get("top_queries", []):
            kw     = q.get("query", "").lower().strip()
            clicks = q.get("clicks", 0)
            ctr    = q.get("ctr", 0)
            pos    = q.get("position", 0)

            if kw not in keyword_perf:
                keyword_perf[kw] = {"clicks": 0, "ctr": 0, "position": 0, "count": 0}

            keyword_perf[kw]["clicks"]   += clicks
            keyword_perf[kw]["ctr"]       = (keyword_perf[kw]["ctr"] + ctr) / 2
            keyword_perf[kw]["position"]  = (keyword_perf[kw]["position"] + pos) / 2
            keyword_perf[kw]["count"]    += 1

    memory["keyword_performance"] = keyword_perf
    memory["recommendations"]["avoid_keywords"] = [
        kw for kw, data in keyword_perf.items()
        if data["clicks"] == 0 and data["count"] >= 3
    ][:10]

    logging.info(f"  🔍 키워드 학습: {len(keyword_perf)}개")
    return memory

def analyze_categories(memory, links, stats):
    """카테고리별 성과 학습"""
    cat_perf = memory.get("category_performance", {})

    # used_topics.json에서 카테고리 정보 추출
    used_file = META_DIR / "used_topics.json"
    if used_file.exists():
        try:
            used = json.loads(used_file.read_text(encoding='utf-8'))
            for u in used:
                cat = u.get("category", "") if isinstance(u, dict) else ""
                if cat in cat_perf:
                    cat_perf[cat]["count"] += 1
        except:
            pass

    if cat_perf:
        best_cat = max(
            cat_perf.items(),
            key=lambda x: x[1].get("sessions", 0) / max(x[1].get("count", 1), 1)
        )
        memory["recommendations"]["best_category"] = best_cat[0]

    memory["category_performance"] = cat_perf
    logging.info(f"  📁 카테고리 학습 완료 / 최고: {memory['recommendations']['best_category']}")
    return memory

def update_recommendations(memory, stats):
    """권장사항 업데이트"""
    if not stats:
        return memory

    recent = stats[-7:] if len(stats) >= 7 else stats
    avg_sessions = sum(d.get("sessions", 0) for d in recent) / len(recent) if recent else 0
    avg_ctr      = sum(d.get("ctr", 0) for d in recent) / len(recent) if recent else 0

    memory["avg_sessions"] = round(avg_sessions, 1)
    memory["avg_ctr"]      = round(avg_ctr, 2)

    starters = memory["title_patterns"].get("best_starters", [])
    best_len = memory["title_patterns"].get("best_length", 55)
    if starters:
        memory["recommendations"]["best_title_pattern"] = (
            f"시작 단어: {', '.join(starters[:3])} | 최적 길이: {best_len}자"
        )

    logging.info(f"  ✅ 권장사항 업데이트: 평균 세션 {avg_sessions:.1f} / CTR {avg_ctr:.2f}%")
    return memory

def save_learning_report(memory):
    """학습 결과를 옵시디언에 기록"""
    try:
        LEARN_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        date = datetime.now().strftime("%Y-%m-%d %H:%M")

        rec    = memory.get("recommendations", {})
        kw     = memory.get("keyword_performance", {})
        top_kw = sorted(kw.items(), key=lambda x: x[1]["clicks"], reverse=True)[:5]

        top_kw_md = "\n".join([
            f"- **{k}**: {v['clicks']}클릭 / CTR {v['ctr']:.1f}% / {v['position']:.1f}위"
            for k, v in top_kw
        ]) or "- 데이터 없음"

        avoid_kw = ", ".join(rec.get("avoid_keywords", [])) or "없음"

        md = f"""# NutriStack 학습 리포트 — {date}

## 📊 현재 성과
| 항목 | 수치 |
|------|------|
| 평균 일일 세션 | {memory['avg_sessions']} |
| 평균 CTR | {memory['avg_ctr']}% |
| 총 발행 포스팅 | {memory['total_posts']} |

## 🏆 학습된 권장사항
- **최고 성과 카테고리:** {rec.get('best_category', '분석 중')}
- **최적 제목 패턴:** {rec.get('best_title_pattern', '분석 중')}
- **피해야 할 키워드:** {avoid_kw}

## 🔍 상위 키워드
{top_kw_md}

## 📈 고성과 제목 패턴
{chr(10).join(['- ' + t for t in memory['title_patterns'].get('high_ctr', [])[:5]]) or '- 데이터 없음'}

## ⚠️ 저성과 제목 패턴
{chr(10).join(['- ' + t for t in memory['title_patterns'].get('low_ctr', [])[:5]]) or '- 데이터 없음'}

## 📁 카테고리 성과
{chr(10).join([f"- **{k}**: {v['count']}개 발행" for k, v in memory.get('category_performance', {}).items()]) or '- 데이터 없음'}

---
*NutriStack Lab Learning Engine v1.0 자동 기록*
"""
        fp = LEARN_DIR / f"{ts}_nutristack_learning.md"
        fp.write_text(md, encoding='utf-8')
        logging.info(f"  📚 학습 리포트 저장: {fp.name}")
    except Exception as e:
        logging.warning(f"  옵시디언 저장 실패: {e}")

# ============================================================
# 메인 학습 실행
# ============================================================
def run_learning():
    logging.info("\n🧠 NutriStack 학습 엔진 시작")

    memory = load_memory()

    stats = []
    if STATS_FILE.exists():
        try:
            stats = json.loads(STATS_FILE.read_text(encoding='utf-8'))
        except:
            pass

    links = []
    if LINKS_FILE.exists():
        try:
            links = json.loads(LINKS_FILE.read_text(encoding='utf-8'))
        except:
            pass

    memory["total_posts"] = len(links)

    memory = analyze_title_patterns(memory, links, stats)
    memory = analyze_keywords(memory, stats)
    memory = analyze_categories(memory, links, stats)
    memory = update_recommendations(memory, stats)

    save_memory(memory)
    save_learning_report(memory)

    logging.info("🧠 NutriStack 학습 완료!")
    return memory

def get_prompt_context():
    """오케스트레이터에서 호출 — 학습된 패턴을 AI 프롬프트에 주입"""
    memory = load_memory()
    rec    = memory.get("recommendations", {})
    kw     = memory.get("keyword_performance", {})

    top_kw = sorted(kw.items(), key=lambda x: x[1]["clicks"], reverse=True)[:5]
    top_kw_str = ", ".join([k for k, _ in top_kw]) if top_kw else ""
    avoid = ", ".join(rec.get("avoid_keywords", [])[:5])

    ctx = f"""
LEARNING CONTEXT (from previous NutriStack posts performance):
- Best performing category: {rec.get('best_category', 'Not enough data')}
- Best title pattern: {rec.get('best_title_pattern', 'Not enough data')}
- High-performing keywords to include: {top_kw_str if top_kw_str else 'Not enough data'}
- Keywords to avoid (low CTR): {avoid if avoid else 'None identified yet'}
- Average sessions per post: {memory.get('avg_sessions', 0)}
- Average CTR: {memory.get('avg_ctr', 0)}%

Apply these insights to improve this Nordic supplement post's performance.
"""
    return ctx

if __name__ == "__main__":
    run_learning()