"""Simulator: two virtual PSU modules for UI testing without hardware."""
import struct
import threading
import time
import random

from .interface import CANInterface
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import protocol


class Simulator(CANInterface):

    def __init__(self):
        self._connected = False
        self._callback = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        # Simulated module state
        self._enabled = [False, False]
        self._set_v = [500.0, 500.0]   # V
        self._set_i = [18.5, 18.5]     # A per module

    # ── CANInterface ──────────────────────────────────────────────────────

    def connect(self) -> bool:
        self._connected = True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name='SimulatorRx')
        self._thread.start()
        return True

    def disconnect(self):
        self._running = False
        self._connected = False

    def send_frame(self, can_id: int, data: bytes) -> bool:
        """Handle commands sent by the PC (simulate board+PSU response)."""
        p = protocol.parse_can_id(can_id)
        dst = p['dst']
        cmd = p['cmd']
        if cmd == protocol.CMD_KEEPALIVE:
            # Плата отвечает на keep-alive: src=BOARD_ADDR → ПК видит «Online».
            reply_id = protocol.build_can_id(protocol.BOARD_ADDR, protocol.MONITOR_ADDR,
                                             protocol.CMD_KEEPALIVE)
            self._fire(reply_id, bytes(8))
            return True
        addrs = range(protocol.PSU_ACTIVE_COUNT) if dst == protocol.BROADCAST_ADDR else [dst]
        with self._lock:
            for addr in addrs:
                if addr >= protocol.PSU_ACTIVE_COUNT:
                    continue
                if cmd == protocol.CMD_SET_ENABLE:
                    # data[0]=0 → on, data[0]=1 → off  (inverted logic)
                    self._enabled[addr] = (data[0] == 0)
                    self._emit_0x1a(addr, data[0])
                elif cmd == protocol.CMD_SET_VC:
                    v_mv, i_ma = struct.unpack('>II', bytes(data[:8]))
                    self._set_v[addr] = v_mv / 1000.0
                    self._set_i[addr] = i_ma / 1000.0
        return True

    def set_rx_callback(self, callback):
        self._callback = callback

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Simulation loop ───────────────────────────────────────────────────

    def _loop(self):
        tick = 0
        while self._running:
            time.sleep(0.2)
            tick += 1
            for addr in range(protocol.PSU_ACTIVE_COUNT):
                self._emit_0x04(addr)
                self._emit_0x09(addr)
                if tick % 5 == 0:
                    self._emit_0x06(addr)

    def _emit_0x1a(self, addr, enable_byte: int):
        """Echo 0x1A back from PSU so psu_model._commanded_on stays in sync."""
        data = bytes([enable_byte]) + bytes(7)
        can_id = protocol.build_can_id(addr, protocol.MONITOR_ADDR, protocol.CMD_SET_ENABLE)
        self._fire(can_id, data)

    def _emit_0x04(self, addr):
        temp = 35 + random.randint(-2, 2)
        data = bytes([0, temp & 0xFF, 0, 0, 0, 0, 0, 0])
        can_id = protocol.build_can_id(addr, protocol.MONITOR_ADDR, protocol.CMD_READ_STATUS)
        self._fire(can_id, data)

    def _emit_0x09(self, addr):
        with self._lock:
            enabled = self._enabled[addr]
            sv = self._set_v[addr]
            si = self._set_i[addr]
        if enabled:
            v_mv = int(sv * 1000 + random.randint(-300, 300))
            i_ma = int(si * 1000 + random.randint(-50, 50))
        else:
            v_mv, i_ma = 0, 0
        data = struct.pack('>II', max(0, v_mv), max(0, i_ma))
        can_id = protocol.build_can_id(addr, protocol.MONITOR_ADDR, protocol.CMD_READ_OUTPUT)
        self._fire(can_id, data)

    def _emit_0x06(self, addr):
        vab = int(380.0 * 10 + random.randint(-5, 5))
        vbc = int(381.0 * 10 + random.randint(-5, 5))
        vca = int(379.0 * 10 + random.randint(-5, 5))
        data = struct.pack('>HHHxx', vab, vbc, vca)
        can_id = protocol.build_can_id(addr, protocol.MONITOR_ADDR, protocol.CMD_READ_PHASE_V)
        self._fire(can_id, data)

    def _fire(self, can_id, data):
        cb = self._callback
        if cb:
            cb(can_id, data)
