FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache .[prod]

COPY app ./app
COPY manage_users.py wsgi.py ./
COPY config/examples ./config/examples

EXPOSE 8200

CMD ["gunicorn", "-b", "0.0.0.0:8200", "wsgi:app"]
