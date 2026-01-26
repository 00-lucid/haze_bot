# haze_launcher.py
import sys
import os
import threading
import time

def run_scheduler():
    """haze_scheduler 실행"""
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.join(os.path.dirname(sys.executable), "_internal")
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        sys.path.insert(0, base_path)
        os.chdir(base_path)

        import haze_scheduler
        haze_scheduler.bot.run(haze_scheduler.TOKEN)
    except Exception as e:
        print(f"[scheduler 오류] {e}")

def run_scrimer():
    """haze_scrimer 실행"""
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.join(os.path.dirname(sys.executable), "_internal")
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        sys.path.insert(0, base_path)
        os.chdir(base_path)

        import haze_scrimer
        haze_scrimer.bot.run(haze_scrimer.TOKEN)
    except Exception as e:
        print(f"[scrimer 오류] {e}")

def main():
    print("=" * 50)
    print(" Haze Discord Bot Launcher")
    print("=" * 50)
    print("두 봇을 동시에 실행합니다...")
    print("이 창을 닫으면 봇이 종료됩니다.")
    print("=" * 50)

    # 스레드로 두 봇 실행
    t1 = threading.Thread(target=run_scheduler, daemon=True)
    t2 = threading.Thread(target=run_scrimer, daemon=True)

    t1.start()
    print("✅ haze_scheduler 시작됨")

    t2.start()
    print("✅ haze_scrimer 시작됨")

    print("")
    print("봇이 실행 중입니다. 종료하려면 이 창을 닫으세요.")
    print("=" * 50)

    # 메인 스레드 유지
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n종료 중...")

if __name__ == "__main__":
    main()