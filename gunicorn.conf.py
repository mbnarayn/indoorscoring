# Loaded automatically by gunicorn from the working directory; App Service supplies --bind and --timeout.
worker_class = "uvicorn_worker.UvicornWorker"
# One process: match saves are serialised in-process.
workers = 1
forwarded_allow_ips = "*"
