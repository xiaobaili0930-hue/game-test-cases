@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" was not found.
  pause
  exit /b 1
)
if not exist "adb.exe" (
  echo Put this file in the same folder as adb.exe.
  pause
  exit /b 1
)
echo Close any old bot window before continuing.
echo This launcher downloads the latest bot and enables actual clicks.
pause
echo Downloading latest bot.py...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { $url='https://raw.githubusercontent.com/xiaobaili0930-hue/game-test-cases/main/mumu_relic/bot.py?v='+[DateTime]::UtcNow.Ticks; Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 $url -OutFile 'bot_update.tmp' } catch { Remove-Item 'bot_update.tmp' -ErrorAction SilentlyContinue; Write-Error $_; exit 1 }"
if errorlevel 1 goto update_failed
py -c "from pathlib import Path; compile(Path('bot_update.tmp').read_text(encoding='utf-8-sig'), 'bot.py', 'exec')"
if errorlevel 1 goto update_failed
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { if(Test-Path 'bot.py'){ Copy-Item 'bot.py' ('bot_backup_'+(Get-Date -Format yyyyMMdd_HHmmss_fffffff)+'.py') }; Move-Item -Force 'bot_update.tmp' 'bot.py' } catch { Write-Error $_; exit 1 }"
if errorlevel 1 goto update_failed
echo Update complete. Starting bot. Press Ctrl+C to stop.
py bot.py --adb ".\adb.exe" --serial 127.0.0.1:16416 --run
pause
exit /b

:update_failed
echo Update failed. The bot was not started.
echo Check network access to GitHub and try again.
pause
exit /b 1
