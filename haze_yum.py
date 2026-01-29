
# haze_yum.py
import discord
from discord.ext import commands
import aiohttp
import ssl
import certifi
import os
import json
import time
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv
from google import genai

# SSL 컨텍스트 생성
ssl_context = ssl.create_default_context(cafile=certifi.where())

# ==========================================
# [설정]
# ==========================================
load_dotenv()

TOKEN = os.getenv("YUM_BOT_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
YUM_CHANNEL_ID = int(os.getenv("YUM_CHANNEL_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 클라이언트
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# 지역 설정 (한국)
REGION = "kr"
REGION_V5 = "asia"  # account-v1, match-v5 API용

# ==========================================
# 캐시 설정
# ==========================================
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player_cache.json")
CACHE_EXPIRY_DAYS = 7
CACHE_EXPIRY_SECONDS = CACHE_EXPIRY_DAYS * 24 * 60 * 60  # 7일 = 604800초

def load_cache() -> dict:
    """캐시 파일 로드"""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[캐시] 로드 오류: {e}")
        return {}


def save_cache(cache: dict) -> None:
    """캐시 파일 저장"""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[캐시] 저장 오류: {e}")


def get_cache_key(riot_id: str) -> str:
    """캐시 키 생성 (소문자로 정규화)"""
    return riot_id.lower().strip()


def get_cached_player(riot_id: str) -> tuple[dict | None, bool]:
    """
    캐시에서 플레이어 데이터 조회
    Returns: (data, is_cached) - data가 None이면 캐시 미스, is_cached는 캐시 사용 여부
    """
    cache = load_cache()
    key = get_cache_key(riot_id)

    if key not in cache:
        return None, False

    entry = cache[key]
    cached_time = entry.get("cached_at", 0)
    current_time = time.time()

    # 7일 경과 체크
    if current_time - cached_time > CACHE_EXPIRY_SECONDS:
        print(f"[캐시] {riot_id} - 만료됨 (7일 초과)")
        return None, False

    remaining_days = (CACHE_EXPIRY_SECONDS - (current_time - cached_time)) / 86400
    print(f"[캐시] {riot_id} - 히트! (남은 기간: {remaining_days:.1f}일)")
    return entry.get("data"), True


def set_cached_player(riot_id: str, data: dict, ai_analysis: str | None = None) -> None:
    """플레이어 데이터를 캐시에 저장"""
    cache = load_cache()
    key = get_cache_key(riot_id)

    cache[key] = {
        "cached_at": time.time(),
        "cached_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": data,
        "ai_analysis": ai_analysis
    }

    save_cache(cache)
    print(f"[캐시] {riot_id} - 저장 완료")


def get_cached_ai_analysis(riot_id: str) -> str | None:
    """캐시된 AI 분석 결과 조회"""
    cache = load_cache()
    key = get_cache_key(riot_id)

    if key in cache:
        return cache[key].get("ai_analysis")
    return None


def clear_expired_cache() -> int:
    """만료된 캐시 항목 정리"""
    cache = load_cache()
    current_time = time.time()

    expired_keys = [
        key for key, entry in cache.items()
        if current_time - entry.get("cached_at", 0) > CACHE_EXPIRY_SECONDS
    ]

    for key in expired_keys:
        del cache[key]

    if expired_keys:
        save_cache(cache)
        print(f"[캐시] 만료된 항목 {len(expired_keys)}개 정리됨")

    return len(expired_keys)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 역할 확인을 위해 필요

bot = commands.Bot(command_prefix="!", intents=intents)

def has_admin_role():
    """ADMIN_ROLE_ID 권한 체크 + 채널 체크 데코레이터"""
    async def predicate(ctx):
        # 채널 체크
        if YUM_CHANNEL_ID and ctx.channel.id != YUM_CHANNEL_ID:
            return False  # 다른 채널에서는 조용히 무시

        # 권한 체크
        user_role_ids = [role.id for role in ctx.author.roles]
        if ADMIN_ROLE_ID not in user_role_ids:
            await ctx.send("🚫 이 명령어는 관리자만 사용할 수 있습니다.", delete_after=5)
            return False
        return True
    return commands.check(predicate)

# ==========================================
# Riot API 헬퍼 함수
# ==========================================
async def get_account_by_riot_id(game_name: str, tag_line: str) -> dict | None:
    """Riot ID (게임이름#태그)로 계정 정보 조회"""
    url = f"https://{REGION_V5}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_summoner_by_puuid(puuid: str) -> dict | None:
    """PUUID로 소환사 정보 조회"""
    url = f"https://{REGION}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_league_entries(puuid: str) -> list:
    """소환사의 랭크 정보 조회 (PUUID 사용)"""
    url = f"https://{REGION}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


async def get_champion_mastery(puuid: str, count: int = 3) -> list:
    """챔피언 숙련도 상위 조회"""
    url = f"https://{REGION}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


async def get_recent_matches(puuid: str, count: int = 20, queue_type: str = "ranked") -> list:
    """최근 매치 ID 조회"""
    if queue_type == "ranked":
        url = f"https://{REGION_V5}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={count}&type=ranked"
    else:
        url = f"https://{REGION_V5}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count={count}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


async def get_match_detail(match_id: str) -> dict | None:
    """매치 상세 정보 조회"""
    url = f"https://{REGION_V5}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_match_timeline(match_id: str) -> dict | None:
    """매치 타임라인 조회 (Match-V5 Timeline)"""
    url = f"https://{REGION_V5}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_current_game(puuid: str) -> dict | None:
    """현재 진행 중인 게임 조회 (Spectator-V5)"""
    url = f"https://{REGION}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_player_challenges(puuid: str) -> dict | None:
    """플레이어 도전과제 정보 조회 (Challenges-V1)"""
    url = f"https://{REGION}.api.riotgames.com/lol/challenges/v1/player-data/{puuid}"
    headers = {"X-Riot-Token": RIOT_API_KEY}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


# ==========================================
# 챔피언 ID → 이름 매핑 (Data Dragon)
# ==========================================
CHAMPION_MAP = {}


async def load_champion_map():
    """Data Dragon에서 챔피언 데이터 로드"""
    global CHAMPION_MAP
    url = "https://ddragon.leagueoflegends.com/cdn/14.24.1/data/ko_KR/champion.json"

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                for champ_name, champ_data in data["data"].items():
                    CHAMPION_MAP[int(champ_data["key"])] = champ_data["name"]


def get_champion_name(champion_id: int) -> str:
    return CHAMPION_MAP.get(champion_id, f"Unknown({champion_id})")


# ==========================================
# 타임라인 분석 함수
# ==========================================
def analyze_timeline(timeline_data: dict, puuid: str, participant_id: int) -> dict:
    """타임라인 데이터에서 상세 분석"""
    analysis = {
        "early_kills": 0,  # 10분 전 킬
        "early_deaths": 0,  # 10분 전 데스
        "early_assists": 0,  # 10분 전 어시스트
        "first_blood_time": None,
        "cs_at_10": 0,
        "cs_at_15": 0,
        "gold_at_10": 0,
        "gold_at_15": 0,
        "lane_kills": 0,  # 라인전 킬
        "roam_kills": 0,  # 로밍 킬
        "solo_kills": 0,  # 솔로킬
        "ganks_received": 0,  # 갱 당한 횟수
        "tower_plates": 0,  # 타워 플레이트
        "jungle_invades": 0,  # 정글 침범
    }

    if not timeline_data or "info" not in timeline_data:
        return analysis

    frames = timeline_data["info"].get("frames", [])

    for frame in frames:
        timestamp_min = frame.get("timestamp", 0) // 60000  # 밀리초 -> 분

        # 참가자 프레임 데이터
        participant_frames = frame.get("participantFrames", {})
        player_frame = participant_frames.get(str(participant_id), {})

        if timestamp_min == 10:
            analysis["cs_at_10"] = player_frame.get("minionsKilled", 0) + player_frame.get("jungleMinionsKilled", 0)
            analysis["gold_at_10"] = player_frame.get("totalGold", 0)
        elif timestamp_min == 15:
            analysis["cs_at_15"] = player_frame.get("minionsKilled", 0) + player_frame.get("jungleMinionsKilled", 0)
            analysis["gold_at_15"] = player_frame.get("totalGold", 0)

        # 이벤트 분석
        events = frame.get("events", [])
        for event in events:
            event_type = event.get("type")
            event_time = event.get("timestamp", 0) // 60000

            if event_type == "CHAMPION_KILL":
                killer_id = event.get("killerId")
                victim_id = event.get("victimId")
                assisting_ids = event.get("assistingParticipantIds", [])

                if event_time <= 10:
                    if killer_id == participant_id:
                        analysis["early_kills"] += 1
                    if victim_id == participant_id:
                        analysis["early_deaths"] += 1
                    if participant_id in assisting_ids:
                        analysis["early_assists"] += 1

                # 솔로킬 체크
                if killer_id == participant_id and len(assisting_ids) == 0:
                    analysis["solo_kills"] += 1

            elif event_type == "TURRET_PLATE_DESTROYED":
                if event.get("killerId") == participant_id:
                    analysis["tower_plates"] += 1

    return analysis


# ==========================================
# 분석 함수
# ==========================================
async def analyze_player(riot_id: str, force_refresh: bool = False) -> tuple[dict | None, bool, str | None]:
    """
    플레이어 분석 (닉네임#태그 형식)
    Returns: (data, is_cached, cached_ai_analysis)
    """
    # 캐시 확인 (강제 새로고침이 아닌 경우)
    if not force_refresh:
        cached_data, is_cached = get_cached_player(riot_id)
        if cached_data is not None:
            cached_ai = get_cached_ai_analysis(riot_id)
            return cached_data, True, cached_ai

    # 닉네임 파싱
    if "#" in riot_id:
        game_name, tag_line = riot_id.rsplit("#", 1)
    else:
        game_name = riot_id
        tag_line = "KR1"  # 기본 태그

    # 계정 정보 조회
    account = await get_account_by_riot_id(game_name, tag_line)
    if not account:
        return None, False, None

    puuid = account["puuid"]

    # 소환사 정보 조회
    summoner = await get_summoner_by_puuid(puuid)
    if not summoner:
        return None, False, None

    # 랭크 정보 조회 (PUUID 사용)
    leagues = await get_league_entries(puuid)

    # 솔로랭크 정보 추출
    solo_rank = None
    flex_rank = None
    for league in leagues:
        if league["queueType"] == "RANKED_SOLO_5x5":
            solo_rank = league
        elif league["queueType"] == "RANKED_FLEX_SR":
            flex_rank = league

    # 챔피언 숙련도 상위 5 (전체 모스트)
    masteries = await get_champion_mastery(puuid, 5)

    # 도전과제 정보 조회 (Challenges-V1)
    challenges_data = await get_player_challenges(puuid)

    # 현재 게임 중인지 확인 (Spectator-V5)
    current_game = await get_current_game(puuid)

    # 최근 랭크 게임 매치 데이터 수집 (20게임)
    match_ids = await get_recent_matches(puuid, 20)

    wins = 0
    losses = 0
    recent_champions = []  # 최근 픽한 챔피언들
    recent_matches_data = []  # 상세 매치 데이터

    # 통계 집계용 변수
    total_stats = {
        "turret_kills": 0,
        "turret_takedowns": 0,
        "dragon_kills": 0,
        "baron_kills": 0,
        "first_blood_kills": 0,
        "first_blood_assists": 0,
        "double_kills": 0,
        "triple_kills": 0,
        "quadra_kills": 0,
        "penta_kills": 0,
        "damage_to_objectives": 0,
        "damage_self_mitigated": 0,
        "total_damage_taken": 0,
        "time_ccing_others": 0,
        "wards_placed": 0,
        "wards_killed": 0,
        "control_wards_placed": 0,
        "skillshots_dodged": 0,
        "skillshots_hit": 0,
        "solo_kills": 0,
        "early_kills": 0,
        "early_deaths": 0,
        "cs_at_10_total": 0,
        "gold_at_10_total": 0,
        "games_with_timeline": 0,
    }

    for match_id in match_ids[:20]:
        match_data = await get_match_detail(match_id)
        if match_data:
            participants = match_data["info"]["participants"]
            game_duration = match_data["info"]["gameDuration"]

            for idx, p in enumerate(participants):
                if p["puuid"] == puuid:
                    participant_id = idx + 1
                    is_win = p["win"]
                    if is_win:
                        wins += 1
                    else:
                        losses += 1

                    champion_id = p["championId"]
                    champion_name = get_champion_name(champion_id)
                    recent_champions.append(champion_name)

                    # challenges 객체에서 추가 통계 추출
                    challenges = p.get("challenges", {})

                    # 타임라인 분석 (처음 5게임만 - API 제한 고려)
                    timeline_analysis = {}
                    if len(recent_matches_data) < 5:
                        timeline_data = await get_match_timeline(match_id)
                        if timeline_data:
                            timeline_analysis = analyze_timeline(timeline_data, puuid, participant_id)
                            total_stats["games_with_timeline"] += 1
                            total_stats["early_kills"] += timeline_analysis.get("early_kills", 0)
                            total_stats["early_deaths"] += timeline_analysis.get("early_deaths", 0)
                            total_stats["cs_at_10_total"] += timeline_analysis.get("cs_at_10", 0)
                            total_stats["gold_at_10_total"] += timeline_analysis.get("gold_at_10", 0)
                            total_stats["solo_kills"] += timeline_analysis.get("solo_kills", 0)

                    # 상세 매치 데이터 저장 (모든 필드 포함)
                    match_entry = {
                        "champion": champion_name,
                        "champion_id": champion_id,
                        "win": is_win,
                        "kills": p["kills"],
                        "deaths": p["deaths"],
                        "assists": p["assists"],
                        "cs": p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0),
                        "damage": p["totalDamageDealtToChampions"],
                        "gold": p["goldEarned"],
                        "vision_score": p.get("visionScore", 0),
                        "position": p.get("teamPosition", "UNKNOWN"),
                        "game_duration": game_duration,
                        "kda": (p["kills"] + p["assists"]) / max(p["deaths"], 1),
                        # 새로 추가된 필드들
                        "turret_kills": p.get("turretKills", 0),
                        "turret_takedowns": p.get("turretTakedowns", 0),
                        "dragon_kills": p.get("dragonKills", 0),
                        "baron_kills": p.get("baronKills", 0),
                        "first_blood_kill": p.get("firstBloodKill", False),
                        "first_blood_assist": p.get("firstBloodAssist", False),
                        "double_kills": p.get("doubleKills", 0),
                        "triple_kills": p.get("tripleKills", 0),
                        "quadra_kills": p.get("quadraKills", 0),
                        "penta_kills": p.get("pentaKills", 0),
                        "damage_to_objectives": p.get("damageDealtToObjectives", 0),
                        "damage_self_mitigated": p.get("damageSelfMitigated", 0),
                        "total_damage_taken": p.get("totalDamageTaken", 0),
                        "time_ccing_others": p.get("timeCCingOthers", 0),
                        "wards_placed": p.get("wardsPlaced", 0),
                        "wards_killed": p.get("wardsKilled", 0),
                        "control_wards_placed": p.get("detectorWardsPlaced", 0),
                        # challenges 객체에서 추출
                        "skillshots_dodged": challenges.get("skillshotsDodged", 0),
                        "skillshots_hit": challenges.get("skillshotsHit", 0),
                        "solo_kills": challenges.get("soloKills", 0),
                        "damage_per_minute": challenges.get("damagePerMinute", 0),
                        "gold_per_minute": challenges.get("goldPerMinute", 0),
                        "kda_challenge": challenges.get("kda", 0),
                        "kill_participation": challenges.get("killParticipation", 0),
                        "lane_minions_first_10": challenges.get("laneMinionsFirst10Minutes", 0),
                        "turret_plates_taken": challenges.get("turretPlatesTaken", 0),
                        "vision_score_per_minute": challenges.get("visionScorePerMinute", 0),
                        "early_laning_phase_gold": challenges.get("earlyLaningPhaseGoldExpAdvantage", 0),
                        "team_damage_percentage": challenges.get("teamDamagePercentage", 0),
                        # 타임라인 데이터
                        "timeline": timeline_analysis
                    }
                    recent_matches_data.append(match_entry)

                    # 총계 집계
                    total_stats["turret_kills"] += match_entry["turret_kills"]
                    total_stats["turret_takedowns"] += match_entry["turret_takedowns"]
                    total_stats["dragon_kills"] += match_entry["dragon_kills"]
                    total_stats["baron_kills"] += match_entry["baron_kills"]
                    total_stats["first_blood_kills"] += 1 if match_entry["first_blood_kill"] else 0
                    total_stats["first_blood_assists"] += 1 if match_entry["first_blood_assist"] else 0
                    total_stats["double_kills"] += match_entry["double_kills"]
                    total_stats["triple_kills"] += match_entry["triple_kills"]
                    total_stats["quadra_kills"] += match_entry["quadra_kills"]
                    total_stats["penta_kills"] += match_entry["penta_kills"]
                    total_stats["damage_to_objectives"] += match_entry["damage_to_objectives"]
                    total_stats["damage_self_mitigated"] += match_entry["damage_self_mitigated"]
                    total_stats["total_damage_taken"] += match_entry["total_damage_taken"]
                    total_stats["time_ccing_others"] += match_entry["time_ccing_others"]
                    total_stats["wards_placed"] += match_entry["wards_placed"]
                    total_stats["wards_killed"] += match_entry["wards_killed"]
                    total_stats["control_wards_placed"] += match_entry["control_wards_placed"]
                    total_stats["skillshots_dodged"] += match_entry["skillshots_dodged"]
                    total_stats["skillshots_hit"] += match_entry["skillshots_hit"]
                    break

    # 최근 모스트 계산 (최근 20게임 기준)
    champion_counter = Counter(recent_champions)
    recent_most = champion_counter.most_common(5)  # 상위 5챔피언

    # 챔피언별 상세 통계
    champion_stats = {}
    for match in recent_matches_data:
        champ = match["champion"]
        if champ not in champion_stats:
            champion_stats[champ] = {
                "games": 0, "wins": 0,
                "kills": 0, "deaths": 0, "assists": 0,
                "cs": 0, "damage": 0, "gold": 0,
                "total_duration": 0,
                "turret_kills": 0, "dragon_kills": 0, "baron_kills": 0,
                "first_bloods": 0, "solo_kills": 0,
                "wards_placed": 0, "control_wards": 0,
            }
        stats = champion_stats[champ]
        stats["games"] += 1
        stats["wins"] += 1 if match["win"] else 0
        stats["kills"] += match["kills"]
        stats["deaths"] += match["deaths"]
        stats["assists"] += match["assists"]
        stats["cs"] += match["cs"]
        stats["damage"] += match["damage"]
        stats["gold"] += match["gold"]
        stats["total_duration"] += match["game_duration"]
        stats["turret_kills"] += match["turret_kills"]
        stats["dragon_kills"] += match["dragon_kills"]
        stats["baron_kills"] += match["baron_kills"]
        stats["first_bloods"] += 1 if match["first_blood_kill"] else 0
        stats["solo_kills"] += match["solo_kills"]
        stats["wards_placed"] += match["wards_placed"]
        stats["control_wards"] += match["control_wards_placed"]

    # 포지션별 게임 수
    position_counter = Counter([m["position"] for m in recent_matches_data])
    main_position = position_counter.most_common(1)[0] if position_counter else ("UNKNOWN", 0)

    # 평균 KDA 계산
    total_kills = sum(m["kills"] for m in recent_matches_data)
    total_deaths = sum(m["deaths"] for m in recent_matches_data)
    total_assists = sum(m["assists"] for m in recent_matches_data)
    avg_kda = (total_kills + total_assists) / max(total_deaths, 1)

    # 게임 수
    total_games = len(recent_matches_data)

    # 평균 계산
    # 평균 계산
    avg_stats = {}
    if total_games > 0:
        # 분당 딜/골드 평균 계산
        dpm_list = [m.get("damage_per_minute", 0) for m in recent_matches_data if m.get("damage_per_minute", 0) > 0]
        gpm_list = [m.get("gold_per_minute", 0) for m in recent_matches_data if m.get("gold_per_minute", 0) > 0]
        avg_dpm = (sum(dpm_list) / len(dpm_list)) if dpm_list else 0
        avg_gpm = (sum(gpm_list) / len(gpm_list)) if gpm_list else 0

        avg_stats = {
            "avg_damage": sum(m["damage"] for m in recent_matches_data) / total_games,
            "avg_damage_taken": total_stats["total_damage_taken"] / total_games,
            "avg_vision_score": sum(m["vision_score"] for m in recent_matches_data) / total_games,
            "avg_wards_placed": total_stats["wards_placed"] / total_games,
            "avg_control_wards": total_stats["control_wards_placed"] / total_games,
            "avg_cs": sum(m["cs"] for m in recent_matches_data) / total_games,
            "avg_gold": sum(m["gold"] for m in recent_matches_data) / total_games,
            "avg_cc_time": total_stats["time_ccing_others"] / total_games,
            "avg_obj_damage": total_stats["damage_to_objectives"] / total_games,
            "avg_dpm": avg_dpm,  # 분당 딜량 추가
            "avg_gpm": avg_gpm,  # 분당 골드 추가
        }

    # 타임라인 기반 평균
    if total_stats["games_with_timeline"] > 0:
        avg_stats["avg_cs_at_10"] = total_stats["cs_at_10_total"] / total_stats["games_with_timeline"]
        avg_stats["avg_gold_at_10"] = total_stats["gold_at_10_total"] / total_stats["games_with_timeline"]
        avg_stats["avg_early_kills"] = total_stats["early_kills"] / total_stats["games_with_timeline"]
        avg_stats["avg_early_deaths"] = total_stats["early_deaths"] / total_stats["games_with_timeline"]

    result = {
        "riot_id": f"{game_name}#{tag_line}",
        "summoner_level": summoner["summonerLevel"],
        "solo_rank": solo_rank,
        "flex_rank": flex_rank,
        "top_champions": masteries,  # 전체 모스트 (숙련도)
        "recent_most": recent_most,  # 최근 모스트
        "recent_wins": wins,
        "recent_losses": losses,
        "recent_matches": recent_matches_data,
        "champion_stats": champion_stats,
        "main_position": main_position,
        "avg_kda": avg_kda,
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "total_assists": total_assists,
        # 새로 추가된 데이터
        "total_stats": total_stats,
        "avg_stats": avg_stats,
        "challenges_data": challenges_data,
        "current_game": current_game,
    }

    return result, False, None



async def generate_ai_analysis(player_data: dict) -> str | None:
    """Gemini AI로 플레이어 분석 코멘트 생성"""
    if not gemini_client:
        return None

    try:
        # 분석용 데이터 정리
        riot_id = player_data["riot_id"]
        solo_rank = player_data.get("solo_rank")
        rank_str = f"{solo_rank['tier']} {solo_rank['rank']} ({solo_rank['leaguePoints']}LP)" if solo_rank else "Unranked"

        recent_wins = player_data["recent_wins"]
        recent_losses = player_data["recent_losses"]
        total_games = recent_wins + recent_losses
        win_rate = (recent_wins / total_games * 100) if total_games > 0 else 0

        recent_most = player_data.get("recent_most", [])
        recent_most_str = ", ".join([f"{champ}({count}판)" for champ, count in recent_most[:5]])

        champion_stats = player_data.get("champion_stats", {})
        avg_kda = player_data.get("avg_kda", 0)
        main_pos = player_data.get("main_position", ("UNKNOWN", 0))
        total_stats = player_data.get("total_stats", {})
        avg_stats = player_data.get("avg_stats", {})

        # 챔피언별 상세 통계
        champ_details = []
        for champ, stats in champion_stats.items():
            if stats["games"] >= 2:
                wr = (stats["wins"] / stats["games"]) * 100
                kda = (stats["kills"] + stats["assists"]) / max(stats["deaths"], 1)
                avg_dmg = stats["damage"] / stats["games"]
                champ_details.append(
                    f"{champ}: {stats['games']}판 {wr:.0f}%승률, KDA {kda:.1f}, "
                    f"솔로킬 {stats['solo_kills']}회, 평균딜 {avg_dmg:.0f}"
                )

        # 플레이 스타일 분석용 추가 데이터
        first_blood_rate = (total_stats.get("first_blood_kills", 0) + total_stats.get("first_blood_assists", 0)) / max(total_games, 1) * 100
        avg_vision = avg_stats.get("avg_vision_score", 0)
        avg_damage = avg_stats.get("avg_damage", 0)
        avg_damage_taken = avg_stats.get("avg_damage_taken", 0)
        avg_cc_time = avg_stats.get("avg_cc_time", 0)
        avg_obj_damage = avg_stats.get("avg_obj_damage", 0)
        avg_dpm = avg_stats.get("avg_dpm", 0)  # 분당 딜량 추가
        avg_gpm = avg_stats.get("avg_gpm", 0)  # 분당 골드 추가
        
        # 타임라인 데이터
        avg_cs_10 = avg_stats.get("avg_cs_at_10", 0)
        avg_gold_10 = avg_stats.get("avg_gold_at_10", 0)
        avg_early_kills = avg_stats.get("avg_early_kills", 0)
        avg_early_deaths = avg_stats.get("avg_early_deaths", 0)

        # 도전과제 데이터
        challenges_data = player_data.get("challenges_data")
        challenge_str = ""
        if challenges_data:
            total_points = challenges_data.get("totalPoints", {})
            level = total_points.get("level", "NONE")
            pts = total_points.get("current", 0)
            challenge_str = f"도전과제 티어: {level} ({pts:,}점)"

        # 최근 매치에서 평균 킬관여율, 팀딜비중 계산
        recent_matches = player_data.get("recent_matches", [])
        avg_kill_participation = 0
        avg_team_damage_pct = 0
        if recent_matches:
            kp_list = [m.get("kill_participation", 0) for m in recent_matches if m.get("kill_participation")]
            tdp_list = [m.get("team_damage_percentage", 0) for m in recent_matches if m.get("team_damage_percentage")]
            if kp_list:
                avg_kill_participation = sum(kp_list) / len(kp_list) * 100
            if tdp_list:
                avg_team_damage_pct = sum(tdp_list) / len(tdp_list) * 100

        prompt = f"""리그 오브 레전드 플레이어 분석을 해주세요. 스크림 상대로 만났을 때 어떻게 대응해야 할지 조언해주세요.

플레이어: {riot_id}
랭크: {rank_str}
레벨: {player_data.get('summoner_level', 0)}
{challenge_str}

===== 기본 통계 =====
최근 전적: {recent_wins}승 {recent_losses}패 ({win_rate:.0f}%)
평균 KDA: {avg_kda:.2f}
주 포지션: {main_pos[0]} ({main_pos[1]}게임)
최근 모스트 챔피언: {recent_most_str}

===== 공격성 지표 =====
- 퍼스트 블러드 관여율: {first_blood_rate:.0f}%
- 솔로킬: 총 {total_stats.get("solo_kills", 0)}회
- 멀티킬: 더블 {total_stats.get("double_kills", 0)} | 트리플 {total_stats.get("triple_kills", 0)} | 쿼드라 {total_stats.get("quadra_kills", 0)} | 펜타 {total_stats.get("penta_kills", 0)}
- 평균 킬 관여율: {avg_kill_participation:.0f}%

===== 라인전 능력 (10분 기준) =====
- 평균 10분 CS: {avg_cs_10:.0f}
- 평균 10분 골드: {avg_gold_10:.0f}
- 10분 전 평균 킬: {avg_early_kills:.1f}회
- 10분 전 평균 데스: {avg_early_deaths:.1f}회

===== 오브젝트 & 스플릿 =====
- 타워 파괴: 총 {total_stats.get("turret_kills", 0)}개
- 타워 플레이트: 총 {total_stats.get("turret_takedowns", 0)}개
- 드래곤 킬 관여: {total_stats.get("dragon_kills", 0)}회
- 바론 킬 관여: {total_stats.get("baron_kills", 0)}회
- 평균 오브젝트 딜량: {avg_obj_damage:.0f}

===== 전투 능력 =====
- 평균 챔피언 딜량: {avg_damage:.0f}
- 분당 딜량 (DPM): {avg_dpm:.0f}
- 분당 골드 (GPM): {avg_gpm:.0f}
- 팀 내 딜 비중: {avg_team_damage_pct:.0f}%
- 평균 받은 피해: {avg_damage_taken:.0f}
- 평균 피해 감소량: {total_stats.get("damage_self_mitigated", 0) / max(total_games, 1):.0f}
- 평균 CC 시간: {avg_cc_time:.1f}초

===== 시야 싸움 =====
- 평균 시야 점수: {avg_vision:.1f}
- 평균 와드 설치: {avg_stats.get('avg_wards_placed', 0):.1f}개
- 평균 제어와드: {avg_stats.get('avg_control_wards', 0):.1f}개
- 와드 제거: 총 {total_stats.get("wards_killed", 0)}개

===== 스킬 (challenges 데이터) =====
- 스킬샷 명중: 총 {total_stats.get("skillshots_hit", 0)}회
- 스킬샷 회피: 총 {total_stats.get("skillshots_dodged", 0)}회

===== 챔피언별 상세 통계 =====
{chr(10).join(champ_details[:5])}

===== 분석 요청 =====
위 데이터를 종합하여 다음을 분석해주세요:
1. 플레이어의 주요 강점 (라인전/한타/스플릿/시야 등)
2. 플레이어의 약점 또는 취약 시점
3. 주의해야 할 챔피언과 그 이유
4. 스크림에서 이 플레이어를 상대할 때 구체적인 대응 전략

5줄 이내로 핵심만 간결하게 작성해주세요. 한국어로 답변하세요."""

        response = await gemini_client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=[{"parts": [{"text": prompt}]}]
        )

        return response.text.strip()

    except Exception as e:
        print(f"[AI 분석 오류] {e}")
        return None


def format_rank(rank_data: dict | None) -> str:
    """랭크 정보 포맷팅"""
    if not rank_data:
        return "Unranked"

    tier = rank_data["tier"]
    rank = rank_data["rank"]
    lp = rank_data["leaguePoints"]
    wins = rank_data["wins"]
    losses = rank_data["losses"]
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    tier_emoji = {
        "IRON": "🔩", "BRONZE": "🥉", "SILVER": "🥈", "GOLD": "🥇",
        "PLATINUM": "💎", "EMERALD": "💚", "DIAMOND": "💠",
        "MASTER": "🏆", "GRANDMASTER": "🔥", "CHALLENGER": "👑"
    }

    emoji = tier_emoji.get(tier, "🎮")
    return f"{emoji} {tier} {rank} ({lp}LP) | {wins}승 {losses}패 ({win_rate:.1f}%)"


def format_position(position: str) -> str:
    """포지션 한글 변환"""
    pos_map = {
        "TOP": "탑",
        "JUNGLE": "정글",
        "MIDDLE": "미드",
        "BOTTOM": "원딜",
        "UTILITY": "서폿",
        "UNKNOWN": "미확인"
    }
    return pos_map.get(position, position)


# ==========================================
# 명령어
# ==========================================
@bot.event
async def on_ready():
    await load_champion_map()
    print(f'상대팀 분석 봇 로그인 성공: {bot.user}')


@bot.command(name="analyze")
@has_admin_role()
async def analyze_cmd(ctx, *args):
    """
    플레이어를 분석합니다. (1~5명)
    사용법: !analyze 닉네임1#태그 [닉네임2#태그] [닉네임3#태그] ...
    !analyze refresh 닉네임#태그 - 캐시 무시하고 새로 분석
    """
    if not RIOT_API_KEY:
        await ctx.send("❌ RIOT_API_KEY가 설정되지 않았습니다. `.env` 파일을 확인해주세요.")
        return

    if len(args) == 0:
        await ctx.send("❌ 최소 1명의 닉네임을 입력해주세요.\n"
                       "**사용법:** `!analyze 닉네임1#태그 [닉네임2#태그] ...` (최대 5명)\n"
                       "**예시:** `!analyze Hide on bush#KR1 Faker#KR1`\n"
                       "**새로고침:** `!analyze refresh 닉네임#태그`")
        return

    # refresh 옵션 체크
    force_refresh = False
    args_list = list(args)
    if args_list and args_list[0].lower() == "refresh":
        force_refresh = True
        args_list = args_list[1:]
        if not args_list:
            await ctx.send("❌ 새로고침할 닉네임을 입력해주세요.\n**사용법:** `!analyze refresh 닉네임#태그`")
            return

    # 공백이 포함된 닉네임 처리: #태그를 기준으로 재조합
    raw_text = " ".join(args_list)
    players = []
    current = ""

    for part in raw_text.split(" "):
        if current:
            current += " " + part
        else:
            current = part

        # #이 포함되어 있고, # 뒤에 문자가 있으면 완성된 닉네임
        if "#" in current:
            hash_idx = current.rfind("#")
            tag_part = current[hash_idx + 1:]
            # 태그 부분이 있으면 완성
            if tag_part:
                players.append(current)
                current = ""

    # 마지막 남은 부분 처리 (태그 없이 끝난 경우)
    if current:
        players.append(current)

    if len(players) == 0:
        await ctx.send("❌ 올바른 형식으로 닉네임을 입력해주세요.\n"
                       "**형식:** `닉네임#태그` (예: `Hide on bush#KR1`)")
        return

    if len(players) > 5:
        await ctx.send("❌ 최대 5명까지만 분석할 수 있습니다.")
        return

    # 시작 시 만료된 캐시 정리
    clear_expired_cache()

    refresh_text = " (강제 새로고침)" if force_refresh else ""
    processing_msg = await ctx.send(f"🔄 {len(players)}명 분석 중...{refresh_text}")

    results = []
    cached_count = 0

    for player in players:
        data, is_cached, cached_ai = await analyze_player(player, force_refresh=force_refresh)
        if is_cached:
            cached_count += 1
        results.append((player, data, is_cached, cached_ai))

    # 임베드 생성
    embed = discord.Embed(
        title=f"🔍 플레이어 분석 결과 ({len(players)}명)",
        color=0xe74c3c
    )

    # 캐시 사용 여부 표시
    if cached_count > 0:
        embed.description = f"📦 {cached_count}명은 캐시된 데이터 사용 (7일 이내 조회됨)"

    for i, (player_name, data, is_cached, cached_ai) in enumerate(results):
        if data is None:
            embed.add_field(
                name=f"{player_name}",
                value="❌ 플레이어를 찾을 수 없습니다.",
                inline=False
            )
            continue

        # 캐시 표시
        cache_badge = " 📦" if is_cached else ""

        # 현재 게임 중 표시 (캐시된 데이터가 아닐 때만)
        if not is_cached and data.get("current_game"):
            current = data["current_game"]
            game_mode = current.get("gameMode", "UNKNOWN")
            game_length = current.get("gameLength", 0) // 60
            embed.add_field(
                name=f"🎮 현재 게임 중!",
                value=f"모드: {game_mode} | 진행시간: {game_length}분",
                inline=False
            )

        # 솔로랭크 & 플렉스
        solo_str = format_rank(data["solo_rank"])
        flex_str = format_rank(data.get("flex_rank"))

        # 주 포지션
        main_pos, pos_games = data.get("main_position", ("UNKNOWN", 0))
        pos_str = f"{format_position(main_pos)} ({pos_games}게임)"

        # 전체 모스트 (숙련도 기반)
        top_champs = []
        for mastery in data["top_champions"][:3]:
            champ_name = get_champion_name(mastery["championId"])
            points = mastery["championPoints"]
            top_champs.append(f"{champ_name} ({points // 1000}k)")
        all_most_str = " | ".join(top_champs) if top_champs else "데이터 없음"

        # 최근 모스트 (최근 20게임 기준) - 상세 정보 포함
        recent_most = data.get("recent_most", [])
        recent_most_parts = []
        champion_stats = data.get("champion_stats", {})
        for champ, count in recent_most[:3]:
            stats = champion_stats.get(champ, {})
            if stats:
                wins = stats.get("wins", 0)
                games = stats.get("games", count)
                wr = (wins / games * 100) if games > 0 else 0
                kda = (stats["kills"] + stats["assists"]) / max(stats["deaths"], 1)
                recent_most_parts.append(f"{champ} ({games}판 {wr:.0f}% KDA {kda:.1f})")
            else:
                recent_most_parts.append(f"{champ} ({count}판)")
        recent_most_str = " | ".join(recent_most_parts) if recent_most_parts else "데이터 없음"

        # 최근 전적
        recent_total = data["recent_wins"] + data["recent_losses"]
        recent_wr = (data["recent_wins"] / recent_total * 100) if recent_total > 0 else 0
        recent_str = f"{data['recent_wins']}승 {data['recent_losses']}패 ({recent_wr:.0f}%)"

        # 평균 KDA
        avg_kda = data.get("avg_kda", 0)
        kda_str = f"{data['total_kills']}/{data['total_deaths']}/{data['total_assists']} (평균 {avg_kda:.2f})"

        # 기본 정보 필드
        value = f"**솔로랭크:** {solo_str}\n"
        if data.get("flex_rank"):
            flex_str = format_rank(data["flex_rank"])
            value += f"**자유랭크:** {flex_str}\n"
        value += f"**주 포지션:** {pos_str}\n"
        value += f"**전체 모스트:** {all_most_str}\n"
        value += f"**최근 모스트:** {recent_most_str}\n"
        value += f"**최근 {recent_total}게임:** {recent_str}\n"
        value += f"**KDA:** {kda_str}"

        embed.add_field(
            name=f"{data['riot_id']} (Lv.{data['summoner_level']}){cache_badge}",
            value=value,
            inline=False
        )

        # 상세 통계 필드 추가
        total_stats = data.get("total_stats", {})
        avg_stats = data.get("avg_stats", {})
        recent_matches = data.get("recent_matches", [])

        if total_stats and recent_total > 0:
            # 킬관여율, 팀딜비중 계산
            kp_list = [m.get("kill_participation", 0) for m in recent_matches if m.get("kill_participation")]
            tdp_list = [m.get("team_damage_percentage", 0) for m in recent_matches if m.get("team_damage_percentage")]
            avg_kp = (sum(kp_list) / len(kp_list) * 100) if kp_list else 0
            avg_tdp = (sum(tdp_list) / len(tdp_list) * 100) if tdp_list else 0

            first_blood_rate = (total_stats.get("first_blood_kills", 0) + total_stats.get("first_blood_assists", 0)) / recent_total * 100

            # 공격성 & 전투 통계
            combat_value = f"🗡️ **공격성:** 퍼블관여 {first_blood_rate:.0f}% | 솔로킬 {total_stats.get('solo_kills', 0)}회 | 킬관여 {avg_kp:.0f}%\n"
            combat_value += f"💥 **멀티킬:** 더블 {total_stats.get('double_kills', 0)} | 트리플 {total_stats.get('triple_kills', 0)} | 쿼드라 {total_stats.get('quadra_kills', 0)} | 펜타 {total_stats.get('penta_kills', 0)}\n"
            combat_value += f"💪 **전투:** 딜 {avg_stats.get('avg_damage', 0):.0f} ({avg_tdp:.0f}%) | 탱킹 {avg_stats.get('avg_damage_taken', 0):.0f} | CC {avg_stats.get('avg_cc_time', 0):.1f}초\n"
            combat_value += f"📈 **분당:** DPM {avg_stats.get('avg_dpm', 0):.0f} | GPM {avg_stats.get('avg_gpm', 0):.0f}"

            embed.add_field(
                name=f"⚔️ 전투 통계",
                value=combat_value,
                inline=False
            )

            # 오브젝트 & 시야
            obj_value = f"🏰 **오브젝트:** 타워 {total_stats.get('turret_kills', 0)} | 플레이트 {total_stats.get('turret_takedowns', 0)} | 용 {total_stats.get('dragon_kills', 0)} | 바론 {total_stats.get('baron_kills', 0)}\n"
            obj_value += f"🎯 **오브젝트 딜:** 평균 {avg_stats.get('avg_obj_damage', 0):.0f}\n"
            obj_value += f"👁️ **시야:** 점수 {avg_stats.get('avg_vision_score', 0):.1f} | 와드 {avg_stats.get('avg_wards_placed', 0):.1f} | 제어 {avg_stats.get('avg_control_wards', 0):.1f} | 제거 {total_stats.get('wards_killed', 0)}"

            embed.add_field(
                name=f"🏛️ 오브젝트 & 시야",
                value=obj_value,
                inline=False
            )

            # 라인전 (타임라인 데이터가 있는 경우)
            if total_stats.get("games_with_timeline", 0) > 0:
                lane_value = f"📊 **10분 기준** (최근 {total_stats['games_with_timeline']}게임)\n"
                lane_value += f"CS: {avg_stats.get('avg_cs_at_10', 0):.0f} | 골드: {avg_stats.get('avg_gold_at_10', 0):.0f}\n"
                lane_value += f"초반 킬: {avg_stats.get('avg_early_kills', 0):.1f} | 초반 데스: {avg_stats.get('avg_early_deaths', 0):.1f}"

                embed.add_field(
                    name=f"🛡️ 라인전",
                    value=lane_value,
                    inline=True
                )

            # 스킬샷 통계 (있는 경우에만)
            if total_stats.get("skillshots_hit", 0) > 0 or total_stats.get("skillshots_dodged", 0) > 0:
                skill_value = f"명중: {total_stats.get('skillshots_hit', 0)} | 회피: {total_stats.get('skillshots_dodged', 0)}"
                embed.add_field(
                    name=f"🎯 스킬샷",
                    value=skill_value,
                    inline=True
                )

        # 도전과제 정보 표시
        challenges_data = data.get("challenges_data")
        if challenges_data:
            total_points = challenges_data.get("totalPoints", {})
            level = total_points.get("level", "NONE")
            current_pts = total_points.get("current", 0)
            percentile = total_points.get("percentile", 0) * 100

            challenge_emoji = {"IRON": "🔩", "BRONZE": "🥉", "SILVER": "🥈", "GOLD": "🥇",
                               "PLATINUM": "💎", "DIAMOND": "💠", "MASTER": "🏆",
                               "GRANDMASTER": "🔥", "CHALLENGER": "👑", "NONE": "⚪"}

            embed.add_field(
                name=f"🏅 도전과제",
                value=f"{challenge_emoji.get(level, '⚪')} {level}\n{current_pts:,}점 (상위 {percentile:.1f}%)",
                inline=True
            )

        # AI 분석 (Gemini) - 캐시된 경우 캐시된 AI 분석 사용
        if gemini_client:
            if is_cached and cached_ai:
                ai_analysis = cached_ai
            else:
                ai_analysis = await generate_ai_analysis(data)
                # 새로 분석한 경우 캐시에 저장
                if not is_cached and ai_analysis:
                    set_cached_player(player_name, data, ai_analysis)

            if ai_analysis:
                embed.add_field(
                    name=f"🤖 AI 분석",
                    value=f"```{ai_analysis[:900]}```",
                    inline=False
                )
        elif not is_cached:
            # AI 분석 없이 캐시 저장
            set_cached_player(player_name, data, None)

    embed.set_footer(text="📦=캐시(7일) | 새로고침: !analyze refresh 닉네임#태그")
    await processing_msg.edit(content=None, embed=embed)


@bot.command(name="live")
@has_admin_role()
async def live_cmd(ctx, *, riot_id: str = None):
    """
    플레이어의 현재 진행 중인 게임을 조회합니다.
    사용법: !live 닉네임#태그
    """
    if not RIOT_API_KEY:
        await ctx.send("❌ RIOT_API_KEY가 설정되지 않았습니다.")
        return

    if not riot_id:
        await ctx.send("❌ 닉네임을 입력해주세요.\n**사용법:** `!live 닉네임#태그`")
        return

    # 닉네임 파싱
    if "#" in riot_id:
        game_name, tag_line = riot_id.rsplit("#", 1)
    else:
        game_name = riot_id
        tag_line = "KR1"

    processing_msg = await ctx.send(f"🔄 {game_name}#{tag_line} 게임 조회 중...")

    # 계정 정보 조회
    account = await get_account_by_riot_id(game_name, tag_line)
    if not account:
        await processing_msg.edit(content="❌ 플레이어를 찾을 수 없습니다.")
        return

    puuid = account["puuid"]

    # 현재 게임 조회
    current_game = await get_current_game(puuid)

    if not current_game:
        await processing_msg.edit(content=f"ℹ️ **{game_name}#{tag_line}** 님은 현재 게임 중이 아닙니다.")
        return

    # 게임 정보 표시
    game_mode = current_game.get("gameMode", "UNKNOWN")
    game_type = current_game.get("gameType", "UNKNOWN")
    game_length = current_game.get("gameLength", 0) // 60
    map_id = current_game.get("mapId", 0)

    embed = discord.Embed(
        title=f"🎮 {game_name}#{tag_line} 현재 게임",
        color=0x00ff00
    )

    embed.add_field(name="게임 모드", value=game_mode, inline=True)
    embed.add_field(name="진행 시간", value=f"{game_length}분", inline=True)

    # 참가자 정보
    participants = current_game.get("participants", [])

    blue_team = []
    red_team = []

    for p in participants:
        champ_id = p.get("championId", 0)
        champ_name = get_champion_name(champ_id)
        summoner_name = p.get("riotId", "Unknown")
        team_id = p.get("teamId", 0)

        player_str = f"{champ_name} - {summoner_name}"

        if team_id == 100:
            blue_team.append(player_str)
        else:
            red_team.append(player_str)

    embed.add_field(
        name="🔵 블루팀",
        value="\n".join(blue_team) if blue_team else "정보 없음",
        inline=False
    )

    embed.add_field(
        name="🔴 레드팀",
        value="\n".join(red_team) if red_team else "정보 없음",
        inline=False
    )

    await processing_msg.edit(content=None, embed=embed)


# ==========================================
# 메인
# ==========================================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ YUM_BOT_TOKEN이 설정되지 않았습니다.")
    elif not RIOT_API_KEY:
        print("❌ RIOT_API_KEY가 설정되지 않았습니다.")
    else:
        bot.run(TOKEN)