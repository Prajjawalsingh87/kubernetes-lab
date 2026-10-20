import os
import sys
from pathlib import Path

# main.py exits at import time without these; tests never open a real connection.
for name, value in {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "test",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
}.items():
    os.environ.setdefault(name, value)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
