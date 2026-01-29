
import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import datetime
import json
import os
from dotenv import load_dotenv
from image_parser import parse_game_image

def format_mvp_svp(mvp: dict, svp: dict) -> str | None:
    """MVP와 SVP 정보를 포맷팅된 문자열로 반환"""
    result = ""
    if mvp.get('nickname'):
        result += f"🏆 MVP: **{mvp['nickname']}** ({mvp.get('mvp_score', 0):.1f}점)"
    if svp.get('nickname'):
        if result:
            result += " | "
        result += f"🥈 SVP: **{svp['nickname']}** ({svp.get('mvp_score', 0):.1f}점)"
    return result if result else None

# ==========================================
# [설정]
# ==========================================
load_dotenv()

TOKEN = os.getenv("SCRIM_BOT_TOKEN")
SCRIM_CHANNEL_ID = int(os.getenv("SCRIM_CHANNEL_ID"))
DATA_FILE = "scrim_data.json"
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))

# 팀 선수 닉네임 및 포지션 (포지션:닉네임 형식)
# 예: {"닉네임1": "탑", "닉네임2": "정글", ...}
TEAM_PLAYERS = {}
for entry in os.getenv("TEAM_PLAYERS", "").split(","):
    entry = entry.strip()
    if ":" in entry:
        position, nickname = entry.split(":", 1)
        TEAM_PLAYERS[nickname.strip()] = position.strip()

