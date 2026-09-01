"""
`BaseQueue.py` file contains the abstract base class for queues with generic item types.
"""
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional

T = TypeVar('T')

class BaseQueue(ABC, Generic[T]):
    """
    Abstract base class for queues with generic item types.
    Defines the interface for different queue implementations.
    """

    @abstractmethod
    def __len__(self) -> int:
        """
        Return the number of items in the queue.
        """
        pass

    @abstractmethod
    def put(self, item: T) -> None:
        """
        Add an item to the queue.
        """
        pass

    @abstractmethod
    def get(self) -> Optional[T]:
        """
        Remove and return an item from the queue.
        """
        pass

    @abstractmethod
    def is_empty(self) -> bool:
        """
        Check if the queue is empty.
        """
        pass
