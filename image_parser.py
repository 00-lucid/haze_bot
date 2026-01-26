
import os
import json
import base64
import aiohttp
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Gemini 클라이언트
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 분석 프롬프트
ANALYSIS_PROMPT = """이 이미지는 리그 오브 레전드 게임 결과 화면입니다.
이미지에서 다음 정보를 추출하여 JSON 형식으로 반환해주세요:

1. 게임 결과 (승리/패배)
2. 게임 시간 (분:초 형식)
3. 1팀(위쪽 팀) 전체 정보 및 5명의 개인 정보
4. 2팀(아래쪽 팀) 전체 정보 및 5명의 개인 정보

반드시 아래 JSON 형식으로만 응답해주세요. 다른 텍스트 없이 JSON만 출력하세요:
{
  "is_win": true,
  "game_time": "23:19",
  "team1": {
    "total_kills": 27,
    "total_deaths": 7,
    "total_assists": 42,
    "team_total_gold": 53587,
    "players": [
      {
        "position": "탑",
        "nickname": "유저닉네임",
        "champion": "Jax",
        "level": 15,
        "kills": 8,
        "deaths": 3,
        "assists": 5,
        "kda": 4.33,
        "total_gold": 9627,
        "gold_per_min": 412,
        "damage": 15000,
        "damage_per_min": 643,
        "gold_share": 18.0,
        "damage_per_gold": 155.85
      },
      {
        "position": "정글",
        "nickname": "유저닉네임",
        "champion": "Lillia",
        "level": 14,
        "kills": 9,
        "deaths": 2,
        "assists": 6,
        "kda": 7.5,
        "total_gold": 9943,
        "gold_per_min": 426,
        "damage": 18000,
        "damage_per_min": 771,
        "gold_share": 18.6,
        "damage_per_gold": 181.02
      },
      {
        "position": "미드",
        "nickname": "유저닉네임",
        "champion": "Ryze",
        "level": 16,
        "kills": 3,
        "deaths": 0,
        "assists": 9,
        "kda": 12.0,
        "total_gold": 10181,
        "gold_per_min": 436,
        "damage": 22000,
        "damage_per_min": 943,
        "gold_share": 19.0,
        "damage_per_gold": 216.09
      },
      {
        "position": "원딜",
        "nickname": "유저닉네임",
        "champion": "Ezreal",
        "level": 15,
        "kills": 6,
        "deaths": 1,
        "assists": 7,
        "kda": 13.0,
        "total_gold": 11200,
        "gold_per_min": 480,
        "damage": 25000,
        "damage_per_min": 1071,
        "gold_share": 20.9,
        "damage_per_gold": 223.21
      },
      {
        "position": "서폿",
        "nickname": "유저닉네임",
        "champion": "Leona",
        "level": 12,
        "kills": 1,
        "deaths": 1,
        "assists": 15,
        "kda": 16.0,
        "total_gold": 7005,
        "gold_per_min": 300,
        "damage": 5000,
        "damage_per_min": 214,
        "gold_share": 13.1,
        "damage_per_gold": 71.38
      }
    ]
  },
  "team2": {
    "total_kills": 7,
    "total_deaths": 27,
    "total_assists": 9,
    "team_total_gold": 41519,
    "players": [
      {
        "position": "탑",
        "nickname": "유저닉네임",
        "champion": "Ambessa",
        "level": 13,
        "kills": 5,
        "deaths": 8,
        "assists": 0,
        "kda": 0.63,
        "total_gold": 8461,
        "gold_per_min": 363,
        "damage": 12000,
        "damage_per_min": 514,
        "gold_share": 20.4,
        "damage_per_gold": 141.83
      },
      {
        "position": "정글",
        "nickname": "유저닉네임",
        "champion": "Taliyah",
        "level": 12,
        "kills": 1,
        "deaths": 5,
        "assists": 3,
        "kda": 0.8,
        "total_gold": 6418,
        "gold_per_min": 275,
        "damage": 8000,
        "damage_per_min": 343,
        "gold_share": 15.5,
        "damage_per_gold": 124.65
      },
      {
        "position": "미드",
        "nickname": "유저닉네임",
        "champion": "Naafiri",
        "level": 13,
        "kills": 1,
        "deaths": 5,
        "assists": 3,
        "kda": 0.8,
        "total_gold": 7710,
        "gold_per_min": 330,
        "damage": 14000,
        "damage_per_min": 600,
        "gold_share": 18.6,
        "damage_per_gold": 181.58
      },
      {
        "position": "원딜",
        "nickname": "유저닉네임",
        "champion": "Aurora",
        "level": 14,
        "kills": 0,
        "deaths": 6,
        "assists": 1,
        "kda": 0.17,
        "total_gold": 10181,
        "gold_per_min": 436,
        "damage": 16000,
        "damage_per_min": 686,
        "gold_share": 24.5,
        "damage_per_gold": 157.15
      },
      {
        "position": "서폿",
        "nickname": "유저닉네임",
        "champion": "Lulu",
        "level": 10,
        "kills": 0,
        "deaths": 3,
        "assists": 2,
        "kda": 0.67,
        "total_gold": 9496,
        "gold_per_min": 407,
        "damage": 3000,
        "damage_per_min": 129,
        "gold_share": 22.9,
        "damage_per_gold": 31.60
      }
    ]
  }
}

주의사항:
- 챔피언 이름은 반드시 영어로 작성 (예: Jax, Ryze, Viego, Galio, Lillia, Leona)
- nickname은 이미지에 표시된 소환사명/유저 닉네임 그대로
- level은 게임 종료 시점의 챔피언 레벨 (1~18)
- kda는 (킬+어시스트)/데스 계산값 (데스가 0이면 Perfect 사용)
- total_gold는 전체 획득 골드
- gold_per_min은 분당 골드 (total_gold / 게임시간(분))
- damage는 챔피언에게 가한 피해량 (딜량)
- damage_per_min은 분당 데미지 (damage / 게임시간(분))
- gold_share는 팀 골드 비중 % (개인골드 / 팀총골드 * 100)
- damage_per_gold는 100골드당 데미지 ((damage / total_gold) * 100)
- 이미지 상단에 "승리"가 있으면 is_win: true, "패배"가 있으면 is_win: false
- 위쪽 팀이 team1, 아래쪽 팀이 team2
- 팀별 total_kills, total_deaths, total_assists, team_total_gold는 팀 합계

MVP/SVP 점수 계산 방식:
각 팀별로 MVP(1위)와 SVP(2위)를 산출해주세요. 점수는 다음 지표의 가중 합계입니다:
1. KDA (30%): KDA 5.0 이상이면 만점(30점), 0이면 0점 (선형 비례)
2. 킬 관여율 (25%): (킬+어시스트)/팀 총 킬 * 100, 80% 이상이면 만점(25점)
3. 딜 비중 (20%): 개인 딜량/팀 총 딜량 * 100, 30% 이상이면 만점(20점)
4. 골드 효율 (15%): (딜량/골드)*100, 150 이상이면 만점(15점)
5. 데스 패널티 (10%): 데스 0이면 만점(10점), 데스가 늘어날수록 감소

각 팀의 team_total_gold 아래에 mvp와 svp 객체를 추가하세요:
"mvp": {
  "nickname": "MVP 플레이어 닉네임",
  "mvp_score": 총점(0~100),
  "breakdown": {
    "kda_score": KDA 점수(0~30),
    "kill_participation_score": 킬관여율 점수(0~25),
    "damage_share_score": 딜비중 점수(0~20),
    "gold_efficiency_score": 골드효율 점수(0~15),
    "death_penalty_score": 데스패널티 점수(0~10)
  }
},
"svp": {
  "nickname": "SVP 플레이어 닉네임",
  "mvp_score": 총점(0~100),
  "breakdown": {
    "kda_score": KDA 점수(0~30),
    "kill_participation_score": 킬관여율 점수(0~25),
    "damage_share_score": 딜비중 점수(0~20),
    "gold_efficiency_score": 골드효율 점수(0~15),
    "death_penalty_score": 데스패널티 점수(0~10)
  }
}
"""

