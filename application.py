"""Entry point App Service auto-detects (`gunicorn application:app`); see gunicorn.conf.py."""

from app.main import app

__all__ = ["app"]
