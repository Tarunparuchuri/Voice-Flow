import os

# Colors
ORANGE = "#FF6600"

# Dark Mode Colors
DARK_BG = "#0F0F0F"
DARK_CARD = "#1A1A1A"
DARK_TEXT = "#FFFFFF"
DARK_BORDER = "#FF6600"

# Light Mode Colors
LIGHT_BG = "#FFFFFF"
LIGHT_CARD = "#F0F0F0"
LIGHT_TEXT = "#121212"
LIGHT_BORDER = "#FF6600"

# Paths
LOGO_PATH = r"C:\Projects\Vibe Coding Projects\Voice Flow\Logo.png"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "voice_flow.db")
TEMP_WAV_PATH = os.path.join(APP_DIR, "temp_recording.wav")

# Default Settings
DEFAULT_SETTINGS = {
    "theme": "dark",          # "dark" or "light"
    "hold_duration": 0.5,     # minimum seconds to trigger hold
    "idle_timeout": 5000,     # milliseconds before capsule fades out
    "opacity_idle": 0.15,      # opacity when capsule is idle
    "opacity_active": 1.0,    # opacity when capsule is active
}
