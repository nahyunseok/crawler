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
        "--name", app_name(version),
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
    folder_name = app_name(version)
    source_dir = app_dist_dir(version)
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

SHORTCUT_LNK_NAME = "Gemini 이미지 수집기 V2.0.lnk"
SHORTCUT_BAT_NAME = "바로가기_만들기.bat"
APP_BASE_NAME = "Gemini_Image_Crawler"
PACKAGED_DOCS = ("MANUAL.md", "CHANGELOG.md")


def app_name(version):
    """
    배포 폴더 이름 · exe 이름 규칙. (예: Gemini_Image_Crawler_v1.0.17)

    ⛔ 수정금지(DO NOT MODIFY — INTENDED): 이 규칙은 여기 '한 곳'에만 있어야 한다.
    왜: exe 이름·배포 폴더·zip·바로가기 대상이 모두 이 이름을 쓴다. 예전에는 같은 문자열을
        build_exe / zip_build / prepare_package / generate_shortcut_script 4곳에서 각자
        조립했다. 이름 규칙을 바꾸면 일부만 바뀌어, 바로가기가 존재하지 않는 exe 를
        가리키는 사고가 난다(실제로 경로 불일치 사고를 겪었다).
    """
    return f"{APP_BASE_NAME}_v{version}"


def app_dist_dir(version):
    """배포 폴더 경로 (dist/Gemini_Image_Crawler_vX)."""
    return os.path.join("dist", app_name(version))


def app_exe_filename(version):
    """배포 exe 파일명 (Gemini_Image_Crawler_vX.exe)."""
    return f"{app_name(version)}.exe"


