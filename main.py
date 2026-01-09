import os
import sys
from src.ui.main_window import MainWindow
import customtkinter as ctk
from src.utils.logger import setup_logger

def main():
    # Setup logging
    setup_logger()
    
    # Initialize GUI
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    
    app = MainWindow()
    app.mainloop()

if __name__ == "__main__":
    main()