# 닉네임만 리스트로 (필터링용)
TEAM_PLAYER_NAMES = list(TEAM_PLAYERS.keys())

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# 데이터 저장/불러오기
# ==========================================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:  # 빈 파일인 경우
                    return {"matches": []}
                return json.loads(content)
        except json.JSONDecodeError:
            return {"matches": []}
    return {"matches": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def has_admin_role():
    """ADMIN_ROLE_ID 권한 체크 데코레이터"""
    async def predicate(ctx):
        user_role_ids = [role.id for role in ctx.author.roles]
        if ADMIN_ROLE_ID not in user_role_ids:
            await ctx.send("🚫 이 명령어는 관리자만 사용할 수 있습니다.", delete_after=5)
            return False
        return True
    return commands.check(predicate)

# ==========================================
# 이미지 분석 결과 확인 View
# ==========================================
class ImageConfirmView(View):
    def __init__(self, parsed_data: dict, author_id: int):
        super().__init__(timeout=300)
        self.parsed_data = parsed_data
        self.author_id = author_id
        self.memo = ""
        self.side = "blue"  # 기본값: 블루 진영

    @discord.ui.button(label="🔵 블루 진영", style=discord.ButtonStyle.primary, row=0)
    async def set_blue(self, interaction: discord.Interaction, button: Button):
        self.side = "blue"
        await interaction.response.send_message("🔵 블루 진영으로 설정되었습니다.", ephemeral=True)

    @discord.ui.button(label="🔴 레드 진영", style=discord.ButtonStyle.danger, row=0)
    async def set_red(self, interaction: discord.Interaction, button: Button):
        self.side = "red"
        await interaction.response.send_message("🔴 레드 진영으로 설정되었습니다.", ephemeral=True)

    @discord.ui.button(label="📝 메모 추가", style=discord.ButtonStyle.secondary, row=1)
    async def add_memo(self, interaction: discord.Interaction, button: Button):
        modal = MemoInputModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ 확인 및 저장", style=discord.ButtonStyle.success, row=1)
    async def confirm_save(self, interaction: discord.Interaction, button: Button):
        # 경기 데이터 구성
        match_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result": "승리" if self.parsed_data["is_win"] else "패배",
            "game_time": self.parsed_data.get("game_time"),
            "side": self.side,
            "memo": self.memo,
            "team1": self.parsed_data["team1"],
            "team2": self.parsed_data["team2"],
        }

        # 저장
        data = load_data()
        data["matches"].append(match_data)
        save_data(data)

        # 결과 임베드 생성
        embed = create_match_embed(match_data)

        await interaction.response.defer()
        await interaction.delete_original_response()
        await interaction.channel.send("✅ 경기 결과가 저장되었습니다!", embed=embed)

    @discord.ui.button(label="❌ 취소", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await interaction.delete_original_response()
        await interaction.channel.send("❌ 등록이 취소되었습니다.", delete_after=5)

class MemoInputModal(Modal):
    def __init__(self, view: ImageConfirmView):
        super().__init__(title="메모 추가")
        self.parent_view = view
        self.memo = TextInput(
            label="메모 (피드백, 개선점 등)",
            style=discord.TextStyle.paragraph,
            placeholder="예: 바텀 다이브 타이밍 개선 필요",
            max_length=500,
            required=False
        )
        self.add_item(self.memo)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.memo = self.memo.value.strip()
        await interaction.response.send_message("📝 메모가 저장되었습니다!", ephemeral=True)

# ==========================================
# 임베드 생성 함수
# ==========================================
def create_match_embed(match: dict) -> discord.Embed:
    """경기 결과 임베드 생성"""
    is_win = match["result"] == "승리"
    color = 0x2ecc71 if is_win else 0xe74c3c
    emoji = "🏆" if is_win else "💀"

    embed = discord.Embed(
        title=f"{emoji} 스크림 결과 - {match['result']}",
        color=color,
        timestamp=datetime.datetime.now()
    )

    # 기본 정보
    side_emoji = "🔵" if match.get("side") == "blue" else "🔴"
    side_text = "블루" if match.get("side") == "blue" else "레드"
    info_line = f"📅 {match['date']}  |  {side_emoji} {side_text} 진영"
    if match.get("game_time"):
        info_line += f"  |  ⏱️ {match['game_time']}"
    embed.description = info_line

    # 아군 팀 (team1)
    team1 = match.get("team1", {})
    team1_kda = f"{team1.get('total_kills', 0)}/{team1.get('total_deaths', 0)}/{team1.get('total_assists', 0)}"
    team1_gold = f"{team1.get('team_total_gold', 0):,}"

    team1_header = f"**{team1_kda}** KDA | 💰 **{team1_gold}**G"

    # 테이블 (챔피언, 레벨, KDA, 골드, 분당골드, 딜량, 분당딜, 골드비중, 골드대비딜)
    team1_table = "```\n"
    team1_table += f"{'CHAMP':<8} {'LV':>2} {'K/D/A':<9} {'GOLD':>6} {'G/M':>4} {'DMG':>6} {'D/M':>4} {'G%':>4} {'D/G':>5}\n"
    team1_table += f"{'-'*8} {'-'*2} {'-'*9} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*4} {'-'*5}\n"
    for p in team1.get('players', []):
        champ = p.get('champion', '?')[:8]
        level = p.get('level', 0)
        kda = f"{p['kills']}/{p['deaths']}/{p['assists']}"
        gold = p.get('total_gold', 0)
        gold_per_min = p.get('gold_per_min', 0)
        dmg = p.get('damage', 0)
        dmg_per_min = p.get('damage_per_min', 0)
        gold_share = p.get('gold_share', 0)
        dmg_per_gold = p.get('damage_per_gold', 0)

        team1_table += f"{champ:<8} {level:>2} {kda:<9} {gold//1000:>5}k {gold_per_min:>4} {dmg//1000:>5}k {int(dmg_per_min):>4} {gold_share:>3.0f}% {dmg_per_gold:>5.1f}\n"
    team1_table += "```"

    # 닉네임은 별도로 표시
    team1_nicks = " → ".join([f"**{p.get('nickname', '?')[:6]}**" for p in team1.get('players', [])])

    embed.add_field(name=f"🔵 아군 팀\n{team1_header}", value=f"{team1_nicks}\n{team1_table}", inline=False)

    # MVP/SVP 정보 추가 (team1 add_field 바로 아래)
    team1_mvp = team1.get('mvp', {})
    team1_svp = team1.get('svp', {})
    team1_mvp_str = format_mvp_svp(team1_mvp, team1_svp)
    if team1_mvp_str:
        embed.add_field(name="", value=team1_mvp_str, inline=False)

    # 상대 팀 (team2)
    team2 = match.get("team2", {})
    team2_kda = f"{team2.get('total_kills', 0)}/{team2.get('total_deaths', 0)}/{team2.get('total_assists', 0)}"
    team2_gold = f"{team2.get('team_total_gold', 0):,}"

    team2_header = f"**{team2_kda}** KDA | 💰 **{team2_gold}**G"

    team2_table = "```\n"
    team2_table += f"{'CHAMP':<8} {'LV':>2} {'K/D/A':<9} {'GOLD':>6} {'G/M':>4} {'DMG':>6} {'D/M':>4} {'G%':>4} {'D/G':>5}\n"
    team2_table += f"{'-'*8} {'-'*2} {'-'*9} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*4} {'-'*5}\n"
    for p in team2.get('players', []):
        champ = p.get('champion', '?')[:8]
        level = p.get('level', 0)
        kda = f"{p['kills']}/{p['deaths']}/{p['assists']}"
        gold = p.get('total_gold', 0)
        gold_per_min = p.get('gold_per_min', 0)
        dmg = p.get('damage', 0)
        dmg_per_min = p.get('damage_per_min', 0)
        gold_share = p.get('gold_share', 0)
        dmg_per_gold = p.get('damage_per_gold', 0)

        team2_table += f"{champ:<8} {level:>2} {kda:<9} {gold//1000:>5}k {gold_per_min:>4} {dmg//1000:>5}k {int(dmg_per_min):>4} {gold_share:>3.0f}% {dmg_per_gold:>5.1f}\n"
    team2_table += "```"

    team2_nicks = " → ".join([f"**{p.get('nickname', '?')[:6]}**" for p in team2.get('players', [])])

    embed.add_field(name=f"🔴 상대 팀\n{team2_header}", value=f"{team2_nicks}\n{team2_table}", inline=False)

    # MVP/SVP 정보 추가 (team2 add_field 바로 아래)
    team2_mvp = team2.get('mvp', {})
    team2_svp = team2.get('svp', {})
    team2_mvp_str = format_mvp_svp(team2_mvp, team2_svp)
    if team2_mvp_str:
        embed.add_field(name="", value=team2_mvp_str, inline=False)

    # 범례
    embed.add_field(
        name="📖 범례",
        value="`LV`레벨 `G/M`분당골드 `D/M`분당딜 `G%`골드비중 `D/G`100골드당딜",
        inline=False
    )

    # 메모
    if match.get("memo"):
        embed.add_field(name="📝 메모", value=f"```{match['memo']}```", inline=False)

    return embed


def create_preview_embed(parsed_data: dict) -> discord.Embed:
    """이미지 분석 결과 미리보기 임베드"""
    is_win = parsed_data.get("is_win")
    if is_win is None:
        color = 0x9b59b6
        result_text = "❓ 승패 인식 실패"
    elif is_win:
        color = 0x2ecc71
        result_text = "🏆 **승리**"
    else:
        color = 0xe74c3c
        result_text = "💀 **패배**"

    embed = discord.Embed(
        title="📸 이미지 분석 결과",
        description=f"{result_text}",
        color=color
    )

    if parsed_data.get("game_time"):
        embed.description += f"  |  ⏱️ **{parsed_data['game_time']}**"

    embed.description += "\n\n⚠️ **진영을 선택해주세요** (기본: 블루)"

    # 아군 팀 미리보기
    team1 = parsed_data.get("team1", {})
    team1_kda = f"{team1.get('total_kills', 0)}/{team1.get('total_deaths', 0)}/{team1.get('total_assists', 0)}"
    team1_gold = f"{team1.get('team_total_gold', 0):,}"

    team1_header = f"**{team1_kda}** KDA | 💰 **{team1_gold}**G"

    # 테이블 (챔피언, 레벨, KDA, 골드, 분당골드, 딜량, 분당딜, 골드비중, 골드대비딜)
    team1_table = "```\n"
    team1_table += f"{'CHAMP':<8} {'LV':>2} {'K/D/A':<9} {'GOLD':>6} {'G/M':>4} {'DMG':>6} {'D/M':>4} {'G%':>4} {'D/G':>5}\n"
    team1_table += f"{'-'*8} {'-'*2} {'-'*9} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*4} {'-'*5}\n"
    for p in team1.get('players', []):
        champ = p.get('champion', '?')[:8]
        level = p.get('level', 0)
        kda = f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}"
        gold = p.get('total_gold', 0)
        gold_per_min = p.get('gold_per_min', 0)
        dmg = p.get('damage', 0)
        dmg_per_min = p.get('damage_per_min', 0)
        gold_share = p.get('gold_share', 0)
        dmg_per_gold = p.get('damage_per_gold', 0)

        team1_table += f"{champ:<8} {level:>2} {kda:<9} {gold//1000:>5}k {gold_per_min:>4} {dmg//1000:>5}k {int(dmg_per_min):>4} {gold_share:>3.0f}% {dmg_per_gold:>5.1f}\n"
    team1_table += "```"

    # 닉네임은 별도로 표시
    team1_nicks = " → ".join([f"**{p.get('nickname', '?')[:6]}**" for p in team1.get('players', [])])

    embed.add_field(name=f"🔵 아군 팀\n{team1_header}", value=f"{team1_nicks}\n{team1_table}", inline=False)

    # MVP/SVP 정보 추가 (team1)
    team1_mvp = team1.get('mvp', {})
    team1_svp = team1.get('svp', {})
    team1_mvp_str = format_mvp_svp(team1_mvp, team1_svp)
    if team1_mvp_str:
        embed.add_field(name="", value=team1_mvp_str, inline=False)

    # 상대 팀 미리보기
    team2 = parsed_data.get("team2", {})
    team2_kda = f"{team2.get('total_kills', 0)}/{team2.get('total_deaths', 0)}/{team2.get('total_assists', 0)}"
    team2_gold = f"{team2.get('team_total_gold', 0):,}"

    team2_header = f"**{team2_kda}** KDA | 💰 **{team2_gold}**G"

    team2_table = "```\n"
    team2_table += f"{'CHAMP':<8} {'LV':>2} {'K/D/A':<9} {'GOLD':>6} {'G/M':>4} {'DMG':>6} {'D/M':>4} {'G%':>4} {'D/G':>5}\n"
    team2_table += f"{'-'*8} {'-'*2} {'-'*9} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*4} {'-'*5}\n"
    for p in team2.get('players', []):
        champ = p.get('champion', '?')[:8]
        level = p.get('level', 0)
        kda = f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)}"
        gold = p.get('total_gold', 0)
        gold_per_min = p.get('gold_per_min', 0)
        dmg = p.get('damage', 0)
        dmg_per_min = p.get('damage_per_min', 0)
        gold_share = p.get('gold_share', 0)
        dmg_per_gold = p.get('damage_per_gold', 0)

        team2_table += f"{champ:<8} {level:>2} {kda:<9} {gold//1000:>5}k {gold_per_min:>4} {dmg//1000:>5}k {int(dmg_per_min):>4} {gold_share:>3.0f}% {dmg_per_gold:>5.1f}\n"
    team2_table += "```"

    team2_nicks = " → ".join([f"**{p.get('nickname', '?')[:6]}**" for p in team2.get('players', [])])

    embed.add_field(name=f"🔴 상대 팀\n{team2_header}", value=f"{team2_nicks}\n{team2_table}", inline=False)

    # MVP/SVP 정보 추가 (team2)
    team2_mvp = team2.get('mvp', {})
    team2_svp = team2.get('svp', {})
    team2_mvp_str = format_mvp_svp(team2_mvp, team2_svp)
    if team2_mvp_str:
        embed.add_field(name="", value=team2_mvp_str, inline=False)

    # 범례
    embed.add_field(
        name="📖 범례",
        value="`LV`레벨 `G/M`분당골드 `D/M`분당딜 `G%`골드비중 `D/G`100골드당딜",
        inline=False
    )

    embed.set_footer(text="✅ 확인 후 저장 버튼을 눌러주세요 | ❌ 인식 오류 시 취소 후 재시도")

    return embed

