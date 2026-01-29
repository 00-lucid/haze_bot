@echo off
echo [1/3] Building haze_scheduler...
pyinstaller --onefile --name haze_scheduler haze_scheduler.py

echo [2/3] Building haze_latte...
pyinstaller --onefile --name haze_latte haze_latte.py

echo [3/3] Building HazeBot launcher...
pyinstaller HazeBot.spec

echo Done!
pause