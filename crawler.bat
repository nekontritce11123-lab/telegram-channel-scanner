@echo off
chcp 65001 >nul 2>&1
title Crawler v61.0

:menu
cls
echo ============================================================
echo                     CRAWLER v61.0
echo         Skaner Telegram kanalov - 17 kategoriy
echo ============================================================
echo.
echo   [1] Zapustit crawler (beskonechno)
echo   [2] Zapustit crawler (ogranicheno)
echo   [3] Dobavit seed kanaly
echo.
echo   [4] Statistika bazy
echo   [5] Statistika po kategoriyam
echo.
echo   [6] Klassificirovat kanaly
echo   [7] Export GOOD v CSV
echo   [8] Export po kategorii
echo.
echo   [9] Skanirovat odin kanal
echo   [S] Sync BD na server
echo   [0] Vyhod
echo.
set /p choice="Vybor: "

if "%choice%"=="1" goto run_infinite
if "%choice%"=="2" goto run_limited
if "%choice%"=="3" goto add_seeds
if "%choice%"=="4" goto stats
if "%choice%"=="5" goto category_stats
if "%choice%"=="6" goto classify
if "%choice%"=="7" goto export_all
if "%choice%"=="8" goto export_category
if "%choice%"=="9" goto scan_one
if /i "%choice%"=="s" goto sync_db
if "%choice%"=="0" goto exit

echo Nevernyy vybor!
pause
goto menu

:run_infinite
cls
echo Zapusk crawlera... (Ctrl+C dlya ostanovki)
echo.
echo Pri zapuske: zabirayem zaprosy s servera
echo Pri zavershenii: otpravlyaem BD na server
echo.
python crawler.py
pause
goto menu

:run_limited
cls
set /p max_count="Skolko kanalov obrabotat: "
echo.
python crawler.py --max %max_count%
pause
goto menu

:add_seeds
cls
echo Vvedite kanaly cherez probel (naprimer @channel1 @channel2)
set /p seeds="Kanaly: "
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
set /p classify_count="Skolko kanalov klassificirovat (Enter = 100): "
if "%classify_count%"=="" set classify_count=100
echo.
python crawler.py --classify --max %classify_count%
pause
goto menu

:export_all
cls
set /p filename="Imya fayla (Enter = good_channels.csv): "
if "%filename%"=="" set filename=good_channels.csv
echo.
python crawler.py --export %filename%
echo.
echo Sohraneno: %filename%
pause
goto menu

:export_category
cls
echo Kategorii: CRYPTO, FINANCE, REAL_ESTATE, BUSINESS, TECH, AI_ML,
echo            EDUCATION, BEAUTY, HEALTH, TRAVEL, RETAIL,
echo            ENTERTAINMENT, NEWS, LIFESTYLE, GAMBLING, ADULT
echo.
set /p cat="Kategoriya: "
set /p catfile="Imya fayla (Enter = %cat%.csv): "
if "%catfile%"=="" set catfile=%cat%.csv
echo.
python crawler.py --export %catfile% --category %cat%
echo.
echo Sohraneno: %catfile%
pause
goto menu

:scan_one
cls
set /p channel="Kanal (@username): "
echo.
python run.py %channel%
pause
goto menu

:sync_db
cls
echo Otpravka BD na server...
echo.
cd mini-app\deploy
python sync_db.py
cd ..\..
echo.
pause
goto menu

:exit
exit