# ==========================================
# 통계 함수
# ==========================================
def calculate_stats(matches: list, period: str = "all") -> dict:
    """전적 통계 계산"""
    now = datetime.datetime.now()
    filtered = []

    for match in matches:
        match_date = datetime.datetime.strptime(match["date"], "%Y-%m-%d %H:%M")
        if period == "week":
            if (now - match_date).days <= 7:
                filtered.append(match)
        elif period == "month":
            if (now - match_date).days <= 30:
                filtered.append(match)
        else:
            filtered.append(match)

    if not filtered:
        return None

    total = len(filtered)
    wins = sum(1 for m in filtered if m["result"] == "승리")
    losses = total - wins
    win_rate = (wins / total * 100) if total > 0 else 0

    # 챔피언 통계 (team1 = 아군 팀)
    champion_stats = {}
    for match in filtered:
        team1 = match.get("team1", {})
        for player in team1.get("players", []):
            champ = player.get("champion")
            position = player.get("position")
            if champ and champ != "알 수 없음":
                key = f"{position}-{champ}"
                if key not in champion_stats:
                    champion_stats[key] = {
                        "wins": 0, "losses": 0,
                        "kills": 0, "deaths": 0, "assists": 0,
                        "damage": 0, "gold": 0, "gold_per_min": 0,
                        "gold_share": 0, "damage_per_gold": 0,
                        "level": 0, "games": 0,
                        "position": position, "champion": champ,
                        "total_game_time": 0
                    }
                stats = champion_stats[key]
                stats["games"] += 1
                stats["kills"] += player.get("kills", 0)
                stats["deaths"] += player.get("deaths", 0)
                stats["assists"] += player.get("assists", 0)
                stats["damage"] += player.get("damage", 0)
                stats["gold"] += player.get("total_gold", 0)
                stats["gold_per_min"] += player.get("gold_per_min", 0)
                stats["gold_share"] += player.get("gold_share", 0)
                stats["damage_per_gold"] += player.get("damage_per_gold", 0)
                stats["level"] += player.get("level", 0)

                # 게임 시간 합산 (분 단위)
                game_time_str = match.get("game_time", "0:00")
                try:
                    parts = game_time_str.split(":")
                    if len(parts) == 2:
                        minutes = int(parts[0]) + int(parts[1]) / 60
                        stats["total_game_time"] += minutes
                except:
                    pass

                if match["result"] == "승리":
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1

    # 플레이어별 통계 (team1, team2 모두에서 팀 선수 검색)
    player_stats = {}
    for match in filtered:
        is_win = match["result"] == "승리"

        # 게임 시간 파싱
        game_time_str = match.get("game_time", "0:00")
        game_minutes = 0
        try:
            parts = game_time_str.split(":")
            if len(parts) == 2:
                game_minutes = int(parts[0]) + int(parts[1]) / 60
        except:
            pass

        # team1과 team2 모두 확인
        for team_key in ["team1", "team2"]:
            team = match.get(team_key, {})
            for player in team.get("players", []):
                nickname = player.get("nickname", "알 수 없음")
                if nickname == "알 수 없음":
                    continue

                # 등록된 팀 선수인지 확인 (TEAM_PLAYER_NAMES가 있는 경우)
                if TEAM_PLAYER_NAMES and nickname not in TEAM_PLAYER_NAMES:
                    continue

                if nickname not in player_stats:
                    player_stats[nickname] = {
                        "games": 0, "wins": 0, "losses": 0,
                        "kills": 0, "deaths": 0, "assists": 0,
                        "damage": 0, "gold": 0, "gold_per_min": 0,
                        "gold_share": 0, "damage_per_gold": 0,
                        "level": 0, "total_game_time": 0
                    }
                ps = player_stats[nickname]
                ps["games"] += 1
                ps["kills"] += player.get("kills", 0)
                ps["deaths"] += player.get("deaths", 0)
                ps["assists"] += player.get("assists", 0)
                ps["damage"] += player.get("damage", 0)
                ps["gold"] += player.get("total_gold", 0)
                ps["gold_per_min"] += player.get("gold_per_min", 0)
                ps["gold_share"] += player.get("gold_share", 0)
                ps["damage_per_gold"] += player.get("damage_per_gold", 0)
                ps["level"] += player.get("level", 0)
                ps["total_game_time"] += game_minutes

                # 승패 적용: team1 기준으로 판단
                if team_key == "team1":
                    if is_win:
                        ps["wins"] += 1
                    else:
                        ps["losses"] += 1
                else:  # team2
                    if is_win:
                        ps["losses"] += 1
                    else:
                        ps["wins"] += 1

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "champion_stats": champion_stats,
        "player_stats": player_stats
    }

