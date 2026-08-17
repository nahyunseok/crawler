@echo off
chcp 65001 >nul
:: 이 배치파일이 놓인 폴더를 기준으로 동작한다 (어디서 실행해도 경로가 어긋나지 않게)
pushd "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $ErrorActionPreference = 'Stop'; $target = Join-Path $PWD 'dist\Gemini_Image_Crawler_v1.0.20\Gemini_Image_Crawler_v1.0.20.exe'; if (-not (Test-Path $target)) { [System.Windows.Forms.MessageBox]::Show('실행 파일을 찾을 수 없습니다.' + [Environment]::NewLine + $target, '바로가기 생성 실패', 'OK', 'Error') | Out-Null; exit 1 }; $target = (Resolve-Path $target).ProviderPath; $ws = New-Object -ComObject WScript.Shell; $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Gemini 이미지 수집기 V2.0.lnk'; $sc = $ws.CreateShortcut($lnk); $sc.TargetPath = $target; $sc.WorkingDirectory = Split-Path $target -Parent; $sc.Description = 'Gemini 이미지 수집기 V2.0 (v1.0.20)'; $sc.IconLocation = $target + ',0'; $sc.Save(); [System.Windows.Forms.MessageBox]::Show('바탕화면에 [Gemini 이미지 수집기] 바로가기를 만들었습니다. (v1.0.20)', '설치 완료', 'OK', 'Information') | Out-Null"
set "RC=%errorlevel%"

popd
if not "%RC%"=="0" (
    echo [오류] 바로가기 생성에 실패했습니다.
    echo        - 위에 표시된 메시지를 확인하거나, 관리자 권한으로 다시 실행해보세요.
    pause
)
:: 실패 사유를 호출한 쪽에도 그대로 전달한다 (pause 의 종료코드 0 에 덮이지 않게)
exit /b %RC%
