# download_icons.py
import requests
import os

ICONS_DIR = "champion_icons"
os.makedirs(ICONS_DIR, exist_ok=True)

# Data Dragon에서 최신 버전 가져오기
version_url = "https://ddragon.leagueoflegends.com/api/versions.json"
versions = requests.get(version_url).json()
latest_version = versions[0]

# 챔피언 목록 가져오기
champ_url = f"https://ddragon.leagueoflegends.com/cdn/{latest_version}/data/en_US/champion.json"
champ_data = requests.get(champ_url).json()

for champ_name in champ_data["data"].keys():
    icon_url = f"https://ddragon.leagueoflegends.com/cdn/{latest_version}/img/champion/{champ_name}.png"
    response = requests.get(icon_url)
    if response.status_code == 200:
        with open(f"{ICONS_DIR}/{champ_name}.png", "wb") as f:
            f.write(response.content)
        print(f"✅ {champ_name} 다운로드 완료")

print(f"\n총 {len(champ_data['data'])}개 챔피언 아이콘 다운로드 완료!")