# ==========================================
# 명령어
# ==========================================
@bot.event
async def on_ready():
    print(f'스크림 결과 봇 로그인 성공: {bot.user}')

@bot.command(name="register")
@has_admin_role()
async def register_match(ctx):
    """
    스크림 결과를 이미지로 등록합니다.
    사용법: !등록 (이미지 첨부)
    """
    if not ctx.message.attachments:
        embed = discord.Embed(
            title="📸 이미지를 첨부해주세요",
            description="게임 결과 스크린샷과 함께 `!등록` 명령어를 사용해주세요.",
            color=0x9b59b6
        )
        embed.add_field(
            name="사용 방법",
            value="1. 게임 종료 후 결과 화면 캡처\n2. 디스코드에서 `!등록` 입력\n3. 스크린샷 이미지 첨부\n4. 전송",
            inline=False
        )
        await ctx.send(embed=embed, delete_after=15)
        return

    attachment = ctx.message.attachments[0]
    if not attachment.content_type or not attachment.content_type.startswith('image/'):
        await ctx.send("❌ 이미지 파일만 첨부 가능합니다.", delete_after=10)
        return

    # 분석 중 메시지
    processing_msg = await ctx.send("🔄 이미지 분석 중... (잠시만 기다려주세요)")

    try:
        parsed_data = await parse_game_image(attachment.url)

        if parsed_data is None:
            await processing_msg.edit(content="❌ 이미지 분석에 실패했습니다. 다시 시도해주세요.")
            return

        # 미리보기 임베드 생성
        preview_embed = create_preview_embed(parsed_data)
        view = ImageConfirmView(parsed_data, ctx.author.id)

        await processing_msg.edit(content=None, embed=preview_embed, view=view)
        await ctx.message.delete()

    except Exception as e:
        await processing_msg.edit(content=f"❌ 이미지 분석 중 오류 발생: {str(e)}")

