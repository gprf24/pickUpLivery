# Python 3.11.9 slim
FROM python:3.11.9-slim-bookworm

# sane defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# system deps (для колёс и сборок)
RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) ставим зависимости из [project].dependencies (без сборки локального пакета)
COPY pyproject.toml README.md ./
RUN python - <<'PY'
import tomllib, subprocess, sys
with open('pyproject.toml','rb') as f:
    data = tomllib.load(f)
deps = data.get('project', {}).get('dependencies', [])
if not deps:
    raise SystemExit("No [project].dependencies found in pyproject.toml")
# обновим pip/setuptools/wheel — меньше сюрпризов со сборками
subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade", "pip", "setuptools", "wheel"])
# поставим зависимости проекта
subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *deps])
PY

# 2) копируем остальное приложение
COPY . .

# 3) запуск (контейнер слушает 80; в compose маппинг 8000:80)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
