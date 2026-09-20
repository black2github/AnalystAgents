FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app.py /app/app.py
# engine/ монтируется из хоста (./calc/engine) — правки видны без пересборки образа
ENV PYTHONUNBUFFERED=1 CALC_DATA=/data/workspace-invest
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