@bot.command(name="champion")
@has_admin_role()
async def champion_stats_cmd(ctx):
    """
    포지션별 챔피언 통계를 조회합니다.
    사용법: !챔피언통계
    """
    data = load_data()
    if not data["matches"]:
        await ctx.send("📊 아직 등록된 경기 기록이 없습니다.")
        return

    stats = calculate_stats(data["matches"], "all")
    if not stats or not stats["champion_stats"]:
        await ctx.send("📊 챔피언 기록이 없습니다.")
        return

    embed = discord.Embed(
        color=0x9b59b6
    )

    # 포지션별로 그룹화
    by_position = {}
    for key, champ_data in stats["champion_stats"].items():
        position = champ_data["position"]
        if position not in by_position:
            by_position[position] = []

        games = champ_data["games"]
        win_rate = (champ_data["wins"] / games * 100) if games > 0 else 0
        avg_kda = (champ_data["kills"] + champ_data["assists"]) / max(champ_data["deaths"], 1)
        avg_level = champ_data["level"] / games if games > 0 else 0
        avg_gold = champ_data["gold"] / games if games > 0 else 0
        avg_gold_per_min = champ_data["gold_per_min"] / games if games > 0 else 0
        avg_damage = champ_data["damage"] / games if games > 0 else 0
        avg_damage_per_min = avg_damage / (champ_data["total_game_time"] / games) if champ_data["total_game_time"] > 0 else 0
        avg_gold_share = champ_data["gold_share"] / games if games > 0 else 0
        avg_damage_per_gold = champ_data["damage_per_gold"] / games if games > 0 else 0

        by_position[position].append({
            "champion": champ_data["champion"],
            "games": games,
            "wins": champ_data["wins"],
            "losses": champ_data["losses"],
            "win_rate": win_rate,
            "avg_kda": avg_kda,
            "avg_level": avg_level,
            "avg_gold": avg_gold,
            "avg_gold_per_min": avg_gold_per_min,
            "avg_damage": avg_damage,
            "avg_damage_per_min": avg_damage_per_min,
            "avg_gold_share": avg_gold_share,
            "avg_damage_per_gold": avg_damage_per_gold
        })

    position_emojis = {"탑": "🛡️", "정글": "🌲", "미드": "⚡", "원딜": "🏹", "서폿": "💚", "식스맨": "🔄"}

    # 포지션별 선수 닉네임 찾기
    position_players = {}
    for nickname, pos in TEAM_PLAYERS.items():
        if pos not in position_players:
            position_players[pos] = []
        position_players[pos].append(nickname)

    # 식스맨 선수의 챔피언 통계 수집
    sixman_players = position_players.get("식스맨", [])
    sixman_champs = {}

    if sixman_players:
        for match in data["matches"]:
            is_win = match["result"] == "승리"

            # 게임 시간 파싱
            game_time_str = match.get("game_time", "0:00")
            game_minutes = 0
            try:
                parts = game_time_str.split(":")
                if len(parts) == 2:
                    game_minutes = int(parts[0]) + int(parts[1]) / 60
            except:
                pass

            for team_key in ["team1", "team2"]:
                team = match.get(team_key, {})
                for player in team.get("players", []):
                    nickname = player.get("nickname", "")
                    if nickname in sixman_players:
                        champ = player.get("champion", "알 수 없음")
                        if champ == "알 수 없음":
                            continue

                        if champ not in sixman_champs:
                            sixman_champs[champ] = {
                                "champion": champ,
                                "games": 0, "wins": 0, "losses": 0,
                                "kills": 0, "deaths": 0, "assists": 0,
                                "level": 0, "gold": 0, "gold_per_min": 0,
                                "damage": 0, "gold_share": 0, "damage_per_gold": 0,
                                "total_game_time": 0
                            }

                        sc = sixman_champs[champ]
                        sc["games"] += 1
                        sc["kills"] += player.get("kills", 0)
                        sc["deaths"] += player.get("deaths", 0)
                        sc["assists"] += player.get("assists", 0)
                        sc["level"] += player.get("level", 0)
                        sc["gold"] += player.get("total_gold", 0)
                        sc["gold_per_min"] += player.get("gold_per_min", 0)
                        sc["damage"] += player.get("damage", 0)
                        sc["gold_share"] += player.get("gold_share", 0)
                        sc["damage_per_gold"] += player.get("damage_per_gold", 0)
                        sc["total_game_time"] += game_minutes

                        if team_key == "team1":
                            if is_win:
                                sc["wins"] += 1
                            else:
                                sc["losses"] += 1
                        else:
                            if is_win:
                                sc["losses"] += 1
                            else:
                                sc["wins"] += 1

    for position in ["탑", "정글", "미드", "원딜", "서폿"]:
        if position in by_position:
            champs = sorted(by_position[position], key=lambda x: x["games"], reverse=True)[:5]

            players = position_players.get(position, [])
            player_str = ", ".join(players) if players else "미등록"

            # 테이블 (챔피언, 승패, 승률, KDA, 평균레벨, 분당골드, 분당딜, 골드비중, 골드대비딜)
            table = "```\n"
            table += f"{'CHAMP':<8} {'W-L':<5} {'WR%':>4} {'KDA':>4} {'LV':>3} {'G/M':>4} {'D/M':>5} {'G%':>4} {'D/G':>5}\n"
            table += f"{'-'*8} {'-'*5} {'-'*4} {'-'*4} {'-'*3} {'-'*4} {'-'*5} {'-'*4} {'-'*5}\n"

            for c in champs:
                champ_name = c['champion'][:8]
                record = f"{c['wins']}-{c['losses']}"
                win_pct = f"{c['win_rate']:.0f}"
                kda = f"{c['avg_kda']:.1f}"
                level = f"{c['avg_level']:.0f}"
                gpm = f"{c['avg_gold_per_min']:.0f}"
                dpm = f"{c['avg_damage_per_min']:.0f}"
                gs = f"{c['avg_gold_share']:.0f}"
                dpg = f"{c['avg_damage_per_gold']:.1f}"
                table += f"{champ_name:<8} {record:<5} {win_pct:>4} {kda:>4} {level:>3} {gpm:>4} {dpm:>5} {gs:>4} {dpg:>5}\n"

            table += "```"

            embed.add_field(
                name=f"{position_emojis.get(position, '🎮')} {position} ({player_str})",
                value=table,
                inline=False
            )

    # 식스맨 섹션
    if sixman_players and sixman_champs:
        sixman_list = []
        for champ, sc in sixman_champs.items():
            games = sc["games"]
            win_rate = (sc["wins"] / games * 100) if games > 0 else 0
            avg_kda = (sc["kills"] + sc["assists"]) / max(sc["deaths"], 1)
            avg_level = sc["level"] / games if games > 0 else 0
            avg_gold_per_min = sc["gold_per_min"] / games if games > 0 else 0
            avg_damage_per_min = (sc["damage"] / sc["total_game_time"]) if sc["total_game_time"] > 0 else 0
            avg_gold_share = sc["gold_share"] / games if games > 0 else 0
            avg_damage_per_gold = sc["damage_per_gold"] / games if games > 0 else 0

            sixman_list.append({
                "champion": champ,
                "games": games,
                "wins": sc["wins"],
                "losses": sc["losses"],
                "win_rate": win_rate,
                "avg_kda": avg_kda,
                "avg_level": avg_level,
                "avg_gold_per_min": avg_gold_per_min,
                "avg_damage_per_min": avg_damage_per_min,
                "avg_gold_share": avg_gold_share,
                "avg_damage_per_gold": avg_damage_per_gold
            })

        sixman_sorted = sorted(sixman_list, key=lambda x: x["games"], reverse=True)[:5]
        player_str = ", ".join(sixman_players)

        table = "```\n"
        table += f"{'CHAMP':<8} {'W-L':<5} {'WR%':>4} {'KDA':>4} {'LV':>3} {'G/M':>4} {'D/M':>5} {'G%':>4} {'D/G':>5}\n"
        table += f"{'-'*8} {'-'*5} {'-'*4} {'-'*4} {'-'*3} {'-'*4} {'-'*5} {'-'*4} {'-'*5}\n"

        for c in sixman_sorted:
            champ_name = c['champion'][:8]
            record = f"{c['wins']}-{c['losses']}"
            win_pct = f"{c['win_rate']:.0f}"
            kda = f"{c['avg_kda']:.1f}"
            level = f"{c['avg_level']:.0f}"
            gpm = f"{c['avg_gold_per_min']:.0f}"
            dpm = f"{c['avg_damage_per_min']:.0f}"
            gs = f"{c['avg_gold_share']:.0f}"
            dpg = f"{c['avg_damage_per_gold']:.1f}"
            table += f"{champ_name:<8} {record:<5} {win_pct:>4} {kda:>4} {level:>3} {gpm:>4} {dpm:>5} {gs:>4} {dpg:>5}\n"

        table += "```"

        embed.add_field(
            name=f"{position_emojis.get('식스맨', '🔄')} 식스맨 ({player_str})",
            value=table,
            inline=False
        )
    elif sixman_players:
        player_str = ", ".join(sixman_players)
        embed.add_field(
            name=f"🔄 식스맨 ({player_str})",
            value="```\n데이터 없음\n```",
            inline=False
        )

    # 범례
    embed.add_field(
        name="📖 범례",
        value="`WR%`승률 `LV`평균레벨 `G/M`분당골드 `D/M`분당딜 `G%`골드비중 `D/G`100골드당딜",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name="player")
