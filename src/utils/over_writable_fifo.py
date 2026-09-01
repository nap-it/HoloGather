"""
`OverWritableFIFO.py` file contains a generic class that implements a Thread-safe FIFO queue with a 
maximum size and overridable values.
"""
from collections import deque
from threading import Lock
from typing import Deque, Generic, Optional, TypeVar
try:
    # Attempt to import from the `utils` package
    from src.utils.base_queue import BaseQueue
except ImportError:
    try:
        # Fall back to importing without `utils`
        from .base_queue import BaseQueue
    except ImportError:
        # Raise an error if neither import works
        raise ImportError("BaseQueue could not be imported from either 'utils' or the current directory")

 # Define a generic type variable
T = TypeVar('T') 

class OverWritableFIFO(BaseQueue[T], Generic[T]):
    """
    `OverWritableFIFO` is a generic class that implements a FIFO queue with a maximum size. 
    When the queue is full, adding a new item will automatically remove the oldest item. 
    This is useful for storing the most recent items in a fixed-size buffer.
    Attributes:
        queue: The deque object that stores the items.
        lock: The threading lock object to ensure thread safety.
    """
    def __init__(self, max_size: int):
        """
        Initialize the OverWritableFIFO class.
        :param max_size: The maximum size of the FIFO queue.
        """
        self.queue: Deque[T] = deque(maxlen=max_size)
        self.lock = Lock()

    def __len__(self) -> int:
        """
        Get the current number of items in the FIFO queue.
        :return: The number of items in the queue.
        """
        with self.lock:
            return len(self.queue)

    def put(self, item: T) -> None:
        """
        Put an item into the FIFO queue. If the queue is full, the oldest item will be removed.
        :param item: The item to be added to the queue.
        """
        with self.lock:
            self.queue.append(item)  # Automatically removes oldest if full

    def get(self) -> Optional[T]:
        """
        Get the most recent item from the FIFO queue.
        :return: The most recent item from the queue, or None if the queue is empty.
        """
        with self.lock:
            if len(self.queue) > 0:
                return self.queue.popleft()  # Get the most recent item
            return None  # Queue is empty

    def is_empty(self) -> bool:
        """
        Check if the FIFO queue is empty.
        :return: True if the queue is empty, False otherwise.
        """
        with self.lock:
            return len(self.queue) == 0
