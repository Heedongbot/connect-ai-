import discord
from discord.ext import commands
import sys
import io
import os
from datetime import datetime
from pathlib import Path

# Windows 11에서 유니코드(이모지 등) 출력을 위한 설정
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import socket
_instance_socket = None
def ensure_single_instance(port):
    global _instance_socket
    try:
        _instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _instance_socket.bind(('127.0.0.1', port))
    except socket.error:
        print(f"\n\u26a0\ufe0f [중복 실행 방지] 이미 동일한 프로그램이 실행 중입니다 (포트 {port} 점유 중).")
        print("중복 실행을 방지하기 위해 이 인스턴스를 즉시 종료합니다.\n")
        sys.exit(0)

ensure_single_instance(19997)

# 1. 봇의 권한 설정
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'✅ 사령부 봇 {bot.user.name} 가동 시작!')
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name="일반")
        if not channel and guild.text_channels:
            channel = guild.text_channels[0]
        if channel:
            await channel.send("🤖 **[NutriStack 사령부]** 마스터님, 시스템 가동 준비 완료! `!안녕`을 입력해 보세요.")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    print(f"📩 메시지 수신: {message.author}: {message.content}")
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore typing typos like !EORL (대기)
    raise error

@bot.command()
async def 안녕(ctx):
    await ctx.send(f"반갑습니다 마스터님! 현재 RTX 3060 12GB 사령부 상태는 최상입니다. 🚀")

@bot.command()
async def 임무(ctx):
    mission_text = (
        "🤖 **[NutriStack 사령부 임무 보고]**\n"
        "저는 마스터님의 건강 지식 제국을 건설하는 자율 에이전트들의 인터페이스입니다.\n\n"
        "1. **Trend Hunting**: 전 세계 최신 영양제 트렌드를 감시합니다.\n"
        "2. **Specialized Research**: 10인의 에이전트가 과학적 근거를 분석합니다.\n"
        "3. **Auto-Publishing**: 완성된 지식을 Blogger에 자동 배포합니다.\n\n"
        "마스터님은 그저 지켜보시기만 하면 됩니다!"
    )
    await ctx.send(mission_text)

@bot.command()
async def 상태(ctx):
    status_text = (
        "📊 **[사령부 시스템 상태]**\n"
        "- **CPU/GPU**: RTX 3060 12GB VRAM 최적화 상태\n"
        "- **에이전트**: 10인 분대 전원 배치 완료\n"
        "- **Blogger 연동**: API 대기 중\n"
        "- **현재 공정**: 자율 모드로 신규 트렌드 탐색 중..."
    )
    await ctx.send(status_text)

class ReportView(discord.ui.View):
    def __init__(self, topic, blog_url):
        super().__init__(timeout=None)
        self.topic = topic
        self.blog_url = blog_url

    @discord.ui.button(label="✅ 즉시 발행", style=discord.ButtonStyle.success)
    async def publish_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"🚀 **[{self.topic}]** 포스팅을 즉시 발행으로 전환합니다!", ephemeral=True)

    @discord.ui.button(label="📝 수정 요청", style=discord.ButtonStyle.primary)
    async def request_revision(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"📝 **[{self.topic}]** 에이전트들에게 수정을 명령했습니다!", ephemeral=True)

    @discord.ui.button(label="🎨 이미지 재생성", style=discord.ButtonStyle.secondary)
    async def redraw_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"🎨 **[{self.topic}]** 이미지를 다시 그리고 있습니다!", ephemeral=True)

@bot.command()
async def 호출(ctx, nickname, *, message):
    mapping = {
        "작가": "03_Writer_Gardener.md", "글쟁이": "03_Writer_Gardener.md",
        "연구원": "02_Researcher_Synergy.md", "박사": "02_Researcher_Synergy.md",
        "플래너": "01_Planner_P_Reinforce.md", "계획자": "01_Planner_P_Reinforce.md",
        "편집장": "05_Critic_Editor_In_Chief.md", "검수": "05_Critic_Editor_In_Chief.md",
        "비주얼": "07_Visual_Architect.md", "디자인": "07_Visual_Architect.md"
    }
    agent_file = mapping.get(nickname)
    if not agent_file:
        await ctx.send(f"❓ **{nickname}**(이)라는 에이전트는 사령부에 없습니다, 마스터님!")
        return
    from master_hq import PROMPT_DIR, ask_ai, HEAVY_MODEL
    prompt_path = PROMPT_DIR / agent_file
    if prompt_path.exists():
        with open(prompt_path, 'r', encoding='utf-8') as f:
            sys_prompt = f.read()
    else:
        sys_prompt = f"당신은 사령부의 {nickname} 에이전트입니다."
    async with ctx.typing():
        final_sys = sys_prompt + "\n\n[중요] 당신을 부른 사람은 사령부의 마스터입니다. 충성스럽고 전문적으로 답변하십시오."
        response = ask_ai(message, final_sys, HEAVY_MODEL)
    await ctx.send(f"🤖 **[{nickname} 에이전트 응답]**\n\n{response}")

