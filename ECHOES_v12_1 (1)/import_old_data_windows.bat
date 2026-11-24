@echo off
REM --- If started from inside the .zip (not extracted), extract it once and continue ---
if exist "%~dp0requirements.txt" goto :echoes_extracted
set "ECH_SRC=%~dp0"
set "ECH_BAT=%~nx0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$src=$env:ECH_SRC.TrimEnd('\'); $zip=(Split-Path -Leaf $src) -replace '^Temp\d+_',''; $roots=@([Environment]::GetFolderPath('UserProfile')+'\Downloads',[Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('MyDocuments'),$env:OneDrive) | Where-Object {$_ -and (Test-Path $_)}; $f=$null; foreach($r in $roots){ $f=Get-ChildItem -LiteralPath $r -Filter $zip -File -Recurse -Depth 2 -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if($f){break} }; if(-not $f){ Write-Host ''; Write-Host ' Please extract the ZIP first: right-click it > Extract All, then open the extracted folder.'; exit 2 }; $dst=Join-Path ([Environment]::GetFolderPath('Desktop')) 'ECHOES'; Write-Host (' Extracting ECHOES to: '+$dst+' ...'); Expand-Archive -LiteralPath $f.FullName -DestinationPath $dst -Force; Start-Process explorer.exe $dst; Start-Process -FilePath (Join-Path $dst $env:ECH_BAT) -WorkingDirectory $dst; exit 0"
if errorlevel 1 pause
exit /b
:echoes_extracted
REM ECHOES - copy your saved data (Telegram settings, safe zone, patient profile, photos)
REM from an OLDER ECHOES folder into THIS folder.
cd /d "%~dp0"
chcp 65001 >nul
echo.
echo  ECHOES - import data from the old folder
echo  Drag the OLD ECHOES folder into this window, then press Enter:
set /p OLD=
set OLD=%OLD:"=%
if not exist "%OLD%\echeos.db" (
  echo  Not found: "%OLD%\echeos.db" - choose the folder that contains echeos.db
  pause
  exit /b 1
)
if exist echeos.db copy /y echeos.db echeos.db.before_import >nul
copy /y "%OLD%\echeos.db" echeos.db >nul
if exist "%OLD%\app\.secret_key" copy /y "%OLD%\app\.secret_key" "app\.secret_key" >nul
if exist "%OLD%\app\uploads" xcopy "%OLD%\app\uploads" "app\uploads\" /E /I /Y /Q >nul
echo.
echo  Done. Telegram settings, safe zone, profile and photos were copied.
echo  Now start ECHOES as usual (run_public_windows.bat).
pause
