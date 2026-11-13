# Built from the project root: the admin API reuses Back-end's models, so both are copied in,
# keeping the same folder layout as on disk.
FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY Back-end/requirements.txt Back-end/requirements.txt
RUN pip install --no-cache-dir -r Back-end/requirements.txt
COPY Back-end/app Back-end/app
COPY Admin/api Admin/api
WORKDIR /srv/Admin/api
EXPOSE 8001
CMD ["uvicorn", "admin_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
