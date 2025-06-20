# app/llm/utils.py

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Tuple, Type

def make_retry(
    exc_types: Tuple[Type[Exception], ...],
    max_retries: int = 3
):
    """
    Construye un decorador de retry para Tenacity, parametrizado
    por tipos de excepción y número de reintentos.
    """
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(exc_types),
    )