@has_admin_role()
async def player_stats_cmd(ctx):
    """
    선수별 통계를 조회합니다.
    사용법: !선수통계
    """
    data = load_data()
    if not data["matches"]:
        await ctx.send("📊 아직 등록된 경기 기록이 없습니다.")
        return

    stats = calculate_stats(data["matches"], "all")
    if not stats or not stats["player_stats"]:
        await ctx.send("📊 선수 기록이 없습니다.")
        return

    embed = discord.Embed(
        color=0xe67e22
    )

    filtered_players = stats["player_stats"]

    if not filtered_players:
        await ctx.send("📊 등록된 팀 선수의 기록이 없습니다.")
        return

    position_emojis = {"탑": "🛡️", "정글": "🌲", "미드": "⚡", "원딜": "🏹", "서폿": "💚", "식스맨": "🔄"}

    # 닉네임 축약 함수
    def truncate_name(name, max_len=6):
        if len(name) > max_len:
            return name[:max_len-2] + ".."
        return name

    # 포지션별로 그룹화 (주전 선수)
    main_positions = ["탑", "정글", "미드", "원딜", "서폿"]
    by_position = {pos: [] for pos in main_positions}
    sixman_list = []

    for nickname, ps in filtered_players.items():
        position = TEAM_PLAYERS.get(nickname, "")

        games = ps["games"]
        win_rate = (ps["wins"] / games * 100) if games > 0 else 0
        avg_kda = (ps["kills"] + ps["assists"]) / max(ps["deaths"], 1)
        avg_level = ps["level"] / games if games > 0 else 0
        avg_gold_per_min = ps["gold_per_min"] / games if games > 0 else 0
        avg_damage_per_min = ps["damage"] / ps["total_game_time"] if ps["total_game_time"] > 0 else 0
        avg_gold_share = ps["gold_share"] / games if games > 0 else 0
        avg_damage_per_gold = ps["damage_per_gold"] / games if games > 0 else 0

        player_data = {
            "nickname": nickname,
            "games": games,
            "wins": ps["wins"],
            "losses": ps["losses"],
            "win_rate": win_rate,
            "avg_kda": avg_kda,
            "avg_level": avg_level,
            "avg_gold_per_min": avg_gold_per_min,
            "avg_damage_per_min": avg_damage_per_min,
            "avg_gold_share": avg_gold_share,
            "avg_damage_per_gold": avg_damage_per_gold
        }

        if position == "식스맨":
            sixman_list.append(player_data)
        elif position in main_positions:
            by_position[position].append(player_data)

    # 주전 선수 테이블
    for position in main_positions:
        if by_position[position]:
            players = sorted(by_position[position], key=lambda x: x["games"], reverse=True)

            # 해당 포지션 선수 이름
            player_names = [p["nickname"] for p in players]
            player_str = ", ".join(player_names)

            table = "```\n"
            table += f"{'PLAYER':<10} {'W-L':<5} {'WR%':>4} {'KDA':>4} {'LV':>3} {'G/M':>4} {'D/M':>5} {'G%':>4} {'D/G':>5}\n"
            table += f"{'-'*10} {'-'*5} {'-'*4} {'-'*4} {'-'*3} {'-'*4} {'-'*5} {'-'*4} {'-'*5}\n"

            for p in players:
                name = truncate_name(p['nickname'], 6)
                record = f"{p['wins']}-{p['losses']}"
                win_pct = f"{p['win_rate']:.0f}"
                kda = f"{p['avg_kda']:.1f}"
                level = f"{p['avg_level']:.0f}"
                gpm = f"{p['avg_gold_per_min']:.0f}"
                dpm = f"{p['avg_damage_per_min']:.0f}"
                gs = f"{p['avg_gold_share']:.0f}"
                dpg = f"{p['avg_damage_per_gold']:.1f}"
                table += f"{name:<10} {record:<5} {win_pct:>4} {kda:>4} {level:>3} {gpm:>4} {dpm:>5} {gs:>4} {dpg:>5}\n"

            table += "```"

            embed.add_field(
                name=f"{position_emojis.get(position, '🎮')} {position} ({player_str})",
                value=table,
                inline=False
            )

    # 식스맨 테이블 (별도 그룹)
    if sixman_list:
        sixman_sorted = sorted(sixman_list, key=lambda x: x["games"], reverse=True)
        player_names = [p["nickname"] for p in sixman_sorted]
        player_str = ", ".join(player_names)

        table = "```\n"
        table += f"{'PLAYER':<10} {'W-L':<5} {'WR%':>4} {'KDA':>4} {'LV':>3} {'G/M':>4} {'D/M':>5} {'G%':>4} {'D/G':>5}\n"
        table += f"{'-'*10} {'-'*5} {'-'*4} {'-'*4} {'-'*3} {'-'*4} {'-'*5} {'-'*4} {'-'*5}\n"

        for p in sixman_sorted:
            name = truncate_name(p['nickname'], 6)
            record = f"{p['wins']}-{p['losses']}"
            win_pct = f"{p['win_rate']:.0f}"
            kda = f"{p['avg_kda']:.1f}"
            level = f"{p['avg_level']:.0f}"
            gpm = f"{p['avg_gold_per_min']:.0f}"
            dpm = f"{p['avg_damage_per_min']:.0f}"
            gs = f"{p['avg_gold_share']:.0f}"
            dpg = f"{p['avg_damage_per_gold']:.1f}"
            table += f"{name:<10} {record:<5} {win_pct:>4} {kda:>4} {level:>3} {gpm:>4} {dpm:>5} {gs:>4} {dpg:>5}\n"

        table += "```"

        embed.add_field(
            name=f"🔄 식스맨 ({player_str})",
            value=table,
            inline=False
        )
    else:
        # 식스맨 등록은 되어 있지만 데이터가 없는 경우
        sixman_registered = [nick for nick, pos in TEAM_PLAYERS.items() if pos == "식스맨"]
        if sixman_registered:
            embed.add_field(
                name=f"🔄 식스맨 ({', '.join(sixman_registered)})",
                value="```\n데이터 없음\n```",
                inline=False
            )

    # 범례
    embed.add_field(
        name="📖 범례",
        value="`WR%`승률 `LV`평균레벨 `G/M`분당골드 `D/M`분당딜 `G%`골드비중 `D/G`100골드당딜",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name="recent")
