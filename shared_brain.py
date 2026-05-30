"""
shared_brain.py — NutriStack Lab 통합 지식 관리자

모든 에이전트(Writer, Critic, HTML Assembler, Verifier)가
동일한 shared_brain.json을 읽고 씀.

발행 전 Critic 반려 → 발행 후 Claude 스캔 → 좋은 예시 → 전부 같은 두뇌.

Tier 시스템:
  Tier 1 (5회+): 각인 — 모든 에이전트, 프롬프트 최상단
  Tier 2 (3~4회): 핵심 — Writer + Critic
  Tier 3 (1~2회): 학습 중 — Verifier, 경보 수준
"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("SharedBrain")

BRAIN_FILE = None   # 외부에서 init() 호출 시 설정됨

_BRAIN_CACHE = None
_BRAIN_MTIME = 0.0


def init(meta_dir: Path):
    global BRAIN_FILE
    BRAIN_FILE = meta_dir / "shared_brain.json"
    _ensure_file()


def _ensure_file():
    if BRAIN_FILE and not BRAIN_FILE.exists():
        _save({"version": 1, "rules": [], "good_patterns": [],
               "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M")})


def _load() -> dict:
    global _BRAIN_CACHE, _BRAIN_MTIME
    if not BRAIN_FILE or not BRAIN_FILE.exists():
        return {"rules": [], "good_patterns": []}
    try:
        mtime = BRAIN_FILE.stat().st_mtime
        if _BRAIN_CACHE and mtime == _BRAIN_MTIME:
            return _BRAIN_CACHE
        _BRAIN_CACHE = json.loads(BRAIN_FILE.read_text(encoding="utf-8"))
        _BRAIN_MTIME = mtime
        return _BRAIN_CACHE
    except Exception:
        return {"rules": [], "good_patterns": []}


def _save(brain: dict):
    global _BRAIN_CACHE, _BRAIN_MTIME
    if not BRAIN_FILE:
        return
    brain["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    BRAIN_FILE.write_text(json.dumps(brain, ensure_ascii=False, indent=2), encoding="utf-8")
    _BRAIN_CACHE = brain
    _BRAIN_MTIME = BRAIN_FILE.stat().st_mtime


# ─────────────────────────────────────────────────────────────
# 기록 API — 어느 에이전트든 호출 가능
# ─────────────────────────────────────────────────────────────

def record_avoid(
    rule_type: str,
    instruction: str,
    severity: str = "medium",
    category: str = "content",
    source: str = "unknown",
    example_bad: str = "",
    example_good: str = "",
):
    """
    회피해야 할 버그/패턴 기록.
    rule_type: 짧은 식별자 (예: 'complete_guide_h1', 'double_encoding')
    """
    brain = _load()
    rules = brain.setdefault("rules", [])

    existing = next((r for r in rules if r["id"] == rule_type), None)
    today = datetime.now().strftime("%Y-%m-%d")

    if existing:
        existing["hit_count"] += 1
        existing["last_hit"] = today
        if source not in existing.get("sources", []):
            existing.setdefault("sources", []).append(source)
        if example_bad and not existing.get("example_bad"):
            existing["example_bad"] = example_bad[:200]
        if example_good and not existing.get("example_good"):
            existing["example_good"] = example_good[:200]
        # Tier 자동 승격
        existing["tier"] = _calc_tier(existing["hit_count"])
        count = existing["hit_count"]
    else:
        new_rule = {
            "id":           rule_type,
            "tier":         3,
            "type":         "AVOID",
            "severity":     severity,
            "category":     category,
            "instruction":  instruction[:200],
            "hit_count":    1,
            "sources":      [source],
            "first_hit":    today,
            "last_hit":     today,
            "example_bad":  example_bad[:200] if example_bad else "",
            "example_good": example_good[:200] if example_good else "",
        }
        rules.append(new_rule)
        count = 1

    _save(brain)
    log.info(f"  [Brain] AVOID 기록: {rule_type} ({count}회, tier={_calc_tier(count)})")
    return count


def record_good_pattern(
    pattern_id: str,
    instruction: str,
    category: str = "structure",
    source: str = "good_examples",
    example: str = "",
):
    """잘된 포스팅에서 발견된 좋은 패턴 기록."""
    brain = _load()
    goods = brain.setdefault("good_patterns", [])

    existing = next((g for g in goods if g["id"] == pattern_id), None)
    today = datetime.now().strftime("%Y-%m-%d")

    if existing:
        existing["confirmed_count"] += 1
        existing["last_confirmed"] = today
        count = existing["confirmed_count"]
    else:
        goods.append({
            "id":              pattern_id,
            "type":            "DO",
            "category":        category,
            "instruction":     instruction[:200],
            "confirmed_count": 1,
            "sources":         [source],
            "first_confirmed": today,
            "last_confirmed":  today,
            "example":         example[:200] if example else "",
        })
        count = 1

    _save(brain)
    log.info(f"  [Brain] DO 기록: {pattern_id} ({count}회 확인)")
    return count


def _calc_tier(hit_count: int) -> int:
    if hit_count >= 5: return 1
    if hit_count >= 3: return 2
    return 3


# ─────────────────────────────────────────────────────────────
# 외부 학습 파일 → shared_brain 동기화
# ─────────────────────────────────────────────────────────────

def sync_from_existing_files(meta_dir: Path):
    """
    기존 claude_discoveries.json + dynamic_rules.json + good_examples.json
    에서 shared_brain으로 흡수.
    """
    if not BRAIN_FILE:
        init(meta_dir)

    # claude_discoveries.json
    discoveries_path = meta_dir / "claude_discoveries.json"
    if discoveries_path.exists():
        try:
            items = json.loads(discoveries_path.read_text(encoding="utf-8"))
            for item in items:
                itype = item.get("type", "unknown")
                desc  = item.get("description", "")
                sev   = item.get("severity", "medium")
                cnt   = item.get("count", 1)
                for _ in range(cnt):
                    record_avoid(
                        rule_type   = itype,
                        instruction = desc[:200],
                        severity    = sev,
                        category    = "unknown",
                        source      = "post_publish_verifier",
                    )
        except Exception as e:
            log.warning(f"  [Brain] discoveries 동기화 실패: {e}")

    # dynamic_rules.json
    dynamic_path = meta_dir / "dynamic_rules.json"
    if dynamic_path.exists():
        try:
            data = json.loads(dynamic_path.read_text(encoding="utf-8"))
            for rule_text in data.get("rules", []):
                rule_id = re.sub(r'[^\w]', '_', rule_text[:40]).lower()
                record_avoid(
                    rule_type   = rule_id,
                    instruction = rule_text[:200],
                    severity    = "high",
                    category    = "content",
                    source      = "dynamic_rules",
                )
        except Exception as e:
            log.warning(f"  [Brain] dynamic_rules 동기화 실패: {e}")

    # good_examples.json
    good_path = meta_dir / "good_examples.json"
    if good_path.exists():
        try:
            examples = json.loads(good_path.read_text(encoding="utf-8"))
            for ex in examples:
                title = ex.get("title", "")
                if ex.get("has_hook"):
                    record_good_pattern("hook_in_intro", "Always include a Hook in the first 200 words (reader engagement)", source=title)
                if ex.get("has_toc"):
                    record_good_pattern("toc_present", "Include a Table of Contents with anchor links (SEO + UX)", source=title)
                if ex.get("has_faq"):
                    record_good_pattern("faq_section", "Include FAQ section with 3+ Q&A pairs (long-tail SEO)", source=title)
                if ex.get("pmid_count", 0) >= 2:
                    record_good_pattern("pmid_citations", f"Include 2+ PMID citations for scientific credibility", source=title)
                if ex.get("word_count", 0) >= 2000:
                    record_good_pattern("word_count_2000", "Aim for 2000+ words for comprehensive guides", source=title)
                if ex.get("section_count", 0) >= 5:
                    record_good_pattern("five_plus_sections", "Use 5+ H2 sections for proper structure", source=title)
        except Exception as e:
            log.warning(f"  [Brain] good_examples 동기화 실패: {e}")

    log.info("  [Brain] 기존 파일 동기화 완료")


# ─────────────────────────────────────────────────────────────
# 프롬프트 주입 API
# ─────────────────────────────────────────────────────────────

def get_injection(agent_role: str = "writer") -> str:
    """
    에이전트 역할에 맞는 지식 주입 블록 반환.

    agent_role: 'writer' | 'critic' | 'assembler' | 'verifier'
    """
    brain = _load()
    rules = brain.get("rules", [])
    goods = brain.get("good_patterns", [])

    if not rules and not goods:
        return ""

    lines = ["\n\n" + "═" * 60]
    lines.append("🧠 SHARED KNOWLEDGE BASE — ALL AGENTS FOLLOW THESE")
    lines.append("═" * 60)

    # ── Tier 1: 각인 (모든 에이전트) ─────────────────────────
    tier1 = [r for r in rules if r.get("tier") == 1]
    if tier1:
        lines.append("\n🔴 TIER 1 — INGRAINED RULES (NEVER VIOLATE — confirmed 5+ times):")
        for r in sorted(tier1, key=lambda x: x["hit_count"], reverse=True):
            line = f"  ✗ [{r['hit_count']}회] {r['instruction']}"
            if r.get("example_bad"):
                line += f"\n      BAD:  {r['example_bad'][:100]}"
            if r.get("example_good"):
                line += f"\n      GOOD: {r['example_good'][:100]}"
            lines.append(line)

    # ── Tier 2: 핵심 (writer + critic) ───────────────────────
    if agent_role in ("writer", "critic"):
        tier2 = [r for r in rules if r.get("tier") == 2]
        if tier2:
            lines.append("\n🟠 TIER 2 — CORE RULES (confirmed 3-4 times — strongly avoid):")
            for r in sorted(tier2, key=lambda x: x["hit_count"], reverse=True):
                lines.append(f"  ✗ [{r['hit_count']}회] {r['instruction']}")

    # ── Tier 3: 학습 중 (verifier만) ─────────────────────────
    if agent_role == "verifier":
        tier3 = [r for r in rules if r.get("tier") == 3]
        if tier3:
            lines.append("\n🟡 TIER 3 — LEARNING (1-2 hits — watch for these):")
            for r in sorted(tier3, key=lambda x: x["hit_count"], reverse=True)[:10]:
                lines.append(f"  ? [{r['hit_count']}회] {r['instruction']}")

    # ── 좋은 패턴 (writer에게 가장 중요) ─────────────────────
    if agent_role in ("writer", "critic") and goods:
        confirmed_goods = [g for g in goods if g["confirmed_count"] >= 2]
        if confirmed_goods:
            lines.append("\n✅ CONFIRMED GOOD PATTERNS (do these — appear in high-scoring posts):")
            for g in sorted(confirmed_goods, key=lambda x: x["confirmed_count"], reverse=True)[:10]:
                lines.append(f"  ✓ [{g['confirmed_count']}회 확인] {g['instruction']}")

    # ── assembler는 HTML 구조 규칙만 ─────────────────────────
    if agent_role == "assembler":
        html_rules = [r for r in rules if r.get("category") in ("html", "structure") and r.get("tier", 3) <= 2]
        if html_rules:
            lines.append("\n🔧 HTML STRUCTURE RULES (assembler-specific):")
            for r in html_rules:
                lines.append(f"  ✗ {r['instruction']}")

    lines.append("═" * 60 + "\n")

    result = "\n".join(lines)
    tier1_c = len(tier1)
    goods_c = len([g for g in goods if g["confirmed_count"] >= 2])
    log.info(f"  [Brain] {agent_role} 주입: Tier1={tier1_c}개, 좋은패턴={goods_c}개")
    return result


# ─────────────────────────────────────────────────────────────
# 편의 함수: Critic 반려 → Brain 기록
# ─────────────────────────────────────────────────────────────

def record_critic_rejection(issues: list, source_agent: str = "critic"):
    """Critic 반려 이슈 목록을 Brain에 기록."""
    for issue in issues:
        if isinstance(issue, str):
            rule_id = re.sub(r'[^\w]', '_', issue[:40]).lower()
            record_avoid(rule_id, issue[:200], severity="high",
                         category="content", source=source_agent)
        elif isinstance(issue, dict):
            record_avoid(
                rule_type   = issue.get("type", re.sub(r'[^\w]', '_', issue.get("description", "")[:30]).lower()),
                instruction = issue.get("description", str(issue))[:200],
                severity    = issue.get("severity", "high"),
                category    = issue.get("category", "content"),
                source      = source_agent,
                example_bad = issue.get("example_bad", ""),
                example_good= issue.get("example_good", ""),
            )


def record_verifier_scan(issues: list, source_agent: str = "post_publish_verifier"):
    """Post-publish verifier 스캔 결과를 Brain에 기록."""
    for issue in issues:
        record_avoid(
            rule_type   = issue.get("type", "unknown"),
            instruction = issue.get("description", "")[:200],
            severity    = issue.get("severity", "medium"),
            category    = "html",
            source      = source_agent,
        )


def record_post_success(title: str, scores: dict, html: str):
    """발행 후 9점 이상 통과 포스팅의 좋은 패턴 기록."""
    import re as _re
    text = _re.sub(r'<[^>]+>', ' ', html)
    word_count    = len(text.split())
    has_hook      = bool(_re.search(r'<(hr|em|blockquote)[^>]*>', html[:3000], _re.I))
    has_toc       = 'href="#sec' in html
    has_faq       = bool(_re.search(r'<h[23][^>]*>.*?FAQ|Frequently Asked', html, _re.I))
    pmid_count    = len(_re.findall(r'pubmed\.ncbi\.nlm\.nih\.gov', html))
    section_count = len(_re.findall(r'<h2[^>]*>', html, _re.I))

    if has_hook:       record_good_pattern("hook_in_intro",      "Always include a Hook in the first 200 words", source=title)
    if has_toc:        record_good_pattern("toc_present",        "Include TOC with anchor links (#sec)", source=title)
    if has_faq:        record_good_pattern("faq_section",        "Include FAQ section (3+ Q&A pairs) for long-tail SEO", source=title)
    if pmid_count >= 2:record_good_pattern("pmid_citations",     f"Include 2+ PMID citations (found {pmid_count})", source=title)
    if word_count >= 2000: record_good_pattern("word_count_2000","Write 2000+ words for comprehensive guides", source=title)
    if section_count >= 5: record_good_pattern("five_h2_sections",f"Use 5+ H2 sections ({section_count} found)", source=title)

    log.info(f"  [Brain] 성공 포스팅 패턴 기록: {title[:50]}")
