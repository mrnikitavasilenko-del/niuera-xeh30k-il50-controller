"""SLCAN ASCII serial driver for USB-CAN adapter (125 kbaud, extended frames)."""
import threading
import time
import logging
from collections import deque
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial
import serial.tools.list_ports

from .interface import CANInterface
from applog import app_log

log = logging.getLogger(__name__)

def _fmt_rx(can_id: int, data: bytes) -> str:
    src = can_id & 0xFF
    dst = (can_id >> 8) & 0xFF
    cmd = (can_id >> 16) & 0x3F
    raw = data.hex().upper() if data else ''
    return f'ID={can_id:08X}  src={src:#04x} dst={dst:#04x} cmd={cmd:#04x}  [{raw}]'

_BAUD_CMD          = b'S4\r'   # 125 kbaud
_OPEN_CMD          = b'O\r'
_CLOSE_CMD         = b'C\r'
_SERIAL_BAUD       = 115200
_RECONNECT_INTERVAL = 2.0      # seconds between reconnect attempts
_ECHO_MAXLEN       = 16        # max number of echoed frames to remember


class SLCANInterface(CANInterface):
    """
    SLCAN-over-serial CAN interface.

    Pass the COM port name at construction or set .port before calling connect().
    Auto-reconnect: watchdog thread retries every 2 s after serial loss.
    """

    def __init__(self, port: str = ''):
        self._port = port
        self._serial: serial.Serial | None = None
        self._serial_lock = threading.Lock()

        self._callback = None
        self._running = False

        self._rx_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None

        # Echo suppression: bare frame strings of recently sent frames
        self._echo_deque: deque[str] = deque(maxlen=_ECHO_MAXLEN)
        self._echo_lock = threading.Lock()

    # ── CANInterface ──────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        with self._serial_lock:
            return self._serial is not None and self._serial.is_open

    def connect(self) -> bool:
        """Start driver threads. Opens serial immediately if port is set."""
        if self._running:
            return self.connected
        self._running = True

        self._rx_thread = threading.Thread(
            target=self._rx_loop, daemon=True, name='SLCAN-RX')
        self._rx_thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name='SLCAN-WD')
        self._watchdog_thread.start()

        if self._port:
            return self._try_open(self._port)
        return False

    def disconnect(self):
        """Stop driver and close serial port."""
        self._running = False
        self._close_port()

    def send_frame(self, can_id: int, data: bytes) -> bool:
        if not self.connected:
            return False
        frame_str = 'T{:08X}{:1X}{}'.format(
            can_id & 0x1FFFFFFF,
            len(data) & 0xF,
            data.hex().upper(),
        )
        raw = (frame_str + '\r').encode('ascii')
        with self._serial_lock:
            if self._serial is None:
                return False
            try:
                self._serial.write(raw)
                with self._echo_lock:
                    self._echo_deque.append(frame_str)
                app_log.log('TX', _fmt_rx(can_id, data))
                return True
            except serial.SerialException as exc:
                log.warning('SLCAN send error: %s', exc)
                app_log.log('WARN', f'Ошибка отправки: {exc}')
                self._close_port_locked()
                return False

    def set_rx_callback(self, callback):
        self._callback = callback

    # ── Port property ─────────────────────────────────────────────────────

    @property
    def port(self) -> str:
        return self._port

    @port.setter
    def port(self, value: str):
        if value == self._port:
            return
        self._port = value
        if self._running:
            self._close_port()   # watchdog will reopen on new port

    # ── Internal ──────────────────────────────────────────────────────────

    def _try_open(self, port: str) -> bool:
        try:
            ser = serial.Serial(
                port=port,
                baudrate=_SERIAL_BAUD,
                timeout=1.0,
                write_timeout=1.0,
            )
            # SLCAN init sequence
            ser.write(_CLOSE_CMD)
            time.sleep(0.05)
            ser.reset_input_buffer()
            ser.write(_BAUD_CMD)
            time.sleep(0.05)
            ser.write(_OPEN_CMD)
            time.sleep(0.05)
            ser.reset_input_buffer()
            with self._serial_lock:
                self._serial = ser
            log.info('SLCAN connected on %s', port)
            app_log.log('CONN', f'Подключено к {port} (125 kbaud SLCAN)')
            return True
        except (serial.SerialException, OSError) as exc:
            log.warning('SLCAN open failed on %s: %s', port, exc)
            app_log.log('WARN', f'Не удалось открыть {port}: {exc}')
            return False

    def _close_port(self):
        with self._serial_lock:
            self._close_port_locked()

    def _close_port_locked(self):
        """Must be called with _serial_lock already held."""
        ser = self._serial
        self._serial = None
        if ser is not None:
            try:
                ser.write(_CLOSE_CMD)
            except Exception:
                pass
            try:
                ser.close()
            except Exception:
                pass

    def _handle_disconnect(self):
        log.warning('SLCAN serial error — disconnected')
        app_log.log('CONN', 'Соединение потеряно (serial error)')
        with self._serial_lock:
            self._close_port_locked()

    # ── RX thread ─────────────────────────────────────────────────────────

    def _rx_loop(self):
        while self._running:
            with self._serial_lock:
                ser = self._serial
            if ser is None:
                time.sleep(0.05)
                continue
            try:
                # read_until returns bytes up to and including the terminator
                chunk = ser.read_until(b'\r')
                if chunk:
                    line = chunk.decode('ascii', errors='ignore').strip('\r\n ')
                    if line:
                        self._dispatch(line)
            except serial.SerialException as exc:
                log.debug('SLCAN RX error: %s', exc)
                self._handle_disconnect()
            except Exception as exc:
                log.debug('SLCAN RX unexpected: %s', exc)
                self._handle_disconnect()

    def _dispatch(self, line: str):
        """Parse one SLCAN line and invoke rx_callback."""
        if line[0] == 'T' and len(line) >= 10:
            # Echo suppression
            with self._echo_lock:
                if line in self._echo_deque:
                    self._echo_deque.remove(line)
                    return
            try:
                can_id = int(line[1:9], 16)
                dlc    = int(line[9], 16)
                hex_data = line[10:10 + dlc * 2]
                if len(hex_data) == dlc * 2:
                    data = bytes.fromhex(hex_data)
                    app_log.log('RX', _fmt_rx(can_id, data))
                    cb = self._callback
                    if cb:
                        cb(can_id, data)
            except (ValueError, IndexError) as exc:
                log.debug('SLCAN parse error "%s": %s', line, exc)
                app_log.log('WARN', f'Ошибка парсинга SLCAN: "{line}" — {exc}')
        elif line and line[0] not in ('t', 'z', 'Z', '\x07'):
            # Log unexpected non-frame lines (errors/status from adapter)
            app_log.log('WARN', f'SLCAN адаптер: "{line}"')

    # ── Watchdog thread ───────────────────────────────────────────────────

    def _watchdog_loop(self):
        while self._running:
            time.sleep(_RECONNECT_INTERVAL)
            if not self._running:
                break
            with self._serial_lock:
                already_open = self._serial is not None
            if not already_open and self._port:
                log.debug('SLCAN watchdog reconnecting on %s', self._port)
                self._try_open(self._port)