@has_admin_role()
async def recent_matches(ctx, count: int = 5):
    """
    최근 경기 기록을 조회합니다.
    사용법: !최근경기 [개수]
    """
    data = load_data()
    matches = data.get("matches", [])

    if not matches:
        await ctx.send("📊 아직 등록된 경기 기록이 없습니다.")
        return

    count = min(count, 10)  # 최대 10개
    recent = matches[-count:][::-1]

    embed = discord.Embed(
        color=0x3498db
    )

    for i, match in enumerate(recent, 1):
        is_win = match["result"] == "승리"
        emoji = "🏆" if is_win else "💀"
        color_bar = "🟢" if is_win else "🔴"

        team1 = match.get("team1", {})
        team1_kda = f"{team1.get('total_kills', 0)}/{team1.get('total_deaths', 0)}/{team1.get('total_assists', 0)}"
        team1_gold = team1.get('team_total_gold', 0)

        value = f"```\n"
        value += f"⏱️ {match.get('game_time', '?')} | 팀 KDA: {team1_kda}\n"
        value += f"💰 팀 골드: {team1_gold:,}G\n"
        value += f"```"

        embed.add_field(
            name=f"{color_bar} #{i} {match['date']} {emoji} {match['result']}",
            value=value,
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name="match")
@has_admin_role()
async def match_detail(ctx, index: int = 1):
    """
    특정 경기의 상세 정보를 조회합니다.
    사용법: !경기상세 [번호] (1이 가장 최근)
    """
    data = load_data()
    matches = data.get("matches", [])

    if not matches:
        await ctx.send("📊 아직 등록된 경기 기록이 없습니다.")
        return

    if index < 1 or index > len(matches):
        await ctx.send(f"❌ 1~{len(matches)} 사이의 번호를 입력해주세요.")
        return

    match = matches[-index]  # 최신이 1번
    embed = create_match_embed(match)
    await ctx.send(embed=embed)


