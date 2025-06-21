import logging
from contextlib import contextmanager
import time

logger = logging.getLogger("reactivos")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

@contextmanager
def log_time(task_name: str):
    start = time.time()
    logger.info(f"Iniciando: {task_name}")
    try:
        yield
    finally:
        elapsed = time.time() - start
        logger.info(f"Completado: {task_name} en {elapsed:.2f}s")
