FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces' Docker SDK expects the app on port 7860 by default;
# run.py already honors $PORT (added for Render/Vercel), so this is the only
# host-specific bit needed.
ENV PORT=7860
EXPOSE 7860

CMD ["python", "run.py"]
