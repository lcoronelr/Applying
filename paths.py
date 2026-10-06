"""Where the owner's files live (profile, resume, jobs.xlsx, letters, screenshots, submissions, friends' profiles).

1. $APPLY_DATA if set (the app sets it)
2. ~/Library/Application Support/Apply/Data — the app's home, shared by the app and the command line
3. this project folder (before anything was moved to 2)
"""
import os
from pathlib import Path

CODE = Path(__file__).parent
APP_DATA = Path.home() / "Library" / "Application Support" / "Apply" / "Data"


def home():
    if os.environ.get("APPLY_DATA"):
        return Path(os.environ["APPLY_DATA"])
    if (APP_DATA / "profile.json").exists():
        return APP_DATA
    return CODE
