# Python 3.11.9 slim
FROM python:3.11.9-slim-bookworm

# sane defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# system dependencies (for wheels and builds)
RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) install dependencies from [project].dependencies (without building the local package)
COPY pyproject.toml README.md ./
RUN python - <<'PY'
import tomllib, subprocess, sys
with open('pyproject.toml','rb') as f:
    data = tomllib.load(f)
deps = data.get('project', {}).get('dependencies', [])
if not deps:
    raise SystemExit("No [project].dependencies found in pyproject.toml")
# upgrade pip/setuptools/wheel — fewer surprises with builds
subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip", "setuptools", "wheel"])
# install project dependencies
subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *deps])
PY

# 2) copy the rest of the application
COPY . .

# 3) start the server (container listens on port 80; docker-compose maps 8000:80)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
