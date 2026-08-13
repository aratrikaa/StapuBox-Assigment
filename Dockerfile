FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# run.py already honors $PORT (added for Render/Vercel). Cloud Run injects
# its own PORT=8080 into the running container regardless of this default —
# it's just a sane fallback for running the image anywhere else.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "run.py"]
