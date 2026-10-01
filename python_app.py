"""Convenience launcher: `python python_app.py` starts the same application as `python app.py`."""
from app import app

if __name__ == "__main__":
    app.run(port=5000)
