@echo off
REM --- If started from inside the .zip (not extracted), extract it once and continue ---
if exist "%~dp0requirements.txt" goto :echoes_extracted
set "ECH_SRC=%~dp0"
set "ECH_BAT=%~nx0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$src=$env:ECH_SRC.TrimEnd('\'); $zip=(Split-Path -Leaf $src) -replace '^Temp\d+_',''; $roots=@([Environment]::GetFolderPath('UserProfile')+'\Downloads',[Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('MyDocuments'),$env:OneDrive) | Where-Object {$_ -and (Test-Path $_)}; $f=$null; foreach($r in $roots){ $f=Get-ChildItem -LiteralPath $r -Filter $zip -File -Recurse -Depth 2 -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($f){break} }; if(-not $f){ Write-Host ''; Write-Host ' Please extract the ZIP first: right-click it > Extract All, then open the extracted folder.'; exit 2 }; $dst=Join-Path ([Environment]::GetFolderPath('Desktop')) 'ECHOES'; Write-Host (' Extracting ECHOES to: '+$dst+' ...'); Expand-Archive -LiteralPath $f.FullName -DestinationPath $dst -Force; Start-Process explorer.exe $dst; Start-Process -FilePath (Join-Path $dst $env:ECH_BAT) -WorkingDirectory $dst; exit 0"
if errorlevel 1 pause
exit /b
:echoes_extracted
title ECHOES - Local server with public HTTPS live link
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Python environment not found. Run install_windows.bat first.
  pause
  exit /b 1
)
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo Cloudflare Tunnel is not installed.
  echo Install it from PowerShell:
  echo winget install --id Cloudflare.cloudflared -e
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt >nul 2>nul
REM optional: hand model for counting fingers (skipped if your Python is too new)
python -m pip install -q mediapipe >nul 2>nul
python run_public.py
pause
