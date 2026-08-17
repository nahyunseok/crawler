import os
import sys
import glob
import shutil
import subprocess

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

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
    """이전 빌드 잔재를 모두 지운다 (전역수칙 10: 클린 빌드)."""
    print("🧹 Cleaning previous builds...")
    dirs_to_clean = ["build", "dist"]

    for d in dirs_to_clean:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"Removed directory: {d}")

    # PyInstaller 가 남기는 .spec 파일 (버전이 올라갈수록 계속 쌓인다)
    for f in glob.glob("*.spec"):
        os.remove(f)
        print(f"Removed file: {f}")

    # 파이썬 캐시도 함께 정리 (구버전 코드가 exe 에 섞여 들어가는 사고 방지)
    for root, dirs, _files in os.walk("."):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)

def build_exe(version):
    print(f"🚀 Building executable (v{version})...")
    
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
        "--windowed",
        "--name", f"Gemini_Image_Crawler_v{version}",
        "--icon", "app_icon.ico",
        "--add-data", f"version.txt;.",
        "--add-data", f"app_icon.ico;.",
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

def zip_build(version):
    """빌드된 폴더를 ZIP 파일로 압축합니다."""
    dist_path = "dist"
    folder_name = f"Gemini_Image_Crawler_v{version}"
    source_dir = os.path.join(dist_path, folder_name)
    zip_filename = os.path.join(dist_path, folder_name) # .zip extension will be added by make_archive
    
    if not os.path.exists(source_dir):
        print(f"❌ Error: Source directory {source_dir} not found for zipping.")
        return

    print(f"📦 Zipping build into {folder_name}.zip...")
    try:
        shutil.make_archive(zip_filename, 'zip', root_dir=dist_path, base_dir=folder_name)
        print(f"✅ Compression successful: {folder_name}.zip")
    except Exception as e:
        print(f"❌ Compression failed: {e}")

def generate_shortcut_script(version):
    print(f"🔗 Generating shortcut script for v{version}...")
    bat_content = f"""@echo off
chcp 65001 >nul

:: PowerShell을 이용해 바탕화면에 깔끔하게 바로가기 생성 및 아이콘 적용
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $ErrorActionPreference = 'Stop'; $wshShell = New-Object -ComObject WScript.Shell; $desktopPath = [Environment]::GetFolderPath('Desktop'); $shortcutPath = Join-Path $desktopPath 'Gemini 이미지 수집기 V2.0.lnk'; $targetPath = Join-Path $PWD 'dist\\Gemini_Image_Crawler_v{version}\\Gemini_Image_Crawler_v{version}.exe'; $shortcut = $wshShell.CreateShortcut($shortcutPath); $shortcut.TargetPath = $targetPath; $shortcut.WorkingDirectory = Join-Path $PWD 'dist\\Gemini_Image_Crawler_v{version}'; $shortcut.Description = 'Gemini 이미지 수집기 V2.0 실행'; $shortcut.IconLocation = Join-Path $PWD 'app_icon.ico'; $shortcut.Save(); [System.Windows.Forms.MessageBox]::Show('바탕화면에 [Gemini 이미지 수집기 V2.0] 바로가기가 생성되었습니다!', '설치 완료', 'OK', 'Information')"

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

def run_preflight():
    """
    빌드 전 필수 품질점검 게이트 (전역수칙 10).

    ⛔ 수정금지(DO NOT MODIFY / DO NOT REMOVE — INTENDED)
    무엇: clean_build() 와 bump_version() 보다 '먼저' 실행한다.
    왜:   ① 점검 실패 시 버전이 올라가 있으면 version.txt 를 손으로 되돌려야 한다.
          ② dist/ 를 지운 뒤에 실패하면 이전 배포판까지 잃는다.
          ③ 배포판 exe 가 실행 중이면 dist/ 가 잠겨 rmtree 가 깨지는데,
             게이트가 그것을 먼저 잡아준다.
    건드리면: 실패한 빌드가 버전만 올리고 산출물은 없는 상태로 끝난다.

    통과 못 하면 빌드를 중단한다. 정말 급하면 사용자가 직접:
        python tools/preflight.py --skip "긴급 핫픽스 사유"
    """
    gate = os.path.join("tools", "preflight.py")
    if not os.path.exists(gate):
        print("⚠️ tools/preflight.py 가 없어 품질점검을 건너뜁니다 (게이트 설치를 권장).")
        return

    print("🛫 빌드 전 품질점검(Preflight)을 실행합니다...\n")
    result = subprocess.run([sys.executable, gate, *sys.argv[1:]])
    if result.returncode != 0:
        print("\n⛔ 품질점검을 통과하지 못해 빌드를 중단합니다.")
        print("   (위 ❌ 항목을 해결한 뒤 다시 실행하세요. 버전은 올라가지 않았습니다)")
        sys.exit(1)
    print()


if __name__ == "__main__":
    run_preflight()
    clean_build()
    new_version = bump_version()
    print(f"📈 Version bumped to: {new_version}")
    try:
        generate_shortcut_script(new_version)
        build_exe(new_version)
        zip_build(new_version)
        generate_git_command(new_version)
    except Exception as e:
        print(f"❌ Build failed: {e}")
