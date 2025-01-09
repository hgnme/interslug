import asyncio
import threading
from logging_config import get_logger


def run_async_as_sync(coro):
    try:
        # Try to get the current running event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop in this thread, create a new one
        loop = None

    if loop and loop.is_running():
        # If a loop is running, use `create_task` to schedule the coroutine
        return asyncio.create_task(coro)
    else:
        # Otherwise, start a new event loop to run the coroutine
        return asyncio.run(coro)