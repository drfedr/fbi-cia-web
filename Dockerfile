FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates
COPY static ./static

ENV CIA_DIR=/cia
ENV PORT=8000

EXPOSE 8000
VOLUME ["/cia"]

CMD ["python", "app.py"]