@bot.command(name="team")
@has_admin_role()
async def team_stats_cmd(ctx):
    """
    팀 전체 통계를 조회합니다 (기간 제한 없음).
    사용법: !팀통계
    """
    data = load_data()
    matches = data.get("matches", [])

    if not matches:
        await ctx.send("📊 아직 등록된 경기 기록이 없습니다.")
        return

    # 기본 통계
    total_games = len(matches)
    wins = sum(1 for m in matches if m["result"] == "승리")
    losses = total_games - wins
    win_rate = (wins / total_games * 100) if total_games > 0 else 0

    # 진영별 통계
    blue_games = [m for m in matches if m.get("side") == "blue"]
    red_games = [m for m in matches if m.get("side") == "red"]

    blue_wins = sum(1 for m in blue_games if m["result"] == "승리")
    red_wins = sum(1 for m in red_games if m["result"] == "승리")

    blue_total = len(blue_games)
    red_total = len(red_games)

    blue_win_rate = (blue_wins / blue_total * 100) if blue_total > 0 else 0
    red_win_rate = (red_wins / red_total * 100) if red_total > 0 else 0

    # 게임 시간 통계
    game_times = []
    for m in matches:
        game_time_str = m.get("game_time", "0:00")
        try:
            parts = game_time_str.split(":")
            if len(parts) == 2:
                minutes = int(parts[0]) + int(parts[1]) / 60
                game_times.append(minutes)
        except (ValueError, AttributeError):
            pass

    avg_game_time = sum(game_times) / len(game_times) if game_times else 0
    min_game_time = min(game_times) if game_times else 0
    max_game_time = max(game_times) if game_times else 0

    # 팀 평균 KDA, 골드
    total_kills = 0
    total_deaths = 0
    total_assists = 0
    total_gold = 0

    for m in matches:
        team1 = m.get("team1", {})
        total_kills += team1.get("total_kills", 0)
        total_deaths += team1.get("total_deaths", 0)
        total_assists += team1.get("total_assists", 0)
        total_gold += team1.get("team_total_gold", 0)

    avg_kills = total_kills / total_games if total_games > 0 else 0
    avg_deaths = total_deaths / total_games if total_games > 0 else 0
    avg_assists = total_assists / total_games if total_games > 0 else 0
    avg_gold = total_gold / total_games if total_games > 0 else 0
    team_kda = (total_kills + total_assists) / max(total_deaths, 1)

    # 연승/연패 기록
    current_streak = 0
    streak_type = None
    max_win_streak = 0
    max_lose_streak = 0
    temp_streak = 0
    prev_result = None

    for m in matches:
        result = m["result"]
        if result == prev_result:
            temp_streak += 1
        else:
            if prev_result == "승리":
                max_win_streak = max(max_win_streak, temp_streak)
            elif prev_result == "패배":
                max_lose_streak = max(max_lose_streak, temp_streak)
            temp_streak = 1
            prev_result = result

    # 마지막 스트릭 처리
    if prev_result == "승리":
        max_win_streak = max(max_win_streak, temp_streak)
    elif prev_result == "패배":
        max_lose_streak = max(max_lose_streak, temp_streak)

    # 현재 연승/연패
    for m in reversed(matches):
        if streak_type is None:
            streak_type = m["result"]
            current_streak = 1
        elif m["result"] == streak_type:
            current_streak += 1
        else:
            break

    # 임베드 생성
    if win_rate >= 60:
        color = 0x2ecc71
    elif win_rate >= 50:
        color = 0x3498db
    elif win_rate >= 40:
        color = 0xf39c12
    else:
        color = 0xe74c3c

    embed = discord.Embed(
        color=color
    )

    # 전체 성적
    filled = int(win_rate / 10)
    overall = f"```\n"
    overall += f"🏆 총 {total_games}게임 | {wins}승 {losses}패\n"
    overall += f"📈 승률: {win_rate:.1f}%\n"
    overall += f"```"

    embed.add_field(name="📊 전체 성적", value=overall, inline=False)

    # 진영별 승률
    side_stats = f"```\n"
    side_stats += f"🔵 블루 진영: {blue_wins}승 {blue_total - blue_wins}패 ({blue_win_rate:.1f}%)\n"
    side_stats += f"🔴 레드 진영: {red_wins}승 {red_total - red_wins}패 ({red_win_rate:.1f}%)\n"
    side_stats += f"```"

    embed.add_field(name="🗺️ 진영별 승률", value=side_stats, inline=False)

    # 게임 시간 통계
    def format_time(minutes):
        m = int(minutes)
        s = int((minutes - m) * 60)
        return f"{m}:{s:02d}"

    time_stats = f"```\n"
    time_stats += f"⏱️ 평균 시간: {format_time(avg_game_time)}\n"
    time_stats += f"⚡ 최단 시간: {format_time(min_game_time)}\n"
    time_stats += f"🐢 최장 시간: {format_time(max_game_time)}\n"
    time_stats += f"```"

    embed.add_field(name="⏰ 게임 시간", value=time_stats, inline=True)

    # 연승/연패 기록
    streak_emoji = "🔥" if streak_type == "승리" else "❄️"
    streak_stats = f"```\n"
    streak_stats += f"🏆 최다 연승: {max_win_streak}연승\n"
    streak_stats += f"💀 최다 연패: {max_lose_streak}연패\n"
    streak_stats += f"```"

    embed.add_field(name="📈 연승/연패", value=streak_stats, inline=True)

    # 팀 평균 스탯
    avg_stats = f"```\n"
    avg_stats += f"⚔️ 팀 평균 KDA: {avg_kills:.1f}/{avg_deaths:.1f}/{avg_assists:.1f}\n"
    avg_stats += f"📊 팀 KDA: {team_kda:.2f}\n"
    avg_stats += f"💰 평균 골드: {avg_gold:,.0f}G\n"
    avg_stats += f"```"

    embed.add_field(name="📋 팀 평균 스탯", value=avg_stats, inline=False)

    # 최근 10경기 트렌드
    # recent_10 = matches[-10:]
    # trend = ""
    # for m in recent_10:
    #     if m["result"] == "승리":
    #         trend += "🟢 "
    #     else:
    #         trend += "🔴 "
    # 
    # embed.add_field(name="📜 최근 10경기", value=trend or "데이터 없음", inline=False)

    # embed.set_footer(text="💡 !전적, !챔피언통계, !선수통계로 상세 정보 확인")

    await ctx.send(embed=embed)

@bot.command(name="commands")
@has_admin_role()
async def help_command(ctx):
    embed = discord.Embed(
        color=0x3498db
    )

    embed.add_field(
        name="!register",
        value="이미지를 첨부하여 경기 결과를 등록합니다.",
        inline=False
    )
    embed.add_field(
        name="!recent [개수]",
        value="최근 경기 목록을 조회합니다. (기본: 5경기)",
        inline=False
    )
    embed.add_field(
        name="!match [번호]",
        value="특정 경기의 상세 정보를 조회합니다.",
        inline=False
    )
    embed.add_field(
        name="!champion",
        value="챔피언별 통계를 조회합니다.",
        inline=False
    )
    embed.add_field(
        name="!player",
        value="선수별 통계를 조회합니다.",
        inline=False
    )
    embed.add_field(
        name="!team",
        value="팀 전체 통계를 조회합니다.",
        inline=False
    )

    await ctx.send(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)