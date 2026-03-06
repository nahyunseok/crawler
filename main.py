import os
import sys
from src.ui.main_window import MainWindow
from src.ui.license_window import LicenseWindow
from src.core.license_manager import LicenseManager
import customtkinter as ctk
from src.utils.logger import setup_logger
import tkinter as tk

def main():
    # Setup logging
    setup_logger()
    
    # Initialize GUI framework base
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    
    root = ctk.CTk()
    root.withdraw() # Hide the root blank window initially
    
    lm = LicenseManager()
    is_valid, status_msg, days = lm.get_license_status()
    
    def start_main_app():
        root.destroy() # Destroy the temp root
        app = MainWindow(lm) # Pass license manager to main window
        app.mainloop()

    if is_valid:
        start_main_app()
    else:
        # Show license window
        lw = LicenseWindow(root, lm, start_main_app)
        root.mainloop() # Start event loop for the license window

if __name__ == "__main__":
    main()
