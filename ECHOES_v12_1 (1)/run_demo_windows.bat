@echo off
REM --- If started from inside the .zip (not extracted), extract it once and continue ---
if exist "%~dp0requirements.txt" goto :echoes_extracted
set "ECH_SRC=%~dp0"
set "ECH_BAT=%~nx0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$src=$env:ECH_SRC.TrimEnd('\'); $zip=(Split-Path -Leaf $src) -replace '^Temp\d+_',''; $roots=@([Environment]::GetFolderPath('UserProfile')+'\Downloads',[Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('MyDocuments'),$env:OneDrive) | Where-Object {$_ -and (Test-Path $_)}; $f=$null; foreach($r in $roots){ $f=Get-ChildItem -LiteralPath $r -Filter $zip -File -Recurse -Depth 2 -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($f){break} }; if(-not $f){ Write-Host ''; Write-Host ' Please extract the ZIP first: right-click it > Extract All, then open the extracted folder.'; exit 2 }; $dst=Join-Path ([Environment]::GetFolderPath('Desktop')) 'ECHOES'; Write-Host (' Extracting ECHOES to: '+$dst+' ...'); Expand-Archive -LiteralPath $f.FullName -DestinationPath $dst -Force; Start-Process explorer.exe $dst; Start-Process -FilePath (Join-Path $dst $env:ECH_BAT) -WorkingDirectory $dst; exit 0"
if errorlevel 1 pause
exit /b
:echoes_extracted
REM ECHOES - simulated demo version (fictional data, separate database)
title ECHOES - Demo
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo  Python is not installed. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv (
  echo  First run: installing...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip >nul
  python -m pip install -r requirements.txt
  python -m app.fetch_models
) else (
  call .venv\Scripts\activate.bat
  python -m pip install -q -r requirements.txt >nul 2>nul
REM optional: hand model for counting fingers (skipped if your Python is too new)
python -m pip install -q mediapipe >nul 2>nul
)
echo.
echo  Demo login:  demo@echoes.app   /   Echoes2026
echo.
python run_demo.py
pause
