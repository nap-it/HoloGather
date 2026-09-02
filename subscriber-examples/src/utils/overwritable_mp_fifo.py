"""
OverWritableMPFIFO.py

Process-safe FIFO queue with fixed capacity and overwrite-on-full semantics,
implemented on top of multiprocessing.Queue.

Behavior:
- FIFO order on get()
- When full, put() automatically drops the oldest item to make space
- Non-blocking get(): returns None if empty
"""

from multiprocessing import Queue
from queue import Full, Empty
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class OverWritableMPFIFO(Generic[T]):
    """
    OverWritableMPFIFO is a generic class that wraps multiprocessing.Queue to provide:
      - FIFO semantics on retrieval
      - Fixed maximum size
      - Overwrite-on-full behavior: when full, inserting a new item discards the oldest one.

    This is useful for cases like sensor readings, frames, or metrics where
    the newest data matters more than the oldest, and blocking producers is undesirable.
    """

    def __init__(self, max_size: int):
        """
        Initialize the OverWritableMPFIFO.

        :param max_size: The maximum number of items in the queue (must be > 0).
        """
        if max_size <= 0:
            raise ValueError("max_size must be a positive integer")

        # multiprocessing.Queue is already process-safe.
        self._queue: Queue = Queue(maxsize=max_size)

    def __len__(self) -> int:
        """
        Return an *approximate* number of items in the queue.

        Note: qsize() may not be exact on all platforms, but is usually good enough
        for monitoring / debugging.
        """
        try:
            return self._queue.qsize()
        except NotImplementedError:
            # On some platforms qsize is not implemented; fall back to 0.
            return 0

    def put(self, item: T, block: bool = False) -> None:
        """
        Put an item into the FIFO queue.

        If the queue is full, the oldest item is removed and then the new item is inserted.
        
        :param block: If True, block until space is available. If False, drop oldest item if full.
        :param item: The item to be added.
        """
        while True:
            try:
                # Try immediate put; if there is space, we're done.
                self._queue.put(item, block=block)
                return
            except Full:
                # Queue is full → drop one oldest item and retry.
                try:
                    self._queue.get(block=False)
                except Empty:
                    # Race condition: another consumer drained it.
                    # Just loop and retry put().
                    pass

    def get(self, block: bool = False) -> Optional[T]:
        """
        Get the oldest item from the FIFO queue.

        :param block: If True, block until an item is available. If False, return None if empty.
        :return: The oldest item, or None if the queue is empty.
        """
        timeout: float = 1.0 if block else 0.0
        try:
            return self._queue.get(block=block, timeout=timeout)
        except Empty:
            return None

    def is_empty(self) -> bool:
        """
        Check if the queue is (likely) empty.

        :return: True if empty, False otherwise.
        """
        return self._queue.empty()