async def download_image_bytes(url: str) -> bytes:
    """이미지 URL에서 바이트 다운로드"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
    return None

async def parse_game_image(image_url: str) -> dict:
    """Gemini Vision으로 게임 결과 이미지 분석"""
    try:
        # 이미지 다운로드
        image_bytes = await download_image_bytes(image_url)
        if not image_bytes:
            print("[ERROR] 이미지 다운로드 실패")
            return None

        # Gemini API 호출
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                {
                    "parts": [
                        {"text": ANALYSIS_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image_bytes).decode('utf-8')
                            }
                        }
                    ]
                }
            ]
        )

        # 응답에서 JSON 추출
        content = response.text.strip()
        print(f"[DEBUG] Gemini 응답:\n{content}")

        # JSON 파싱 (코드 블록 제거)
        content = extract_json_from_response(content)
        result = json.loads(content)

        # 데이터 검증 및 보정
        if not validate_result(result):
            print("[WARNING] 데이터 검증 실패, 기본값으로 채움")
            result = fill_missing_data(result)

        # 파생 통계 계산
        result = calculate_derived_stats(result)

        return result

    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 파싱 실패: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] 이미지 분석 실패: {e}")
        return None

def extract_json_from_response(content: str) -> str:
    """응답에서 JSON 부분만 추출"""
    if content.startswith("```"):
        lines = content.split("\n")
        json_lines = []
        in_json = False
        for line in lines:
            if line.startswith("```json"):
                in_json = True
                continue
            elif line.startswith("```"):
                in_json = False
                continue
            if in_json:
                json_lines.append(line)
        content = "\n".join(json_lines)
    return content.strip()

def validate_result(result: dict) -> bool:
    """결과 데이터 검증"""
    if not isinstance(result, dict):
        return False

    required_keys = ["is_win", "game_time", "team1", "team2"]
    for key in required_keys:
        if key not in result:
            return False

    for team_key in ["team1", "team2"]:
        team = result[team_key]
        if not isinstance(team, dict):
            return False
        if "players" not in team or not isinstance(team["players"], list):
            return False
        if len(team["players"]) != 5:
            return False

    return True

def fill_missing_data(result: dict) -> dict:
    """누락된 데이터 기본값으로 채우기"""
    positions = ["탑", "정글", "미드", "원딜", "서폿"]

    default_player = {
        "position": "",
        "nickname": "알 수 없음",
        "champion": "알 수 없음",
        "level": 1,
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "kda": 0.0,
        "total_gold": 0,
        "gold_per_min": 0,
        "damage": 0,
        "gold_share": 0.0,
        "damage_per_min": 0.0,
        "damage_per_gold": 0.0
    }

    default_team = {
        "total_kills": 0,
        "total_deaths": 0,
        "total_assists": 0,
        "team_total_gold": 0,
        "players": []
    }

    if "is_win" not in result:
        result["is_win"] = None
    if "game_time" not in result:
        result["game_time"] = None

    for team_key in ["team1", "team2"]:
        if team_key not in result or not isinstance(result[team_key], dict):
            result[team_key] = default_team.copy()
            result[team_key]["players"] = []

        team = result[team_key]

        # 팀 합계 기본값
        for key in ["total_kills", "total_deaths", "total_assists", "team_total_gold"]:
            if key not in team:
                team[key] = 0

        if "players" not in team or not isinstance(team["players"], list):
            team["players"] = []

        # 5명 채우기
        while len(team["players"]) < 5:
            idx = len(team["players"])
            player = default_player.copy()
            player["position"] = positions[idx]
            team["players"].append(player)

        # 각 플레이어 데이터 검증
        for i, player in enumerate(team["players"]):
            if not isinstance(player, dict):
                team["players"][i] = default_player.copy()
                team["players"][i]["position"] = positions[i]
            else:
                for key in default_player:
                    if key not in player:
                        player[key] = default_player[key]
                player["position"] = positions[i]

    return result


def calculate_derived_stats(result: dict) -> dict:
    """파생 통계 검증 및 보정 (Gemini가 잘못 계산했을 경우 대비)"""
    # 게임 시간(분) 파싱
    game_time_str = result.get("game_time", "0:00")
    minutes = 0
    try:
        parts = game_time_str.split(":")
        if len(parts) == 2:
            minutes = int(parts[0]) + int(parts[1]) / 60
    except (ValueError, AttributeError):
        minutes = 0

    for team_key in ["team1", "team2"]:
        team = result.get(team_key, {})
        team_total_gold = team.get("team_total_gold", 0)

        for player in team.get("players", []):
            player_gold = player.get("total_gold", 0)
            player_damage = player.get("damage", 0)

            # 팀 골드 비중 (%) - 값이 없거나 비정상이면 재계산
            if player.get("gold_share", 0) <= 0 and team_total_gold > 0:
                player["gold_share"] = round((player_gold / team_total_gold) * 100, 1)

            # 분당 골드 - 값이 없으면 계산
            if player.get("gold_per_min", 0) <= 0 and minutes > 0:
                player["gold_per_min"] = round(player_gold / minutes, 0)

            # 분당 데미지 - 값이 없거나 분당골드와 같으면 재계산 (Gemini 버그 대비)
            if minutes > 0:
                expected_dpm = round(player_damage / minutes, 0)
                current_dpm = player.get("damage_per_min", 0)
                # 분당 데미지가 없거나, 분당 골드와 동일하면 (버그) 재계산
                if current_dpm <= 0 or current_dpm == player.get("gold_per_min", 0):
                    player["damage_per_min"] = expected_dpm

            # 100골드당 데미지 - 값이 없으면 계산
            if player.get("damage_per_gold", 0) <= 0 and player_gold > 0:
                player["damage_per_gold"] = round((player_damage / player_gold) * 100, 2)

    return result

# ==========================================
# 로컬 테스트용
# ==========================================
def test_local_image_sync(image_path: str):
    """로컬 이미지로 동기 테스트"""
    with open(image_path, 'rb') as f:
        image_bytes = f.read()

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            {
                "parts": [
                    {"text": ANALYSIS_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(image_bytes).decode('utf-8')
                        }
                    }
                ]
            }
        ]
    )

    content = response.text.strip()
    print(f"Gemini 응답:\n{content}\n")

    # JSON 파싱
    content = extract_json_from_response(content)
    result = json.loads(content)

    # 검증 및 보정
    if not validate_result(result):
        result = fill_missing_data(result)

    # 파생 통계 계산
    result = calculate_derived_stats(result)

    return result

def print_result(result: dict):
    """결과 출력"""
    print("=" * 60)
    print("===== 분석 결과 =====")
    print("=" * 60)
    print(f"승패: {'승리' if result.get('is_win') else '패배'}")
    print(f"게임 시간: {result.get('game_time')}")

    for team_name, team_label in [("team1", "1팀 (아군)"), ("team2", "2팀 (상대)")]:
        team = result.get(team_name, {})
        print(f"\n[{team_label}]")
        print(f"  팀 KDA: {team.get('total_kills', 0)}/{team.get('total_deaths', 0)}/{team.get('total_assists', 0)}")
        print(f"  팀 골드: {team.get('team_total_gold', 0):,}G")
        print("-" * 50)

        for p in team.get('players', []):
            kda = p.get('kda', 0)
            kda_str = f"{kda:.1f}" if isinstance(kda, (int, float)) else str(kda)
            total_gold = p.get('total_gold', 0)
            gold_per_min = p.get('gold_per_min', 0)
            damage = p.get('damage', 0)
            gold_share = p.get('gold_share', 0)
            damage_per_min = p.get('damage_per_min', 0)
            damage_per_gold = p.get('damage_per_gold', 0)
            level = p.get('level', 1)

            print(f"  {p['position']}: {p.get('nickname', '?')} ({p['champion']}) Lv.{level}")
            print(f"       KDA: {p['kills']}/{p['deaths']}/{p['assists']} ({kda_str})")
            print(f"       골드: {total_gold:,}G ({gold_per_min}/분) | 골드비중: {gold_share}%")
            print(f"       딜량: {damage:,} | 분당딜: {damage_per_min:,.0f} | 100골드당딜: {damage_per_gold:.2f}")

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        image_path = "test_screenshot.png"

    print(f"이미지 분석 중: {image_path}\n")
    result = test_local_image_sync(image_path)
    print_result(result)