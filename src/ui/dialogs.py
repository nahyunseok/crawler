"""앱 테마와 같은 스타일의 알림·확인 대화상자.

⛔ 수정금지(DO NOT MODIFY / DO NOT REPLACE WITH tkinter.messagebox — INTENDED)
무엇: tkinter.messagebox 대신 여기 있는 함수들을 쓴다.
왜:   이 프로그램은 다크 테마(customtkinter)로 강제되어 있는데, tkinter.messagebox 는
      운영체제 기본(밝은 회색) 대화상자를 띄운다. 그래서 체크박스를 하나 누르면
      화면 스타일이 갑자기 90년대 윈도우 창으로 바뀌어 완성도가 크게 떨어져 보였다.
      (실제 사용자 지적: "클릭하면 디자인 스타일이 바뀐다")
건드리면: 앱 안에서 두 가지 디자인 언어가 섞이는 상태로 되돌아간다.

사용법 (반환값은 tkinter.messagebox 와 같은 의미):
    show_info(parent, "안내", "저장했습니다.")
    if ask_yes_no(parent, "삭제 확인", "정말 지울까요?", danger=True): ...
"""
import customtkinter as ctk

# 종류별 아이콘과 강조색 — 색은 customtkinter 기본 팔레트와 어울리는 값으로 맞춘다
KIND_STYLES = {
    "info":     ("ℹ️", "#3B8ED0"),
    "success":  ("✅", "#2FA572"),
    "warning":  ("⚠️", "#D68910"),
    "error":    ("⛔", "#C0392B"),
    "question": ("❓", "#3B8ED0"),
}

DIALOG_WIDTH = 460
TEXT_WRAP = DIALOG_WIDTH - 110   # 아이콘·여백을 뺀 실제 글자 폭


class ThemedDialog(ctk.CTkToplevel):
    """앱과 같은 다크 테마를 쓰는 모달 대화상자."""

    def __init__(self, parent, title, message, kind="info",
                 buttons=(("확인", True),), danger=False):
        super().__init__(parent)
        self.result = None
        icon, accent = KIND_STYLES.get(kind, KIND_STYLES["info"])

        self.title(title)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grid_columnconfigure(0, weight=1)

        # 상단 강조 띠 — 종류(정보/경고/오류)를 색으로 즉시 구분시켜 주는 시그니처 요소
        accent_bar = ctk.CTkFrame(self, height=4, fg_color=accent, corner_radius=0)
        accent_bar.grid(row=0, column=0, sticky="ew")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(20, 0))
        body.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(body, text=icon, font=ctk.CTkFont(size=30)).grid(
            row=0, column=0, sticky="n", padx=(0, 16)
        )

        ctk.CTkLabel(
            body, text=title, font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w", justify="left"
        ).grid(row=0, column=1, sticky="ew")

        ctk.CTkLabel(
            body, text=message, font=ctk.CTkFont(size=13),
            wraplength=TEXT_WRAP, justify="left", anchor="w", text_color="gray75"
        ).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        # 버튼 줄 — 오른쪽 정렬, 마지막(주요) 버튼이 가장 오른쪽에 온다
        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.grid(row=2, column=0, sticky="e", padx=24, pady=(22, 20))

        self._primary_button = None
        for index, (text, value) in enumerate(buttons):
            is_primary = index == len(buttons) - 1
            button = ctk.CTkButton(
                button_row, text=text, width=104, height=34,
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda v=value: self._close_with(v),
            )
            if not is_primary:
                # 보조 버튼은 사이드바와 같은 '투명 + 테두리' 언어를 쓴다(앱 전체 일관성)
                button.configure(fg_color="transparent", border_width=1, text_color="gray80")
            elif danger:
                # 되돌릴 수 없는 선택은 빨간 버튼으로 한 번 더 경고한다
                button.configure(fg_color="#C0392B", hover_color="#96281B")

            button.pack(side="left", padx=(8, 0))
            if is_primary:
                self._primary_button = button

        # 키보드: Enter = 주요 버튼, Esc = 취소 (기본 대화상자와 같은 감각)
        self.bind("<Return>", lambda _e: self._close_with(buttons[-1][1]))
        self.bind("<Escape>", lambda _e: self._on_cancel())

        self._center_on(parent)
        self._make_modal(parent)

    # ──────────────────────────────────────────────────────────
    def _center_on(self, parent):
        """부모 창 중앙에 띄운다. 부모 정보를 못 읽으면 화면 중앙으로 보낸다."""
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), DIALOG_WIDTH)
        height = self.winfo_reqheight()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            if pw <= 1 or ph <= 1:
                raise ValueError("부모 크기를 아직 알 수 없음")
            x = px + (pw - width) // 2
            y = py + (ph - height) // 3      # 살짝 위쪽이 시각적으로 안정적이다
        except Exception:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 3
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def _make_modal(self, parent):
        """
        다른 조작을 막고 이 창만 받도록 만든다.

        ⛔ grab_set() 을 곧바로 부르면 창이 아직 화면에 올라오지 않아 실패할 수 있다
           (customtkinter + 윈도우 조합에서 자주 나는 문제). 그래서 잠깐 뒤에 다시 시도한다.
        """
        self.transient(parent)
        self.lift()
        self.after(10, self._grab)
        if self._primary_button is not None:
            try:
                self._primary_button.focus_set()
            except Exception:
                pass

    def _grab(self):
        try:
            self.grab_set()
        except Exception:
            pass

    def _close_with(self, value):
        self.result = value
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _on_cancel(self):
        # 창을 닫거나 Esc = '아니오/취소'. 확인만 있는 창에서는 None 이 된다.
        self._close_with(False if self.result is None else self.result)


# ──────────────────────────────────────────────────────────────
# 바깥에서 쓰는 함수들 (tkinter.messagebox 와 같은 사용감)
# ──────────────────────────────────────────────────────────────
def _run(parent, title, message, kind, buttons, danger=False):
    dialog = ThemedDialog(parent, title, message, kind=kind, buttons=buttons, danger=danger)
    parent.wait_window(dialog)     # 사용자가 닫을 때까지 여기서 기다린다
    return dialog.result


def show_info(parent, title, message):
    return _run(parent, title, message, "info", (("확인", True),))


def show_success(parent, title, message):
    return _run(parent, title, message, "success", (("확인", True),))


def show_warning(parent, title, message):
    return _run(parent, title, message, "warning", (("확인", True),))


def show_error(parent, title, message):
    return _run(parent, title, message, "error", (("확인", True),))


def ask_yes_no(parent, title, message, kind="question",
               yes_text="예", no_text="아니오", danger=False):
    """예/아니오 확인. 반환값은 bool (tkinter 의 askyesno 와 동일)."""
    result = _run(parent, title, message, kind,
                  ((no_text, False), (yes_text, True)), danger=danger)
    return bool(result)
