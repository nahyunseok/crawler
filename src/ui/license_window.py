import customtkinter as ctk
import tkinter.messagebox as messagebox
import sys
import os

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class LicenseWindow(ctk.CTkToplevel):
    def __init__(self, parent, license_manager, on_success_callback):
        super().__init__(parent)
        
        self.license_manager = license_manager
        self.on_success_callback = on_success_callback
        
        self.title("Gemini Image Crawler - 라이센스 인증")
        self.geometry("400x250")
        self.resizable(False, False)
        
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)
        
        # Center the window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (400 // 2)
        y = (self.winfo_screenheight() // 2) - (250 // 2)
        self.geometry(f"+{x}+{y}")
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self.create_widgets()
        
        # Intercept close button
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_widgets(self):
        self.label_title = ctk.CTkLabel(self, text="라이센스 키를 입력하세요", font=ctk.CTkFont(size=16, weight="bold"))
        self.label_title.pack(pady=(30, 10))
        
        self.label_desc = ctk.CTkLabel(self, text="(테스트용 키: test4321)", text_color="gray", font=ctk.CTkFont(size=12))
        self.label_desc.pack(pady=(0, 20))
        
        self.key_entry = ctk.CTkEntry(self, width=300, placeholder_text="예: test4321")
        self.key_entry.pack(pady=10)
        
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(pady=10)
        
        self.verify_btn = ctk.CTkButton(self.btn_frame, text="인증하기", command=self.verify_key)
        self.verify_btn.pack(side="left", padx=10)
        
        self.exit_btn = ctk.CTkButton(self.btn_frame, text="종료", fg_color="red", hover_color="darkred", command=self.on_close)
        self.exit_btn.pack(side="left", padx=10)

    def verify_key(self):
        key = self.key_entry.get()
        if not key:
            messagebox.showwarning("오류", "라이센스 키를 입력해주세요.")
            return
            
        success, message = self.license_manager.validate_key(key)
        
        if success:
            messagebox.showinfo("성공", message)
            self.on_success_callback()
            self.destroy()
        else:
            messagebox.showerror("실패", message)
            
    def on_close(self):
        # If they close without validating, we must exit the app
        import sys
        sys.exit(0)
