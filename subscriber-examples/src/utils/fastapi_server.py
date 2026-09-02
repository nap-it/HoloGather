# utils/fastapi_server.py
import uvicorn
from multiprocessing import Queue
import importlib

def run_fastapi_server(audio_queue: Queue, host: str = "127.0.0.1", port: int = 4000):
    app_mod = importlib.import_module("src.utils.fastapi_app")
    app_mod.audio_queue = audio_queue

    uvicorn.run(
        "src.utils.fastapi_app:app",
        host=host,
        port=port,
        log_level="info",
    )
