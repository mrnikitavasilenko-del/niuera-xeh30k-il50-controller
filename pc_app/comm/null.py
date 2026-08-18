"""NullInterface: always disconnected, used when no CAN adapter is configured."""
from .interface import CANInterface


class NullInterface(CANInterface):
    @property
    def connected(self) -> bool:
        return False

    def connect(self) -> bool:
        return False

    def disconnect(self):
        pass

    def send_frame(self, can_id: int, data: bytes) -> bool:
        return False

    def set_rx_callback(self, callback):
        pass
