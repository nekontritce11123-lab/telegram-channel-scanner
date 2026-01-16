@echo off
chcp 65001 >nul 2>&1
title Smart Crawler v18.0

:menu
cls
echo ========================================================
echo            SMART CRAWLER v18.0
echo      17 categories + multi-label classification
echo ========================================================
echo.
echo   [1] Run crawler (infinite)
echo   [2] Run crawler (limited)
echo   [3] Add seed channels
echo.
echo   [4] Database stats
echo   [5] Category stats
echo.
echo   [6] Classify existing channels
echo   [7] Export GOOD channels to CSV
echo   [8] Export by category
echo.
echo   [9] Scan single channel
echo   [0] Exit
echo.
set /p choice="Select: "

if "%choice%"=="1" goto run_infinite
if "%choice%"=="2" goto run_limited
if "%choice%"=="3" goto add_seeds
if "%choice%"=="4" goto stats
if "%choice%"=="5" goto category_stats
if "%choice%"=="6" goto classify
if "%choice%"=="7" goto export_all
if "%choice%"=="8" goto export_category
if "%choice%"=="9" goto scan_one
if "%choice%"=="0" goto exit

echo Invalid choice!
pause
goto menu

:run_infinite
cls
echo Starting crawler... (Ctrl+C to stop)
echo.
python crawler.py
pause
goto menu

:run_limited
cls
set /p max_count="How many channels to process: "
echo.
python crawler.py --max %max_count%
pause
goto menu

:add_seeds
cls
echo Enter channels separated by space (e.g. @channel1 @channel2)
set /p seeds="Channels: "
echo.
python crawler.py %seeds%
pause
goto menu

:stats
cls
python crawler.py --stats
echo.
pause
goto menu

:category_stats
cls
python crawler.py --category-stats
echo.
pause
goto menu

:classify
cls
set /p classify_count="How many channels to classify (Enter = 100): "
if "%classify_count%"=="" set classify_count=100
echo.
python crawler.py --classify --max %classify_count%
pause
goto menu

:export_all
cls
set /p filename="Filename (Enter = good_channels.csv): "
if "%filename%"=="" set filename=good_channels.csv
echo.
python crawler.py --export %filename%
echo.
echo Saved: %filename%
pause
goto menu

:export_category
cls
echo Categories: CRYPTO, FINANCE, REAL_ESTATE, BUSINESS, TECH, AI_ML,
echo             EDUCATION, BEAUTY, HEALTH, TRAVEL, RETAIL,
echo             ENTERTAINMENT, NEWS, LIFESTYLE, GAMBLING, ADULT
echo.
set /p cat="Category: "
set /p catfile="Filename (Enter = %cat%.csv): "
if "%catfile%"=="" set catfile=%cat%.csv
echo.
python crawler.py --export %catfile% --category %cat%
echo.
echo Saved: %catfile%
pause
goto menu

:scan_one
cls
set /p channel="Channel (@username): "
echo.
python run.py %channel%
pause
goto menu

:exit
exit
