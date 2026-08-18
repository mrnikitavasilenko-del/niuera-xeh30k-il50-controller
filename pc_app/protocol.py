"""CAN protocol encoding/decoding for NIUERA charging modules."""
import struct

MONITOR_ADDR     = 0xF0
BROADCAST_ADDR   = 0x3F
DEVICE_INDIVIDUAL = 0x0A
DEVICE_GROUP      = 0x0B
PSU_ACTIVE_COUNT  = 2

# Command codes
CMD_READ_STATUS  = 0x04
CMD_READ_PHASE_V = 0x06
CMD_READ_OUTPUT  = 0x09
CMD_SET_ENABLE   = 0x1A
CMD_SET_VC       = 0x1C
CMD_SET_HVLV     = 0x1D
CMD_KEEPALIVE    = 0x2A    # ПК↔плата liveness; плата отвечает src=BOARD_ADDR

BOARD_ADDR       = 0xAA    # маркер платы в ответе на keep-alive

# 29-bit extended ID bit layout:
#   [7:0]   source address
#   [15:8]  destination address
#   [21:16] command (6 bits)
#   [25:22] device  (4 bits)
#   [28:26] error   (3 bits)

def build_can_id(src, dst, cmd, device=DEVICE_INDIVIDUAL, error=0):
    return (
        (src & 0xFF) |
        ((dst & 0xFF) << 8) |
        ((cmd & 0x3F) << 16) |
        ((device & 0x0F) << 22) |
        ((error & 0x07) << 26)
    )

def parse_can_id(can_id):
    return {
        'src':    can_id & 0xFF,
        'dst':    (can_id >> 8) & 0xFF,
        'cmd':    (can_id >> 16) & 0x3F,
        'device': (can_id >> 22) & 0x0F,
        'error':  (can_id >> 26) & 0x07,
    }


def decode_status_bits(s0, s1, s2):
    """Map raw status bytes to a code 5–21, or 0 if no fault active.
    Priority order follows the docx status code table."""
    if s2 & (1 << 7): return 9
    if s2 & (1 << 6): return 10
    if s2 & (1 << 5): return 11
    if s2 & (1 << 4): return 12
    if s2 & (1 << 3): return 13
    # s2.bit2 (severeUnevenFlowFault) — единственный передаваемый признак КЗ на выходе:
    # настоящий бит status0.bit0 не влезает в 8-байтный кадр 0x04. Маппим на код 05.
    if s2 & (1 << 2): return 5
    if s2 & (1 << 0): return 14
    if s1 & (1 << 7): return 8
    if s1 & (1 << 6): return 15
    if s1 & (1 << 5): return 16
    if s1 & (1 << 4): return 6
    if s1 & (1 << 3): return 7
    if s1 & (1 << 2): return 17
    if s1 & (1 << 1): return 18
    if s1 & (1 << 0): return 19
    if s0 & (1 << 5): return 20
    # s0 bit 2 (code 21) is permanently set on this hardware — not a real fault, skip
    if s0 & (1 << 0): return 5
    return 0

# All hardware fault codes (for display coloring)
FAULT_CODES = frozenset(range(5, 22))

# Codes that block UI controls and show "Авария".
# Excluded:
#   14 — Power limiting mode: module continues working at reduced power (spec §6.4).
BLOCKING_FAULT_CODES = frozenset({5}) | frozenset(range(6, 14)) | frozenset(range(15, 21))

# Warning codes shown in yellow, controls remain enabled.
WARNING_CODES = frozenset({14})


