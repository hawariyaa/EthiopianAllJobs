"""Admin API. Shares the database, models and password hashing with Back-end rather than copying them."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "Back-end"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