def write_shortcut_bat(bat_path, exe_subpath, version):
    """
    바탕화면 바로가기를 만들어주는 .bat 파일을 생성한다.
    exe_subpath: bat 파일이 있는 폴더에서 exe 까지의 '상대 경로'

    ⛔ 수정금지(DO NOT MODIFY / DO NOT REMOVE — INTENDED)
    무엇: ① 경로 기준을 'bat 파일 자기 위치'(pushd "%~dp0")로 잡는다.
          ② 바로가기 아이콘을 프로젝트의 app_icon.ico 가 아니라 exe 자체($target,0)에서 가져온다.
          ③ exe 가 없으면 바로가기를 만들지 않고 실패를 알린다.
    왜:   ① 예전 코드는 '실행 시점의 현재 폴더($PWD)'를 기준으로 삼았다. 그래서 bat 을 다른
             폴더에서 호출하거나 정션·링크 경로를 경유하면 엉뚱한 경로가 바로가기에 박혔다.
             실제 사고: v1.0.16 을 배포한 뒤에도 바탕화면 아이콘이 옛 폴더의 v1.0.15 exe 를
             계속 실행해서, 프로그램 화면에 구버전(1.0.15)이 표시됐다.
          ② 아이콘을 exe 와 '다른 파일'로 지정하면, exe 는 살아있는데 아이콘 파일만 없어져
             아이콘이 깨진 상태가 된다(실제로 발생). 또 고객은 zip(exe 폴더)만 받으므로
             프로젝트 루트의 app_icon.ico 가 애초에 존재하지 않는다.
             exe 를 아이콘 원본으로 쓰면 대상과 아이콘이 같은 파일이라 절대 어긋나지 않는다.
          ③ 조용히 성공한 척하면 사용자는 깨진 바로가기를 받는다(침묵 실패 금지).
    건드리면: 버전을 올려도 바탕화면 바로가기가 구버전을 가리키는 사고가 재발한다.
    """
    print(f"🔗 Generating {bat_path} (target: {exe_subpath})")

    # PowerShell 한 줄 명령. 큰따옴표 이스케이프 사고를 피하려고 문자열은 전부 작은따옴표를 쓴다.
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$ErrorActionPreference = 'Stop'; "
        f"$target = Join-Path $PWD '{exe_subpath}'; "
        "if (-not (Test-Path $target)) { "
        "[System.Windows.Forms.MessageBox]::Show("
        "'실행 파일을 찾을 수 없습니다.' + [Environment]::NewLine + $target, "
        "'바로가기 생성 실패', 'OK', 'Error') | Out-Null; exit 1 }; "
        "$target = (Resolve-Path $target).ProviderPath; "
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '{SHORTCUT_LNK_NAME}'; "
        "$sc = $ws.CreateShortcut($lnk); "
        "$sc.TargetPath = $target; "
        "$sc.WorkingDirectory = Split-Path $target -Parent; "
        f"$sc.Description = 'Gemini 이미지 수집기 V2.0 (v{version})'; "
        "$sc.IconLocation = $target + ',0'; "
        "$sc.Save(); "
        "[System.Windows.Forms.MessageBox]::Show("
        f"'바탕화면에 [Gemini 이미지 수집기] 바로가기를 만들었습니다. (v{version})', "
        "'설치 완료', 'OK', 'Information') | Out-Null"
    )

    bat_content = f"""@echo off
chcp 65001 >nul
:: 이 배치파일이 놓인 폴더를 기준으로 동작한다 (어디서 실행해도 경로가 어긋나지 않게)
pushd "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "{ps}"
set "RC=%errorlevel%"

popd
if not "%RC%"=="0" (
    echo [오류] 바로가기 생성에 실패했습니다.
    echo        - 위에 표시된 메시지를 확인하거나, 관리자 권한으로 다시 실행해보세요.
    pause
)
:: 실패 사유를 호출한 쪽에도 그대로 전달한다 (pause 의 종료코드 0 에 덮이지 않게)
exit /b %RC%
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)


def prepare_package(version):
    """
    배포 폴더(dist/Gemini_Image_Crawler_vX) 안에 고객에게 필요한 파일을 함께 넣는다.

    ⛔ 수정금지(DO NOT MODIFY — INTENDED)
    무엇: 바로가기 생성 bat 과 매뉴얼을 exe 와 '같은 폴더'에 복사한다.
    왜:   zip 은 이 폴더만 압축한다(zip_build). 예전에는 bat 과 매뉴얼이 프로젝트 루트에만
          있어서 zip 에 포함되지 않았고, 고객은 exe 파일 하나만 받았다.
          → 바로가기 자동 생성·매뉴얼 제공(전역수칙 7 상품성)이 고객에게는 아예 없었다.
    건드리면: 고객이 바탕화면 바로가기를 만들 방법과 설명서를 못 받는다.
    """
    folder = app_dist_dir(version)
    # ⛔ 침묵 실패 금지: 여기까지 왔으면 build_exe 가 성공했으므로 폴더는 반드시 있어야 한다.
    #    없다면 비정상 상황이므로 조용히 넘기지 않고 빌드를 실패시킨다.
    if not os.path.exists(folder):
        raise FileNotFoundError(f"배포 폴더를 찾을 수 없습니다: {folder}")

    # 고객용 bat — exe 와 같은 폴더에 있으므로 상대경로는 exe 파일명 하나뿐이다
    write_shortcut_bat(
        os.path.join(folder, SHORTCUT_BAT_NAME),
        app_exe_filename(version),
        version,
    )

    # ⛔ 침묵 축소 금지: 매뉴얼이 빠진 배포판이 조용히 나가면 상품성 결함이 된다(전역수칙 7).
    #    없으면 반드시 경고를 띄워 사람이 알아차리게 한다.
    for doc in PACKAGED_DOCS:
        if os.path.exists(doc):
            shutil.copy2(doc, os.path.join(folder, doc))
            print(f"📄 Packaged: {doc}")
        else:
            print(f"⚠️ 동봉할 문서가 없습니다: {doc} — 고객은 이 문서를 받지 못합니다!")


def generate_shortcut_script(version):
    """개발자(프로젝트 루트)용 bat — dist 폴더 안의 exe 를 가리킨다."""
    exe_subpath = os.path.join(app_dist_dir(version), app_exe_filename(version))
    write_shortcut_bat(SHORTCUT_BAT_NAME, exe_subpath, version)

def generate_git_command(version):
    print("\n" + "="*50)
    print("🎉 배포판 빌드가 완료되었습니다! (dist 폴더 확인)")
    print("📦 zip 안에 매뉴얼과 바로가기 생성 도구가 함께 들어 있습니다.")
    # ⛔ 이 안내를 지우지 말 것: 새 버전을 빌드하면 이전 버전 폴더가 사라지므로,
    #    바탕화면 바로가기가 없어진 exe 를 가리켜 '구버전이 실행되는' 사고가 났다.
    print(f"\n⚠️ 바탕화면 바로가기를 반드시 갱신하세요 (이전 버전 폴더는 삭제되었습니다):")
    print(f"    {SHORTCUT_BAT_NAME}  ← 더블클릭")
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
        build_exe(new_version)
        # ⛔ 수정금지: prepare_package 는 zip_build 보다 '먼저' 실행한다.
        #    zip 은 배포 폴더를 그대로 압축하므로, 동봉 파일을 먼저 넣어야 zip 에 포함된다.
        prepare_package(new_version)
        generate_shortcut_script(new_version)
        zip_build(new_version)
        generate_git_command(new_version)
    except Exception as e:
        # ⛔ 침묵 실패 금지: 실패한 빌드가 성공처럼 끝나면 깨진 배포판을 그대로 릴리스하게 된다.
        print(f"❌ Build failed: {e}")
        sys.exit(1)
