FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/Back-end
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY migrations migrations
COPY app app
EXPOSE 8000
# Database changes are applied on start.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