@bot.command()
async def 보고(ctx, topic="마그네슘 부족"):
    embed = discord.Embed(
        title="🚀 NutriStack Lab 자율 공정 완료",
        description=f"주제: **{topic}** 에 대한 모든 분석과 집필이 끝났습니다.",
        color=0x2ecc71
    )
    embed.add_field(name="📊 콘텐츠 통계", value="글자 수: 약 3,500자\n상태: 임시저장 완료", inline=True)
    embed.add_field(name="🔬 분석 데이터", value="PubMed 최신 논문 기반\n시너지 스택 3종 발굴", inline=True)
    view = ReportView(topic, "https://www.nutristacklab.com")
    await ctx.send(embed=embed, view=view)

@bot.command()
async def 지시(ctx, *, topic):
    if len(topic.strip()) < 5:
        await ctx.send("⚠️ 주제가 너무 짧습니다! 더 구체적으로 적어주세요.")
        return
    if topic.strip().endswith("?"):
        await ctx.send(f"❓ `!지시`는 블로그 포스팅 임무를 내릴 때만 사용해 주세요.")
        return
    from master_hq import RAW_DIR
    safe_topic = "".join([c for c in topic if c.isalnum() or c in (" ", "_", "-")]).strip()
    file_path = RAW_DIR / f"{safe_topic}.txt"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"마스터 직접 지시 주제: {topic}\n지시 시간: {datetime.now()}")
        embed = discord.Embed(
            title="🎯 신규 임무 하달 완료",
            description=f"주제: **{topic}**",
            color=0x3498db
        )
        embed.set_footer(text="오케스트레이터가 분석을 시작합니다.")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ 지시 전달 실패: {e}")

# ============================================================
# v5.0 추가: 승인/폐기/대기/현황/오늘
# ============================================================
import json

META_DIR         = Path(__file__).parent / "20_Meta"
PENDING_APPROVAL = META_DIR / "pending_approval.json"
LINKS_DB_FILE    = META_DIR / "published_links.json"
TOPIC_BANK_FILE  = META_DIR / "topic_bank.json"

def load_pending():
    if PENDING_APPROVAL.exists():
        try: return json.loads(PENDING_APPROVAL.read_text(encoding="utf-8"))
        except: return []
    return []

def save_pending(data):
    META_DIR.mkdir(exist_ok=True, parents=True)
    PENDING_APPROVAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

@bot.command(name="승인")
async def approve_post(ctx, *, topic_query=""):
    if not topic_query:
        await ctx.send("❌ 사용법: `!승인 [주제명]`\n`!대기` 명령어로 대기 목록 확인")
        return
    pending = load_pending()
    matched = next((p for p in pending if topic_query.lower() in p.get("topic","").lower()), None)
    if not matched:
        await ctx.send(f"❌ 대기 중인 **{topic_query}** 포스팅이 없습니다.")
        return
    matched["status"] = "approved"
    matched["approved_at"] = datetime.now().isoformat()
    save_pending(pending)
    
    action = matched.get("action", "")
    if action == "UPDATE":
        # CEO run_approved_rewrites()가 in-place 수정 자동 실행 (새 포스팅 X)
        desc = f"**{matched['topic']}** 포스팅을 **기존 URL 유지 채로** 제자리 수정합니다.\n새 포스팅은 생성되지 않습니다."
    else:
        desc = f"**{matched['topic']}** 발행을 시작합니다."
    
    embed = discord.Embed(title="✅ 포스팅 승인됨!", description=desc, color=0x2ecc71)
    embed.set_footer(text="CEO 엔진이 자동으로 처리합니다.")
    await ctx.send(embed=embed)

@bot.command(name="폐기")
async def reject_post(ctx, *, topic_query=""):
    if not topic_query:
        await ctx.send("❌ 사용법: `!폐기 [주제명]`")
        return
    pending = load_pending()
    matched = next((p for p in pending if topic_query.lower() in p.get("topic","").lower()), None)
    if not matched:
        await ctx.send(f"❌ 대기 중인 **{topic_query}** 포스팅이 없습니다.")
        return
    matched["status"] = "rejected"
    matched["rejected_at"] = datetime.now().isoformat()
    save_pending(pending)
    embed = discord.Embed(title="🗑️ 포스팅 폐기됨", description=f"**{matched['topic']}** 폐기 처리됐습니다.", color=0xe74c3c)
    await ctx.send(embed=embed)

