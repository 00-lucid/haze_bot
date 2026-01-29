@echo off
echo [1/4] Building haze_scheduler...
pyinstaller --onefile --name haze_scheduler haze_scheduler.py

echo [2/4] Building haze_latte...
pyinstaller --onefile --name haze_latte haze_latte.py

echo [3/4] Building haze_yum...
pyinstaller --onefile --console haze_yum.py

echo [4/4] Building HazeBot launcher...
pyinstaller HazeBot.spec

echo Done!
pause