def parse_0x04(data):
    """0x04 response. Layout как в старом проекте PSU_Controller:
        bytes 0-1: rsvd
        bytes 2-3: group number (big-endian uint16)
        byte 4:    температура (signed int8)
        byte 5:    rsvd
        byte 6:    status2
        byte 7:    status1
        (status0 формально на byte 8 — вне 8-байтного фрейма, читать неоткуда)
    Текстовое описание протокола (data[1]=temp, data[2..4]=status) с реальным
    железом CS60 не совпадает — temp всегда читался как 0."""
    if len(data) < 8:
        return None
    raw = data[4]
    temp = raw if raw < 128 else raw - 256
    return {
        'group':    (data[2] << 8) | data[3],
        'temp':     temp,
        'status2':  data[6],
        'status1':  data[7],
        'status0':  0,
    }

def parse_0x06(data):
    """0x06 response: phase voltages A-B, B-C, C-A in units of 0.1 V."""
    if len(data) < 6:
        return None
    vab = struct.unpack('>H', bytes(data[0:2]))[0] / 10.0
    vbc = struct.unpack('>H', bytes(data[2:4]))[0] / 10.0
    vca = struct.unpack('>H', bytes(data[4:6]))[0] / 10.0
    return {'vab': vab, 'vbc': vbc, 'vca': vca}

def parse_0x09(data):
    """0x09 response: output voltage (mV, big-endian) and current (mA, big-endian)."""
    if len(data) < 8:
        return None
    v_mv = struct.unpack('>I', bytes(data[0:4]))[0]
    i_ma = struct.unpack('>I', bytes(data[4:8]))[0]
    return {'voltage_v': v_mv / 1000.0, 'current_a': i_ma / 1000.0}

def parse_0x1c(data):
    """0x1C response: PSU echoes back its current setpoints (voltage mV, per-module current mA)."""
    if len(data) < 8:
        return None
    v_mv = struct.unpack('>I', bytes(data[0:4]))[0]
    i_ma = struct.unpack('>I', bytes(data[4:8]))[0]
    return {'voltage_v': v_mv / 1000.0, 'current_per_module_a': i_ma / 1000.0}


def build_keepalive_frame():
    """Keep-alive ПК→плата. Плата отвечает кадром src=BOARD_ADDR, cmd=CMD_KEEPALIVE."""
    can_id = build_can_id(MONITOR_ADDR, BOARD_ADDR, CMD_KEEPALIVE)
    return can_id, bytes(8)

def build_enable_frame(addr, enable):
    """Build 0x1A frame.
    enable=True → ON.  PSU uses inverted logic (0=on, 1=off), same as firmware.
    """
    can_id = build_can_id(MONITOR_ADDR, addr, CMD_SET_ENABLE)
    data = bytes([0 if enable else 1]) + bytes(7)
    return can_id, data

def build_setpoint_frame(addr, voltage_v, current_per_module_a):
    """Build 0x1C frame with per-module voltage (mV) and current (mA).
    The board reads per-module current and multiplies by PSU_ACTIVE_COUNT to get total.
    """
    can_id = build_can_id(MONITOR_ADDR, addr, CMD_SET_VC)
    v_mv = int(voltage_v * 1000)
    i_ma = int(current_per_module_a * 1000)
    data = struct.pack('>II', v_mv, i_ma)
    return can_id, data


STATUS_DESCRIPTIONS = {
    0:  "Норма",
    1:  "Ограничение по напряжению",
    2:  "Ограничение по току",
    3:  "Ограничение мощности 50 кВт",
    4:  "Нет связи по CAN",
    5:  "КЗ на выходе",
    6:  "Перегрев",
    7:  "Отказ вентиляторов",
    8:  "Прерывание связи CAN",
    9:  "Модуль PFC выключен",
    10: "Перенапряжение на входе",
    11: "Низкое входное напряжение",
    12: "Дисбаланс трёхфазного входа",
    13: "Обрыв фазы",
    14: "Режим ограничения мощности",
    15: "Перегрузка по току на выходе",
    16: "Перенапряжение на выходе",
    17: "Сигнализация защиты модуля",
    18: "Сигнализация неисправности модуля",
    19: "Модуль DC стороны выключен",
    20: "Ошибка разряда",
    21: "Сбой внутренней связи",
}
