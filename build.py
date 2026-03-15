import os
import sys
import shutil
import subprocess

def bump_version():
    version_file = "version.txt"
    if not os.path.exists(version_file):
        with open(version_file, "w") as f:
            f.write("1.0.0")
        return "1.0.0"

    with open(version_file, "r") as f:
        version = f.read().strip()
    
    parts = version.split('.')
    if len(parts) == 3:
        major, minor, patch = parts
        patch = str(int(patch) + 1)
        new_version = f"{major}.{minor}.{patch}"
    else:
        new_version = "1.0.1"

    with open(version_file, "w") as f:
        f.write(new_version)
    
    return new_version

def clean_build():
    print("🧹 Cleaning previous builds...")
    dirs_to_clean = ["build", "dist"]
    files_to_clean = ["main.spec"]
    
    for d in dirs_to_clean:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Removed directory: {d}")
            
    for f in files_to_clean:
        if os.path.exists(f):
            os.remove(f)
            print(f"Removed file: {f}")

def build_exe(version):
    print(f"🚀 Building executable (v{version})...")
    
    # CustomTkinter needs some special packaging sometimes, but usually --noconsole and basic add-data is fine
    # For undetected_chromedriver, we don't need special assets but standard pyinstaller works
    
    try:
        import webdriver_manager
        wm_path = os.path.dirname(webdriver_manager.__file__)
        add_data_wm = f"{wm_path};webdriver_manager"
    except ImportError:
        add_data_wm = None

    try:
        import undetected_chromedriver
        uc_path = os.path.dirname(undetected_chromedriver.__file__)
        add_data_uc = f"{uc_path};undetected_chromedriver"
    except ImportError:
        add_data_uc = None

    try:
        import fake_useragent
        fa_path = os.path.dirname(fake_useragent.__file__)
        add_data_fa = f"{fa_path};fake_useragent"
    except ImportError:
        add_data_fa = None

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed", # Don't show console (set --console for debugging if needed, but we keep it windowed for release)
        "--name", f"Gemini_Image_Crawler_v{version}",
        "--icon", "app_icon.ico",
        "--add-data", f"version.txt;.", # Include version file
        "--add-data", f"app_icon.ico;.", # Include icon inside the bundle for tkinter
    ]
    
    if add_data_wm:
        cmd.extend(["--add-data", add_data_wm])
    else:
        cmd.extend(["--collect-all", "webdriver_manager"])
        
    if add_data_uc:
        cmd.extend(["--add-data", add_data_uc])
    else:
        cmd.extend(["--collect-all", "undetected_chromedriver"])

    if add_data_fa:
        cmd.extend(["--add-data", add_data_fa])
    else:
        cmd.extend(["--collect-all", "fake_useragent"])
        
    cmd.append("main.py")
    
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("✅ Build Completed!")

def generate_shortcut_script(version):
    print(f"🔗 Generating shortcut script for v{version}...")
    bat_content = f"""@echo off
chcp 65001 >nul

:: PowerShell을 이용해 바탕화면에 깔끔하게 바로가기 생성 및 아이콘 적용
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $ErrorActionPreference = 'Stop'; $wshShell = New-Object -ComObject WScript.Shell; $desktopPath = [Environment]::GetFolderPath('Desktop'); $shortcutPath = Join-Path $desktopPath 'Gemini 이미지 수집기 V2.0.lnk'; $targetPath = Join-Path $PWD 'dist\Gemini_Image_Crawler_v{version}\Gemini_Image_Crawler_v{version}.exe'; $shortcut = $wshShell.CreateShortcut($shortcutPath); $shortcut.TargetPath = $targetPath; $shortcut.WorkingDirectory = Join-Path $PWD 'dist\Gemini_Image_Crawler_v{version}'; $shortcut.Description = 'Gemini 이미지 수집기 V2.0 실행'; $shortcut.IconLocation = Join-Path $PWD 'app_icon.ico'; $shortcut.Save(); [System.Windows.Forms.MessageBox]::Show('바탕화면에 [Gemini 이미지 수집기 V2.0] 바로가기가 생성되었습니다!', '설치 완료', 'OK', 'Information')"

if %errorlevel% neq 0 (
    echo [오류] 바로가기 생성에 실패했습니다. 관리자 권한으로 실행해보세요.
    pause
)
"""
    with open("바로가기_만들기.bat", "w", encoding="utf-8") as f:
        f.write(bat_content)

def generate_git_command(version):
    print("\n" + "="*50)
    print("🎉 배포판 빌드가 완료되었습니다! (dist 폴더 확인)")
    print("설명서(Manual) 파일과 함께 사용자에게 배포하세요.")
    print("📌 아래 복사 버튼을 누르듯 다음 Git 명령어를 터미널에 복사-붙여넣기 하여 릴리즈 버전을 태깅하세요:\n")
    tag_command = f'git commit -am "Release v{version}" && git tag -a v{version} -m "Release version {version}" && git push origin v{version}'
    print(tag_command)
    print("="*50 + "\n")

if __name__ == "__main__":
    clean_build()
    new_version = bump_version()
    print(f"📈 Version bumped to: {new_version}")
    try:
        generate_shortcut_script(new_version)
        build_exe(new_version)
        generate_git_command(new_version)
    except Exception as e:
        print(f"❌ Build failed: {e}")
