import discord
from discord.ext import commands, tasks
from discord.ui import View, Select, Button
import datetime
import asyncio
import os
from dotenv import load_dotenv
from zoneinfo import ZoneInfo  # Python 3.9+

# ==========================================
# [설정 구간]
# ==========================================
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

# 로그 파일 경로 설정
LOG_FILE_PATH = "vote_log.txt"

# 한국 시간대 설정
KST = ZoneInfo("Asia/Seoul")
# ==========================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 투표 옵션 데이터
VOTE_OPTIONS = [
    ("가능한 일정 없음", "none" ),
    ("월 19:00~21:00", "월_19-21"), ("월 20:00~22:00", "월_20-22"), ("월 21:00~23:00", "월_21-23"), ("월 22:00~24:00", "월_22-24"),
    ("화 19:00~21:00", "화_19-21"), ("화 20:00~22:00", "화_20-22"), ("화 21:00~23:00", "화_21-23"), ("화 22:00~24:00", "화_22-24"),
    ("수 19:00~21:00", "수_19-21"), ("수 20:00~22:00", "수_20-22"), ("수 21:00~23:00", "수_21-23"), ("수 22:00~24:00", "수_22-24"),
    ("목 19:00~21:00", "목_19-21"), ("목 20:00~22:00", "목_20-22"), ("목 21:00~23:00", "목_21-23"), ("목 22:00~24:00", "목_22-24"),
    ("금 19:00~21:00", "금_19-21"), ("금 20:00~22:00", "금_20-22"), ("금 21:00~23:00", "금_21-23"), ("금 22:00~24:00", "금_22-24"),
    ("일 19:00~21:00", "일_19-21"), ("일 20:00~22:00", "일_20-22"), ("일 21:00~23:00", "일_21-23"), ("일 22:00~24:00", "일_22-24"),
]


# 데이터 저장소 (메모리)
# 구조: { user_id: { "월_19-21", "화_21-23" ... } }
vote_data = {}

