"""Abstract CAN communication interface."""
from abc import ABC, abstractmethod
from typing import Callable


class CANInterface(ABC):

    @abstractmethod
    def connect(self) -> bool:
        """Open connection. Returns True on success."""

    @abstractmethod
    def disconnect(self):
        """Close connection."""

    @abstractmethod
    def send_frame(self, can_id: int, data: bytes) -> bool:
        """Transmit one CAN frame. Returns True if queued/sent."""

    @abstractmethod
    def set_rx_callback(self, callback: Callable[[int, bytes], None]):
        """Register callback invoked for every received frame: callback(can_id, data)."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """True while the connection is open."""
