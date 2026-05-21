# 🤖 AGENTS.md — NutriStack Lab Agent Specification

> **For AI coding assistants (Antigravity, Copilot, etc.)**: Read this file first before modifying any code in this repository. All agents, pipelines, and conventions are defined here.

---

## 🏗️ System Overview

**NutriStack Lab** is a fully autonomous AI content pipeline that publishes supplement science articles to [nutristacklab.com](https://www.nutristacklab.com) on Blogger. It uses a **P-Reinforce** reinforcement-learning architecture where each published post feeds back into the system as a reward signal.

### Core Entry Point
- **`00_NutriStack_Grand_Orchestrator.py`** — the `monitor()` loop runs 24/7, watching `00_Raw/` for `.txt` files. When a file appears, `GrandOrchestrator.run()` executes the full 10-step pipeline.

### Model Assignment (v3.0) — Step-by-Step

| Step | Role | Model | 우선순위 |
|------|------|-------|---------|
| **Step 1** — Research | 팩트 추출 / PubMed 정보 손실 최소화 | `gemma4:e4b-it-q8_0` | 🎯 **정밀도** — Q8 정밀 팩트 |
| **Step 2** — Section Writing | 본문 5섹션 집필 (500+단어/섹션) | `qwen2.5:14b-instruct` | 🧠 **지능** — 최대 체급 14B |
| **Step 3** — Hero Image | SDXL 스타일 고품질 프롬프트 생성 | `gemma2:2b` + `SDXL` | 🖼️ **품질** — masterpiece/HDR 묘사 |
| **Step 4** — Section Images | SD1.5 스타일 빠른 프롬프트 생성 | `gemma2:2b` + `SD 1.5` | ⚡ **속도** — 단순 키워드 위주 |
| **Step 5a** — Hook Draft | 창의적 도입부 초안 작성 | `gemma2:9b` | 💡 **창의** — 공감 감성 문장 |
| **Step 5b** — Hook Refine | 도입부 150단어 간결화 정제 | `qwen2:7b-instruct` | ✂️ **간결** — 임팩트 유지 다듬기 |
| **Step 6** — Title / FAQ / Meta | 제목·FAQ·메타 디스크립션 생성 | `qwen2.5:14b-instruct` | 🏆 **논리** — 전체 맥락 권위 부여 |
| **Step 7a** — Label Extract | SEO 핵심 키워드 초고속 추출 | `gemma2:2b` | ⚡ **속도** — 초고속 협업 |
| **Step 7b** — Label Polish | 마케팅 텍스트 SEO 최적화 | `gemma4:e4b-it-q4_0` | 🎯 **최적화** — 마케팅 다듬기 |
| **Step 8** — Critic | 오타·수치·형식 최종 엄격 검수 | `gemma4:e4b-it-q8_0` | 🔍 **무결성** — Q8 정밀 재검 |

### Key Runtime Constants (do NOT change without reading implications)
| Constant | Value | Purpose |
|---|---|---|
| `HEAVY_MODEL` | `qwen2.5:14b` | Research, writing, critic steps |
| `LIGHT_MODEL` | `qwen2.5:7b` | SEO, FAQ, labels, briefing |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Local LLM endpoint |
| `BLOG_ID` | `2812259517039331714` | Blogger target blog |
| `SCOPES` | `blogger` + `drive.file` | Google OAuth scopes |
| `TOKEN_FILE` | `token.pickle` | Google OAuth credentials cache |

---

## 📂 Directory Contract

| Path | Role | Read by | Written by |
|---|---|---|---|
| `00_Raw/` | Input queue — drop `.txt` files here to trigger pipeline | Orchestrator monitor loop | User / scheduler |
| `01_Completed/` | Post-processing archive | — | Orchestrator (on success or skip) |
| `02_Checkpoints/` | Per-topic JSON checkpoint (resume on crash) | `GrandOrchestrator.run()` | `GrandOrchestrator.run()` |
| `05_Images/` | Downloaded Pollinations PNGs | Upload functions | `get_image_url()` |
| `06_prompts/` | Agent system-prompt `.md` files | `load_agent()` | Developer / RL Manager |
| `10_Wiki/Decisions/` | Obsidian learning records (one `.md` per post) | `learning_engine.py` | `save_learning()` |
| `20_Meta/` | `published_links.json`, `pending_approval.json`, `performance_db.json`, `topic_bank.json` | Many agents | Many agents |

---

## 🔄 Pipeline — 10 Steps

Each step is guarded by a checkpoint key. If the process restarts, completed steps are skipped.

```
[RAW .txt file detected]
       │
       ▼
Step 0:  Duplicate check (is_duplicate_topic) — skip if ≥90% title overlap
       │
       ▼
Step 1:  RESEARCHER   — deep science research (HEAVY_MODEL)
       │                checkpoint key: "research"
       ▼
Step 2:  WRITER       — 5 × HTML section bodies, 400+ words each (HEAVY_MODEL)
       │                checkpoint key: "sections"
       ▼
Step 3:  VISUAL       — 6 images (hero + s1–s5) via Pollinations → Drive → Imgur → base64
       │                checkpoint key: "images"
       ▼
Step 4:  PERSONA      — Nordic hook (Draft: gemma2:9b → Refine: qwen2:7b)
       │                checkpoint key: "hook"
       ▼
Step 5:  SEO          — 1 optimized title ≤55 chars (LIGHT_MODEL)
       │                checkpoint key: "title"
       ▼
Step 6:  FAQ          — 3 Q&A pairs in HTML <h3>/<p> (LIGHT_MODEL)
       │                checkpoint key: "faq"
       ▼
Step 7:  PMID LOOKUP  — 5 PubMed IDs (real via pubmed_fetcher → fallback PMID_DB)
       │
       ▼
Step 8:  ASSEMBLER    — assemble_post() → full HTML + FAQPage schema
       │
       ▼
Step 9:  CRITIC       — quality_check() + LLM critic (HEAVY_MODEL), autonomous retries
       │                full authority to approve/reject with backtracking
       ▼
Step 10: PUBLISH      — Blogger API → save_link_to_db → Pinterest → save_learning()
```

---

## 🤖 Agent Roster

All system prompts live in `06_prompts/`. They are loaded at runtime via `load_agent(filename)`.

---

### 01 — Planner (`01_Planner_P_Reinforce.md`)

**Role**: P-Reinforce Architect  
**Invoked by**: Not directly called in the orchestrator (used in standalone planning flows)  
**Responsibility**:
- Analyse incoming raw information against the existing `10_Wiki/` knowledge graph
- Identify `[[bidirectional links]]` to existing wiki documents
- Assign tasks to Researcher, Writer, and Visual agents
- Log selection rationale to `10_Wiki/Decisions/YYYYMMDD_성분명_Selection.md`

**Output format**:
1. `[핵심 주제 및 연결될 위키 문서]` — related wiki links
2. `[타켓 키워드]` — 3 search-intent keywords
3. `[에이전트별 할당 태스크]` — per-agent task assignment

**Collaboration**: → `02_Researcher_Synergy` | Reviewer: `05_Critic_Editor_In_Chief`

---

### 02 — Researcher (`02_Researcher_Synergy.md`)

**Role**: Synergy Stacking Researcher  
**Model**: `HEAVY_MODEL` (`qwen2.5:14b`)  
**Invoked at**: Step 1  
**Prompt file**: `06_prompts/02_Researcher_Synergy.md`

**Responsibility**:
- Prioritise 2024–2026 PubMed / RCT literature
- Focus on synergy combinations ("A + B stacked together") to build affiliate marketing rationale
- Output: biological mechanism, ≥3 synergy stacks with PubMed IDs / URLs

**Input to orchestrator**: `self.ctx["research"]` (stored in checkpoint)  
**Context injection**: `learning_engine.get_prompt_context()` prepended to prompt when available

**Collaboration**: ← `01_Planner_P_Reinforce` | → `03_Writer_Gardener`

---

### 03 — Writer (`03_Writer_Gardener.md`)

**Role**: CHRONOS-X Writer Gardener v4.0  
**Model**: `HEAVY_MODEL` (`qwen2.5:14b`)  
**Invoked at**: Step 2 (5 × per topic)  
**Prompt file**: `06_prompts/03_Writer_Gardener.md`

**Responsibility**: Write exactly **one HTML section at a time** — 400–500 words, pure HTML `<p>` tags, zero markdown.

**5 Sections produced** (in order):
| Key | H2 Title | Style |
|---|---|---|
| `Blood-Brain Barrier Science` | `{nutrients}: The Absorption and Delivery Mechanism` | Story-driven |
| `Cognitive Enhancement Mechanism` | `{nutrients}: The Science and Biological Mechanisms` | Data-first |
| `Nootropic Synergy Stack` | `{nutrients}: Biochemical Interactions and Synergy` | Conversational |
| `Clinical Evidence` | `{nutrients}: Clinical Evidence and Trial Data` | Investigative |
| `Nordic Dosage Protocol` | `{nutrients}: Nordic Dosage and Timing Protocol` | Practical guide |

**Hard rules enforced in system prompt**:
- BANNED openers: "Furthermore", "Moreover", "In conclusion", "In today's world"
- BANNED phrases: "unlock", "game-changer", "dive into", "delve into", "leverage"
- Paragraph length must VARY: 1 sentence / 5–7 sentences / 1 sentence / 3–4 sentences
- Each section must include ≥1 personal observation injection and ≥1 question disruption
- Each section uses a different style template (see above)

**Nordic Voice Signatures required** (1 per section):
- "In Bergen, where winter lasts six months…"
- "During Mørketid, when the sun disappears entirely…"
- "Nordic biohackers figured this out years ago."

**Output stored**: `self.ctx["sections"][section_name]`

---

### 04 — SEO Optimizer (`04_SEO_Optimizer.md`)

**Role**: Senior Semantic Optimizer  
**Model**: `LIGHT_MODEL` (`qwen2.5:7b`)  
**Invoked at**: Step 5  
**Prompt file**: `06_prompts/04_SEO_Optimizer.md`

**Responsibility**: Generate one SEO-optimized title (≤55 chars, both nutrient names, one power word: Nordic / Science / Protocol / Guide / Stack / Winter).

**Output format** (strict, line-by-line):
- Line 1: optimized English title
- Line 2: 150-char meta description
- Line 3+: H-tag outline + LSI keyword suggestions

**Fallback**: If AI title fails validation (length, banned words), `generate_title()` constructs a rule-based fallback.  
**Output stored**: `self.ctx["title"]`

---

### 05 — Critic (`05_Critic_Editor_In_Chief.md`)

**Role**: Quality Sniper & Master Editor  
**Model**: `HEAVY_MODEL` (`qwen2.5:14b`)  
**Invoked at**: Step 9  
**Prompt file**: `06_prompts/05_Critic_Editor_In_Chief.md`

**Responsibility**: Final quality gate. Outputs `APPROVED` or `REJECTED` with Korean-language rejection reasons.

**Instant rejection triggers** (ANY one = reject):
1. Markdown symbols remain in HTML (`**`, `##`, `* `)
2. AI filler phrases present ("도움이 되길 바랍니다", "실험해 보세요")
3. Fewer than 3 PubMed PMIDs in body
4. Under 2,500 words
5. Missing Key Takeaways box, image tags, or comparison tables
6. Generic/mechanical tone instead of 2nd-person Nordic persona

**Retry logic** (orchestrator-managed):
- **Full Authority**: Critic decides when to approve or reject. No manual boss approval required.
- **Backtracking**: Use `[BACKTRACK_TO]: {Agent}` to reset specific steps (Researcher, Writer, Persona, SEO, FAQ, Visual).
- **Loop Protection**: Orchestrator automatically forces approval if a semantic loop is detected or after 10 retries to prevent deadlock.
- **Immediate Publish**: Upon approval, the topic proceeds directly to Step 10.

**Rejection reasons MUST be written in Korean** (hard requirement in prompt).

---

### 06 — Persona Guardian (`06_Persona_Guardian.md`)

**Role**: PERSONA GUARDIAN v4.0 — Human Authenticity Enforcer  
**Model**: `HEAVY_MODEL` (`qwen2.5:14b`)  
**Invoked at**: Step 4 (Nordic hook)  
**Prompt file**: `06_prompts/06_Persona_Guardian.md`

**Responsibility**:
- Write the 180-word Nordic opening hook: specific city + exact time, 2nd-person present tense, physical sensation, physiological symptom, ends with tension (NO solution, NO product pitch)
- Replace all AI-detection red-flag words (see replacement table in prompt)
- Inject micro-expressions, Nordic voice signatures, emotional authenticity markers
- Break uniform paragraph rhythm; allow sentence fragments for emphasis

**Banned in hook**: "unlock", "boost", "game-changer", any sales language  
**Output stored**: `self.ctx["hook"]`

---

### 07 — Visual Architect (`07_Visual_Architect.md`)

**Role**: Visual Architect / Stable Diffusion Engineer  
**Invoked at**: Step 3 (image generation)  
**Prompt file**: `06_prompts/07_Visual_Architect.md`

**Responsibility**: Design image prompts for 6 slots per post.

**Image slots**:
| Key | Theme Template |
|---|---|
| `hero` | `cinematic wide shot {style} Nordic winter aurora borealis backdrop professional` |
| `s1` | `blood-brain barrier crossing {style} molecule transport dark blue scientific` |
| `s2` | `synaptic plasticity neural connections forming {style} golden spark dark` |
| `s3` | `supplement synergy stack {style} molecules connecting network dark infographic` |
| `s4` | `clinical trial data visualization {style} graphs professional medical chart` |
| `s5` | `supplement protocol dosage timing {style} Nordic morning infographic clean` |

**Image retrieval pipeline** (5-level fallback):
1. Pollinations AI download (3 retries, 50s timeout)
2. Google Drive upload → thumbnail URL
3. Imgur upload (2 retries)
4. base64 inline encoding
5. Minimal 1×1 fallback PNG → base64

**Style DB**: `IMAGE_STYLE_DB` (in orchestrator) maps nutrient keyword → Stable Diffusion style string  
**Quality target**: Photorealistic, 8K, dark moody clinical, Nordic premium brand

---

### 08 — Formatter & Auditor (`08_Formatter_Auditor.md`)

**Role**: CHRONOS-X Formatter & Auditor v4.0 — 30-Point Kill List  
**Model**: Not called via LLM in orchestrator; logic is in `quality_check()` function  
**Prompt file**: `06_prompts/08_Formatter_Auditor.md` (reference spec for Critic and developers)

**Automated checks** (`quality_check()` — 9 items scored):
| # | Check | Pass condition |
|---|---|---|
| 1 | H1 count | Exactly 1 `<h1>` |
| 2 | H1 length | ≤60 chars |
| 3 | Pollinations URL | Zero `pollinations.ai` links |
| 4 | Empty `src=""` | Zero occurrences |
| 5 | Arrow format | `&#8594;` present |
| 6 | FAQPage schema | `"FAQPage"` in HTML |
| 7 | Schema tag | `<script type="application/ld+json">` present |
| 8 | Medical Disclaimer | `medical-disclaimer` link present |
| 9 | Disclosure | `Disclosure:` text present |

**Full 30-point specification** is in `06_prompts/08_Formatter_Auditor.md` and governs what Critic must also verify.

---

### 09 — Automation Engineer (`09_Automation_Engineer.md`)

**Role**: System Integration Engineer  
**Prompt file**: `06_prompts/09_Automation_Engineer.md`

**Responsibility** (consultant role — invoked in debugging/deployment contexts, not the main loop):
- Final HTML tag integrity check before publish
- Validate image sources and alt texts
- Approve deployment; produce Git commit message
- Report: `Pass/Fail`, detected technical defects, deploy summary

**Quality target**: Zero-error deployment; commit messages follow NutriStack knowledge-preservation principles.

---

### 10 — Analyst / RL Manager (`10_Analyst_RL_Manager.md`)

**Role**: Reinforcement Learning Manager  
**Prompt file**: `06_prompts/10_Analyst_RL_Manager.md`  
**Invoked by**: `send_daily_analytics_report()` (daily at 06:50) and `send_daily_briefing()` (daily at 05:00)

**Responsibility**:
- Pull GA4 + Google Search Console data (last 7 days)
- Analyse KPI reward signal $R = w_1(\text{Accuracy}) + w_2(\text{Connectivity}) + w_3(\text{Satisfaction})$
- Output per-agent prompt upgrade directives
- Recommend next 3 topics with highest revenue + knowledge-graph connectivity
- Update agent system prompts in `06_prompts/` as needed

**Data sources**:
- GA4: `properties/527664358` (sessions, users, page views — top 5 pages)
- Search Console: `sc-domain:nutristacklab.com` (clicks, impressions, top queries)
- Performance DB: `20_Meta/performance_db.json` (last 200 posts)

---

## 📡 Auxiliary Agents / Scripts

| Script | Role |
|---|---|
| `daily_scheduler.py` | Cron-like scheduler that writes topic `.txt` files to `00_Raw/` on a schedule |
| `blog_sync.py` | Syncs Blogger posts back to local wiki |
| `trend_hunter.py` | Fetches trending supplement topics; used in daily briefing |
| `pinterest_poster.py` | Posts hero image + title to Pinterest after successful publish |
| `label_updater.py` | Retroactively updates Blogger post labels |
| `retroactive_rewriter.py` | Rewrites old posts with new prompts |
| `retroactive_updater.py` | Updates specific fields in published posts |
| `morning_report.py` | Daily morning email/Discord summary |
| `learning_engine.py` | RAG: reads `10_Wiki/Decisions/` to inject past learnings into Researcher prompt |
| `pubmed_fetcher.py` | Real-time PubMed API search for relevant PMIDs |
| `image_restorer.py` | Retroactively restores broken/placeholder images in published posts |
| `bot_start.py` | Discord bot: listens for `!승인 <topic>` / `!폐기 <topic>` boss commands |
| `master_hq.py` | HQ dashboard / manual control interface |

---

## 🔌 External Integrations

| Service | Auth Method | Scope |
|---|---|---|
| Google Blogger API v3 | OAuth2 (`token.pickle`) | `blogger` |
| Google Drive API v3 | OAuth2 (`token.pickle`) | `drive.file` |
| Google Analytics Data API (GA4) | OAuth2 (`token.pickle`) | Read |
| Google Search Console API | OAuth2 (`token.pickle`) | Read |
| Ollama (local LLM) | HTTP REST (`localhost:11434`) | None |
| Pollinations AI | HTTP GET (no auth) | Image generation |
| Imgur API | Client-ID header (`546c25a59c58ad7`) | Image upload |
| Discord Webhook | JSON POST (`discord_webhook.json`) | Notifications |
| Pinterest API | `pinterest_config.json` | Pin creation |
| PubMed E-utilities | HTTP GET (no auth) | Paper lookup |

---

## 🧠 Quality & Learning Loop

### Published Links DB (`20_Meta/published_links.json`)
- Appended after every successful publish
- Used by `find_related_links()` to select 5 semantically-scored internal links per post
- Scoring: nutrient keyword match (+3), nutrient in link nutrients (+2), related nutrient in title (+2), same category (+1), topic word in title (+1)

### Performance DB (`20_Meta/performance_db.json`)
- Rolling window of 200 posts: date, topic, title, status, quality score, word count, nutrients, category, issues
- Read by RL Manager for policy updates

### Obsidian Learning Records (`10_Wiki/Decisions/`)
- One `.md` per post: date, topic, quality score, word count, wiki links, research summary, issues
- Read by `learning_engine.get_prompt_context()` → injected into Researcher prompt as RAG context

### Duplicate Detection (`is_duplicate_topic()`)
- Compares incoming topic against all titles in published links DB
- Uses Jaccard similarity on non-stop-words; threshold: **≥90% overlap → skip**

---

## ⚙️ Configuration Files

| File | Contents |
|---|---|
| `.env` | Environment variables (API keys) |
| `config.json` | General config (blog URL, schedule, etc.) |
| `gemini_config.json` | Gemini API key (used by `image_restorer.py`) |
| `discord_webhook.json` | `{"webhook_url": "https://discord.com/api/webhooks/..."}` |
| `pinterest_config.json` | Pinterest API credentials |
| `client_secrets.json` | Google OAuth2 client secrets |
| `token.pickle` | Cached Google OAuth2 credentials (auto-refreshed) |
| `daily_plan.json` | Today's scheduled topics |

---

## 🚫 Hard Rules for AI Coding Assistants

1. **Never remove checkpointing logic** from `GrandOrchestrator.run()`. Every step saves its result to `self.ctx` and writes `cp.write_text(...)`. This is the crash-recovery system.

2. **Never change `SCOPES`** without also deleting `token.pickle` and re-authenticating. Adding a scope without re-auth causes silent 403 failures.

3. **Never insert Pollinations URLs into final HTML**. The `clean_html()` function strips them; upstream code must ensure Drive/Imgur/base64 URLs are used. Pollinations is download-only.

4. **The `assemble_post()` function is the single source of truth for HTML structure**. Do not build HTML in individual agents — always funnel through `assemble_post()`.

5. **Banned phrases are enforced at two layers**: `BANNED_PHRASES` dict in `clean_banned()` (regex replace) and the Writer/Persona agent system prompts. If you add new banned phrases, add them to BOTH.

6. **The Critic has full autonomous authority**. It can reject and backtrack indefinitely. If an AI loop is detected (semantic repeat or 10+ retries), the orchestrator forces approval to break the cycle. Manual boss approval via Discord is no longer required for quality gate rejections.

7. **`token.pickle` covers both Blogger and Drive scopes**. If you add a new Google API (e.g., Sheets), add the scope to `SCOPES` and delete `token.pickle` to force re-auth.

8. **`load_agent(filename)`** reads from `PROMPT_DIR` (`06_prompts/`). Agent prompt filenames are the source of truth — the manager scripts (`02_Researcher_Manager.py` etc.) are auxiliary; the canonical prompts are in `06_prompts/`.

9. **Image fallback order is fixed**: Drive → Imgur → base64 → minimal PNG base64 → placeholder string. Never skip levels or change the order without testing the full fallback chain.

10. **Discord `report_to_discord(agent, message)`** is fire-and-forget (silent except). Never await it or make pipeline logic depend on its success.

11. **Stable Diffusion rendering is globally standardized to SD 1.5** (`v1-5-pruned-emaonly.safetensors`) for all local image generation (including hero images) to completely bypass checkpoint-switching overhead and prevent VRAM out-of-memory errors on consumer GPUs like RTX 3060. Standard resolutions are set to `768x1152` for hero images and `896x512` for section images. All image captions must be kept strictly educational/experiential and free from any commercial/ad-prone language (e.g., avoid mentioning "exact brands" or product promotions).

---

## 🔁 How to Add a New Agent

1. Create `06_prompts/NN_AgentName.md` with role, rules, and output format.
2. Add a `load_agent("NN_AgentName.md")` call at the appropriate step in `GrandOrchestrator.run()`.
3. Store output in `self.ctx["new_key"]` and call `save()` immediately after.
4. Add the checkpoint key to the step docstring.
5. Update this `AGENTS.md` with the new agent's entry in the roster.
6. Update `06_prompts/Agent_Collaboration_Map.md` with the new node.

---

## 🔁 How to Add a New Google API Integration

1. Add the required scope string to `SCOPES` list.
2. Delete `token.pickle` so the next run forces a browser re-auth flow.
3. Use `get_creds()` to obtain credentials; pass to `build('service', 'version', credentials=get_creds())`.
4. Test with the actual account that owns the Blog/Drive to avoid 403s.

---

*Last updated: 2026-05-04 | NutriStack Lab Grand Orchestrator v5.0 (SD1.5 Global Standard)*
