@echo off
chcp 65001 >nul

:: PowerShell을 이용해 바탕화면에 깔끔하게 바로가기 생성 및 아이콘 적용
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $ErrorActionPreference = 'Stop'; $wshShell = New-Object -ComObject WScript.Shell; $desktopPath = [Environment]::GetFolderPath('Desktop'); $shortcutPath = Join-Path $desktopPath 'Gemini 이미지 수집기 V2.0.lnk'; $targetPath = Join-Path $PWD 'dist\Gemini_Image_Crawler_v1.0.11\Gemini_Image_Crawler_v1.0.11.exe'; $shortcut = $wshShell.CreateShortcut($shortcutPath); $shortcut.TargetPath = $targetPath; $shortcut.WorkingDirectory = Join-Path $PWD 'dist\Gemini_Image_Crawler_v1.0.11'; $shortcut.Description = 'Gemini 이미지 수집기 V2.0 실행'; $shortcut.IconLocation = Join-Path $PWD 'app_icon.ico'; $shortcut.Save(); [System.Windows.Forms.MessageBox]::Show('바탕화면에 [Gemini 이미지 수집기 V2.0] 바로가기가 생성되었습니다!', '설치 완료', 'OK', 'Information')"

if %errorlevel% neq 0 (
    echo [오류] 바로가기 생성에 실패했습니다. 관리자 권한으로 실행해보세요.
    pause
)
