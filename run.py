"""Точка запуска АИС: python run.py  (http://127.0.0.1:5000)."""
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("AIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("AIS_PORT", "5000")),
            debug=os.environ.get("AIS_DEBUG", "0") == "1")