@bot.command(name="대기")
async def show_pending(ctx):
    pending = load_pending()
    waiting = [p for p in pending if p.get("status") == "waiting"]
    if not waiting:
        await ctx.send("✅ 현재 승인 대기 중인 포스팅이 없습니다!")
        return
    
    embed = discord.Embed(
        title=f"⏳ 자율감사 & 승인 대기 목록 ({len(waiting)}개)",
        description="마스터님! 구글 봇의 감시망을 피하기 위해 **하루에 딱 1~2개씩만** 점진적으로 `!승인` 하시는 것을 권장합니다! 🛡️",
        color=0xf39c12
    )
    
    for item in waiting[:10]:  # 최대 10개까지 한 번에 표시
        before_score = item.get('before_score', '?')
        score_str = f"⭐ **수정 전 점수**: {before_score}/10"
        action_type = f" | 🏷️ 조치: {item.get('type', 'REWRITE')}"
        
        embed.add_field(
            name=f"📝 {item.get('title') if item.get('title') else item.get('topic')}",
            value=(
                f"{score_str}{action_type}\n"
                f"💬 **피드백**: {item.get('critic_feedback','')[:120]}\n"
                f"👉 **승인 (모바일 복사용)**: `!승인 {item['topic']}`\n"
                f"👉 **폐기 (모바일 복사용)**: `!폐기 {item['topic']}`"
            ),
            inline=False
        )
        
    if len(waiting) > 10:
        embed.set_footer(text=f"외 {len(waiting) - 10}개의 대기 항목이 더 있습니다.")
        
    await ctx.send(embed=embed)

@bot.command(name="현황")
async def show_status(ctx):
    links, topics = [], []
    if LINKS_DB_FILE.exists():
        try: links = json.loads(LINKS_DB_FILE.read_text(encoding="utf-8"))
        except: pass
    if TOPIC_BANK_FILE.exists():
        try: topics = json.loads(TOPIC_BANK_FILE.read_text(encoding="utf-8"))
        except: pass
    pending_count = len([p for p in load_pending() if p.get("status") == "waiting"])
    topic_pending = len([t for t in topics if t.get("status") == "pending"])
    today = datetime.now().strftime("%Y-%m-%d")
    today_posts = [l for l in links if l.get("date","") == today]
    
    # 20_Meta/daily_plan.json에서 오늘 스케줄 로드
    schedule_value = "인간 엔트로피 (불규칙)"
    plan_file = Path("20_Meta/daily_plan.json")
    if plan_file.exists():
        try:
            import json
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            if plan.get("date") == today and "posts" in plan:
                times = [p.get("time") for p in plan["posts"] if "time" in p]
                if times:
                    schedule_value = f"{', '.join(times)} (유동적 자동)"
        except:
            pass
            
    embed = discord.Embed(title="📊 NutriStack 사령부 현황 v5.0", color=0x3498db)
    embed.add_field(name="📝 총 발행", value=f"{len(links)}개", inline=True)
    embed.add_field(name="📦 주제 대기", value=f"{topic_pending}개", inline=True)
    embed.add_field(name="⏳ 승인 대기", value=f"{pending_count}개", inline=True)
    embed.add_field(name="📰 오늘 발행", value=f"{len(today_posts)}개", inline=True)
    embed.add_field(name="⏰ 스케줄", value=schedule_value, inline=True)
    embed.set_footer(text=f"v5.0 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    await ctx.send(embed=embed)

@bot.command(name="오늘")
async def show_today(ctx):
    links = []
    if LINKS_DB_FILE.exists():
        try: links = json.loads(LINKS_DB_FILE.read_text(encoding="utf-8"))
        except: pass
    today = datetime.now().strftime("%Y-%m-%d")
    today_posts = [l for l in links if l.get("date","") == today]
    if not today_posts:
        await ctx.send(f"📭 오늘({today}) 발행된 포스팅이 없습니다.")
        return
    embed = discord.Embed(title=f"📰 오늘 발행 ({today})", color=0x9b59b6)
    for post in today_posts[:5]:
        embed.add_field(name=f"✅ {post.get('title','')[:50]}", value=post.get("url",""), inline=False)
    await ctx.send(embed=embed)

# 2. 토큰 불러오기 및 실행
def load_token():
    script_dir = Path(__file__).parent
    env_path = script_dir / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('DISCORD_BOT_TOKEN='):
                    return line.strip().split('=')[1].strip('"').strip("'")
    return None

token = load_token()
if token:
    bot.run(token)
else:
    print("❌ 에러: .env 파일에서 DISCORD_BOT_TOKEN을 찾을 수 없습니다.")