"""Entry point: `python run.py` starts the dashboard on http://127.0.0.1:8000

Binds 0.0.0.0 and honors $PORT so the same entry point works unchanged when
deployed behind a host like Render, which assigns its own port at runtime.
"""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
