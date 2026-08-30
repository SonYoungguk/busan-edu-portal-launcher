"""필요한 사이트들을 순서대로 한 창에 탭으로 열어주는 런처.

기본 순서: 클로드 웹사이트 -> 부산교육연수원 -> 구글 클래스룸 -> Playkit -> 업무포털
           -> (로그인 후) 나이스 -> K-에듀파인

인증서 로그인(PIN 입력)은 사용자가 직접 완료해야 하며, 이 스크립트는 그 창에는
관여하지 않는다. 업무포털 로그인 완료 여부만 화면 요소로 감지해서, 완료되면:
- K-에듀파인은 klef.pen.go.kr 세션 쿠키가 업무포털과 공유되어 URL을 바로 열어도
  로그인 상태로 뜨므로, 새 탭으로 직접 연다.
- 나이스는 별도 도메인(neis.go.kr)이라 세션이 공유되지 않아, 업무포털의 SSO
  바로가기 버튼을 실제로 클릭해서 넘어간다.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    from pywinauto import Desktop
    import psutil
except ImportError:
    print("필요한 패키지가 설치되어 있지 않습니다. 'pip install -r requirements.txt'를 먼저 실행하세요.")
    sys.exit(1)

EDGE_WINDOW_CLASS = "Chrome_WidgetWin_1"

DEFAULT_CONFIG = {
    "extra_urls": [
        "https://claude.ai",
        "https://edu.beti.go.kr/",
        "https://classroom.google.com",
        "https://sonyoungguk.github.io/playkit/",
    ],
    "portal_url": "https://pen.eduptl.kr/bpm_man_mn00_001.do",
    "login_indicator_text": "Logout",
    "login_button_text": "교육행정 전자서명 인증서 로그인",
    "nice_link_text": "나이스",
    "edufine_url": "https://klef.pen.go.kr/",
    "notice_dismiss_texts": ["1주일동안 열지 않기"],
    "timeout_seconds": 300,
    "poll_interval_seconds": 1,
}


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def log_path() -> Path:
    return base_dir() / "launcher.log"


def config_path() -> Path:
    return base_dir() / "config.json"


def reset_log() -> None:
    """매 실행마다 이전 로그를 지우고 새로 시작한다 (매일 자동 실행돼도 파일이 무한정 커지지 않도록)."""
    try:
        log_path().write_text("", encoding="utf-8")
    except Exception:
        pass


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    """기본값은 코드에 내장되어 있어 exe 파일 하나만 있어도 동작한다.
    옆에 config.json이 있으면 그 값으로 필요한 항목만 덮어쓴다(선택 사항)."""
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            log(f"config.json을 읽지 못해 내장된 기본값을 사용합니다: {e}")
    return cfg


def find_edge_path() -> str:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    found = shutil.which("msedge")
    if found:
        return found
    raise FileNotFoundError("msedge.exe 경로를 찾을 수 없습니다.")


def is_edge_process(pid: int) -> bool:
    try:
        return psutil.Process(pid).name().lower() == "msedge.exe"
    except Exception:
        return False


def get_edge_windows() -> dict:
    # class_name is Chrome_WidgetWin_1 for every Chromium-based app (Edge, Chrome,
    # Electron apps like Claude desktop, ...), so filter by owning process too.
    windows = {}
    for w in Desktop(backend="uia").windows(class_name=EDGE_WINDOW_CLASS):
        try:
            if not is_edge_process(w.process_id()):
                continue
            windows[w.handle] = w
        except Exception:
            continue
    return windows


def wait_for_new_window(before: dict, timeout: int = 20) -> "object | None":
    deadline = time.time() + timeout
    while time.time() < deadline:
        after = get_edge_windows()
        new_handles = set(after) - set(before)
        if new_handles:
            return after[next(iter(new_handles))]
        time.sleep(1)
    return None


def find_element_by_text(window, text: str, exact: bool = False, control_type: str = None):
    try:
        descendants = window.descendants()
    except Exception:
        return None
    for elem in descendants:
        try:
            if control_type and elem.element_info.control_type != control_type:
                continue
            name = elem.window_text()
        except Exception:
            continue
        if not name:
            continue
        if (exact and name == text) or (not exact and text in name):
            return elem
    return None


def wait_for_text(window, text: str, timeout: int, interval: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if find_element_by_text(window, text) is not None:
            return True
        time.sleep(interval)
    return False


def dismiss_notices(window, texts, attempts: int = 3) -> None:
    """로그인 직후 뜨는 안내 팝업(예: '1주일동안 열지 않기')이 바로가기 아이콘을 가려
    클릭을 가로채는 걸 막기 위해, 클릭 전에 먼저 닫아본다."""
    for _ in range(attempts):
        dismissed_any = False
        for text in texts:
            elem = find_element_by_text(window, text, exact=False, control_type="Button")
            if elem is None:
                continue
            try:
                elem.click_input()
                log(f"안내 팝업 닫음: '{text}'")
                dismissed_any = True
                time.sleep(1)
            except Exception as e:
                log(f"안내 팝업 닫기 실패('{text}'): {e}")
        if not dismissed_any:
            return


def count_tabs(window) -> "int | None":
    try:
        return len(window.descendants(control_type="TabItem"))
    except Exception:
        return None


def open_tab(window, url: str, settle: float = 0.5) -> None:
    """같은 창 안에 Ctrl+T로 새 탭을 열고 url로 이동한다 (모든 사이트를 한 창에 모으기 위해
    subprocess로 새 창을 띄우는 대신 이 방식을 쓴다)."""
    try:
        window.set_focus()
        time.sleep(0.2)
        window.type_keys("^t")
        time.sleep(0.3)
        window.type_keys(url + "{ENTER}", pause=0.01)
        time.sleep(settle)
    except Exception as e:
        log(f"'{url}' 여는 데 실패: {e}")


def wait_for_navigation(window, before_windows: dict, before_tab_count, timeout: int = 60, interval: int = 1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        after_windows = get_edge_windows()
        if set(after_windows) - set(before_windows):
            return True
        after_tab_count = count_tabs(window)
        if after_tab_count is not None and before_tab_count is not None and after_tab_count > before_tab_count:
            return True
        time.sleep(interval)
    return False


def wait_for_any_tab_containing(text: str, timeout: int = 60, interval: int = 1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in get_edge_windows().values():
            try:
                tabs = w.descendants(control_type="TabItem")
            except Exception:
                continue
            for t in tabs:
                try:
                    name = t.window_text()
                except Exception:
                    continue
                if text in name:
                    return True
        time.sleep(interval)
    return False


def dump_tree(out_name: str = "dump.txt") -> None:
    windows = get_edge_windows()
    if not windows:
        print("열려 있는 Edge 창을 찾을 수 없습니다. Edge에서 업무포털에 로그인한 뒤 다시 실행하세요.")
        return
    if len(windows) > 1:
        print(f"Edge 창이 {len(windows)}개 열려 있습니다. 가장 최근 창을 대상으로 덤프합니다.")
    window = list(windows.values())[-1]

    out_path = base_dir() / out_name
    lines = []
    for elem in window.descendants():
        try:
            name = elem.window_text()
            ctrl = elem.element_info.control_type
        except Exception:
            continue
        if name:
            lines.append(f"[{ctrl}] {name}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(lines)}개 요소를 {out_path} 에 저장했습니다.")
    print("이 파일에서 로그인 후에만 보이는 텍스트, '나이스'/'K-에듀파인' 바로가기 이름을 찾아 config.json에 채워 넣으세요.")


def run() -> None:
    cfg = load_config()
    try:
        edge_path = find_edge_path()
    except FileNotFoundError as e:
        log(str(e))
        return

    # 필요한 사이트들을 순서대로 한 창에 탭으로 연다. 첫 사이트로 창을 새로 띄우고,
    # 나머지(연수원/클래스룸/업무포털)는 같은 창에 탭으로 추가한다.
    extra_urls = cfg.get("extra_urls", [])
    first_url = extra_urls[0] if extra_urls else cfg["portal_url"]

    log(f"Edge 실행: {first_url}")
    before = get_edge_windows()
    try:
        subprocess.Popen([edge_path, "--new-window", first_url])
    except OSError as e:
        log(f"Edge 실행 실패: {e}")
        return

    window = wait_for_new_window(before, timeout=20)
    if window is None:
        log("새 Edge 창을 찾지 못해 기존 Edge 창을 사용합니다.")
        windows = get_edge_windows()
        if not windows:
            log("Edge 창을 찾을 수 없어 종료합니다.")
            return
        window = list(windows.values())[-1]

    time.sleep(0.5)
    for url in extra_urls[1:]:
        log(f"탭 여는 중: {url}")
        open_tab(window, url)

    log(f"업무포털 탭 여는 중: {cfg['portal_url']}")
    open_tab(window, cfg["portal_url"])

    # 창이 뜨자마자 클릭하면 페이지가 아직 렌더링/반응 준비가 안 됐을 수 있어 0.3초 대기.
    time.sleep(0.3)

    # 로그인 전 화면이면 인증서 로그인 버튼을 눌러 인증서 선택/PIN 입력 창을 띄운다.
    # PIN/비밀번호 입력은 사용자가 직접 하며, 이 스크립트는 그 창에 관여하지 않는다.
    log("로그인 화면 확인 중...")
    already_logged_in = False
    login_button_text = cfg.get("login_button_text", "")
    deadline = time.time() + 30
    while time.time() < deadline:
        if find_element_by_text(window, cfg["login_indicator_text"], exact=True) is not None:
            already_logged_in = True
            break
        if login_button_text:
            btn = find_element_by_text(window, login_button_text, exact=True, control_type="Button")
            if btn is not None:
                try:
                    window.set_focus()
                    btn.click_input()
                    log("인증서 로그인 버튼 클릭됨 - 인증서 선택 및 비밀번호 입력을 진행해주세요.")
                except Exception as e:
                    log(f"인증서 로그인 버튼 클릭 실패: {e}")
                break
        time.sleep(1)
    else:
        log("로그인 화면 요소를 30초 안에 찾지 못했습니다. 계속 진행합니다.")

    if already_logged_in:
        log("이미 로그인되어 있습니다.")
    else:
        log("로그인 대기 중...")
        if not wait_for_text(
            window, cfg["login_indicator_text"], cfg["timeout_seconds"], cfg["poll_interval_seconds"]
        ):
            log(f"타임아웃({cfg['timeout_seconds']}초): 로그인 완료를 감지하지 못했습니다.")
            return
    log("로그인 감지됨")

    try:
        window.set_focus()
    except Exception:
        pass
    time.sleep(0.3)
    dismiss_notices(window, cfg.get("notice_dismiss_texts", []))

    # 1) 나이스 먼저: 별도 도메인이라 세션이 공유되지 않으므로, 업무포털의 SSO
    #    바로가기 버튼을 실제로 클릭해서 넘어간다.
    text = cfg["nice_link_text"]
    elem = find_element_by_text(window, text, exact=True, control_type="Hyperlink")
    if elem is None:
        log(f"'{text}' 바로가기를 찾지 못했습니다.")
    else:
        before_windows = get_edge_windows()
        before_tab_count = count_tabs(window)
        try:
            window.set_focus()
            elem.click_input()
            log("나이스 바로가기 클릭됨, 로딩 대기 중...")
        except Exception as e:
            log(f"나이스 바로가기 클릭 실패: {e}")
            elem = None

        if elem is not None:
            if wait_for_navigation(window, before_windows, before_tab_count):
                log("나이스 열림 확인됨")
            else:
                log("나이스 열림을 확인하지 못했습니다 (60초 대기)")

    # 2) 그 다음 K-에듀파인: 업무포털과 세션 쿠키가 공유되므로 같은 창에 새 탭으로 바로 연다.
    log(f"K-에듀파인 여는 중: {cfg['edufine_url']}")
    open_tab(window, cfg["edufine_url"])
    if wait_for_any_tab_containing("에듀파인"):
        log("K-에듀파인 열림 확인됨")
    else:
        log("K-에듀파인 열림을 확인하지 못했습니다 (60초 대기)")

    log("완료")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-tree",
        action="store_true",
        help="이미 로그인된 Edge 창의 화면 요소 이름을 dump.txt로 저장 (설정값 확인용)",
    )
    args = parser.parse_args()

    if args.dump_tree:
        dump_tree()
        return

    reset_log()
    try:
        run()
    except Exception:
        log("예상치 못한 오류로 종료됨:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