def log_vote(user_id: int, username: str, action: str, time_slot: str):
    """투표 내역을 파일에 로그로 기록합니다."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] 유저: {username} (ID: {user_id}) | {action}: {time_slot}\n"

    with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
        f.write(log_entry)

def generate_status_embed(is_closed=False, show_details=False):
    total_voters = len(vote_data)

    # [수정됨] 단순 카운트가 아니라, 누가 투표했는지 ID 리스트를 담습니다.
    # 구조: { "월_19-21": [123456(유저ID), 987654(유저ID)] }
    result_voters = {value: [] for _, value in VOTE_OPTIONS}

    for user_id, choices in vote_data.items():
        for choice in choices:
            if choice in result_voters:
                result_voters[choice].append(user_id)

    # 정렬 (투표 많은 순)
    # x[1]은 리스트이므로 len(x[1])로 길이를 비교해야 함
    sorted_results = sorted(result_voters.items(), key=lambda x: len(x[1]), reverse=True)

    if total_voters > 0:
        perfect_times = [
            next(label for label, val in VOTE_OPTIONS if val == val_code)
            for val_code, user_list in sorted_results if len(user_list) == total_voters
        ]
    else:
        perfect_times = []

    details = ""
    # 상세 내역 텍스트 생성
    for val, user_list in sorted_results:
        count = len(user_list)
        if count > 0:
            label_name = next(label for label, v in VOTE_OPTIONS if v == val)

            # [수정됨] 유저 ID를 멘션 형태(<@ID>)로 변환하여 나열
            # 예: (@철수, @영희)
            mentions = ", ".join([f"<@{uid}>" for uid in user_list])

            details += f"**{label_name}**: {count}명 ({mentions})\n"

    if not details: details = "내역 없음"

    if is_closed:
        title = "📊 투표 결과 확정"
        desc = f"투표가 종료되었습니다.\n총 참여 인원: **{total_voters}명**"
        color = 0xff0000
    else:
        title = "📅 차주 스크림 일정 투표 (진행중)"
        desc = f"아래 **[투표 하기]** 버튼을 눌러 일정을 선택해주세요.\n현재 참여 인원: **{total_voters}명**"
        color = 0x9b59b6

    embed = discord.Embed(title=title, description=desc, color=color)

    # 상세 내용(누가 투표했는지)은 '관리자 미리보기'거나 '투표 종료'일 때만 표시
    if is_closed or show_details:
        if perfect_times:
            embed.add_field(name="🌟 모두 가능한 시간 (Best)", value="\n".join(perfect_times), inline=False)
        elif total_voters > 0:
            embed.add_field(name="🌟 만장일치 없음", value="아래 최다 득표 시간을 참고하세요.", inline=False)

        embed.add_field(name="상세 득표 현황", value=details, inline=False)
    else:
        embed.add_field(name="🔒 결과 비공개", value="투표가 종료되면 결과가 공개됩니다.\n모두 투표를 완료해주세요!", inline=False)

    return embed

class PersonalTimeButton(Button):
    def __init__(self, label, value, is_selected):
        style = discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary
        super().__init__(style=style, label=label, custom_id=value)
        self.value = value
        self.label_name = label  # 라벨 이름 저장

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user_id = interaction.user.id
        username = interaction.user.display_name

        if user_id not in vote_data:
            vote_data[user_id] = set()

        if self.value in vote_data[user_id]:
            vote_data[user_id].remove(self.value)
            self.style = discord.ButtonStyle.secondary
            # 투표 취소 로그
            log_vote(user_id, username, "투표 취소", self.label_name)
        else:
            vote_data[user_id].add(self.value)
            self.style = discord.ButtonStyle.success
            # 투표 추가 로그
            log_vote(user_id, username, "투표", self.label_name)

        await interaction.edit_original_response(view=self.view)

class PersonalVoteView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        user_votes = vote_data.get(user_id, set())
        for label, value in VOTE_OPTIONS:
            is_selected = value in user_votes
            self.add_item(PersonalTimeButton(label, value, is_selected))

class MainVoteView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🗳️ 투표 하기", style=discord.ButtonStyle.primary, custom_id="start_vote", row=0)
    async def start_vote(self, interaction: discord.Interaction, button: Button):
        user_role_ids = [role.id for role in interaction.user.roles]
        if ADMIN_ROLE_ID in user_role_ids:
            await interaction.response.send_message("🚫 관리자는 투표에 참여하지 않습니다.", ephemeral=True)
            return

        view = PersonalVoteView(interaction.user.id)
        await interaction.response.send_message(
            "가능한 시간을 선택하세요. (버튼을 누르면 **초록색**으로 바뀝니다)\n선택 후 창을 닫아도 저장됩니다.",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="🔄 인원수 갱신", style=discord.ButtonStyle.secondary, custom_id="refresh_board", row=0)
    async def refresh_board(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        # 갱신 시에는 누가 투표했는지는 가리고(False) 인원수만 갱신
        new_embed = generate_status_embed(is_closed=False, show_details=False)
        await interaction.edit_original_response(embed=new_embed, view=self)

    @discord.ui.button(label="👀 (관리자) 현황 미리보기", style=discord.ButtonStyle.secondary, custom_id="admin_peek", row=1)
    async def admin_peek(self, interaction: discord.Interaction, button: Button):
        user_role_ids = [role.id for role in interaction.user.roles]
        if ADMIN_ROLE_ID not in user_role_ids:
            await interaction.response.send_message("🚫 권한이 없습니다.", ephemeral=True)
            return

        # 여기서 show_details=True 이므로 누가 투표했는지 보임
        peek_embed = generate_status_embed(is_closed=False, show_details=True)
        peek_embed.title = "👀 현재 투표 현황 (관리자용)"
        peek_embed.description = "이 메시지는 관리자에게만 보입니다."

        await interaction.response.send_message(embed=peek_embed, ephemeral=True)

    @discord.ui.button(label="⛔ 투표 종료 (관리자용)", style=discord.ButtonStyle.danger, custom_id="end_vote", row=1)
    async def end_vote(self, interaction: discord.Interaction, button: Button):
        user_role_ids = [role.id for role in interaction.user.roles]
        if ADMIN_ROLE_ID not in user_role_ids:
            await interaction.response.send_message("🚫 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        # 투표 종료 시 show_details=True 이므로 결과에 이름이 공개됨
        final_embed = generate_status_embed(is_closed=True, show_details=True)

        await interaction.edit_original_response(embed=final_embed, view=None)
        await interaction.channel.send("✅ 투표가 종료되었습니다. 결과가 공개됩니다.")

@bot.event
async def on_ready():
    print(f'로그인 성공: {bot.user}')
    check_schedule.start()

@tasks.loop(minutes=1)
async def check_schedule():
    now = datetime.datetime.now(KST)  # 한국 시간 기준으로 변경
    if now.weekday() == 5 and now.hour == 22 and now.minute == 0:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            vote_data.clear()
            embed = generate_status_embed(is_closed=False, show_details=False)
            await channel.send("@everyone 📢 차주 스크림 일정 투표가 시작되었습니다!", embed=embed, view=MainVoteView())
            await asyncio.sleep(60)

@bot.command(name="startvote")
async def start_vote_manual(ctx):
    user_role_ids = [role.id for role in ctx.author.roles]
    if ADMIN_ROLE_ID not in user_role_ids:
        await ctx.send("🚫 이 명령어는 관리자만 사용할 수 있습니다.", delete_after=5)
        return

    vote_data.clear()
    embed = generate_status_embed(is_closed=False, show_details=False)
    await ctx.send("@everyone 📢 차주 스크림 일정 투표가 시작되었습니다!", embed=embed, view=MainVoteView())
    await ctx.message.delete()

if __name__ == "__main__":
    bot.run(TOKEN)