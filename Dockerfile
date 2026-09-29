FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.lock.txt .
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock.txt \
    && python -m pip check

COPY . .

EXPOSE 8000

CMD ["python", "run.py"]
