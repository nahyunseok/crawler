import json
import os
from src.utils.logger import get_logger

class ConfigManager:
    def __init__(self, config_path="config/settings.json"):
        self.config_path = config_path
        self.logger = get_logger()
        self.default_config = {
            "min_width": 100,
            "min_height": 100,
            "allowed_extensions": [".jpg", ".jpeg", ".png", ".webp"],
            "headless": True,
            "timeout": 30,
            "max_scrolls": 0, # 0 means infinite
            "user_agent_rotation": True,
            "random_delay_min": 1,
            "random_delay_max": 3
        }
        self.config = self.load_config()

    def load_config(self):
        """Loads configuration from file or returns default if not found."""
        if not os.path.exists(self.config_path):
            self.logger.info("Config file not found. Creating default config.")
            self.save_config(self.default_config)
            return self.default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return self.default_config

    def save_config(self, config):
        """Saves configuration to file."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            self.config = config
            self.logger.info("Configuration saved successfully.")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def get(self, key, default=None):
        """Retrieves a configuration value."""
        return self.config.get(key, default)

    def set(self, key, value):
        """Sets a configuration value and saves it."""
        self.config[key] = value
        self.save_config(self.config)
