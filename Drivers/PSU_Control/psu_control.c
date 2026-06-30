#include "psu_control.h"
#include "can.h"
#include <string.h>

/* Переменные главного цикла из main.c — обновляются при внешнем управлении с CAN-2 */
extern uint16_t Set_Voltage;
extern uint16_t Set_Current;
extern uint8_t  ON_OFF;

/* Keep-alive ПК↔плата (CAN-2). ПК шлёт cmd 0x2A (src=0xF0→dst=0xAA), плата отвечает
   тем же cmd (src=0xAA→dst=0xF0) прямо на CAN-2. Позволяет ПК показывать «Online»,
   когда плата и ПК на связи, даже если модулей на CAN-1 нет. */
#define PSU_KEEPALIVE_CMD   0x2Au
#define PSU_BOARD_ADDR      0xAAu

/* Внутренние структуры */
#pragma pack(push, 1)
typedef struct {
    uint8_t source;
    uint8_t destination;
    uint8_t command : 6;
    uint8_t device   : 4;
    uint8_t error    : 3;
} CanId_t;

typedef struct { uint8_t rsvd0[2]; uint16_t moduleNumber; uint8_t rsvd1[5]; } PSU_02_t;
/* Layout как в старом проекте PSU_Controller: temp на байте 4, статусы 2/1 на 6/7.
   status0 формально на байте 8 — за пределами 8-байтного CAN-фрейма, читать неоткуда. */
typedef struct { uint8_t rsvd0[2]; uint8_t group[2]; int8_t temperature; uint8_t rsvd1; uint8_t status2; uint8_t status1; } PSU_04_t;
typedef struct { uint8_t VABHi, VABLo, VBCHi, VBCLo, VCAHi, VCALo; uint8_t rsvd1[2]; uint32_t VAB, VBC, VCA; } PSU_06_t;
typedef struct { uint8_t moduleNVoltage_[4]; uint8_t moduleNCurrent_[4]; uint32_t moduleNVoltage; uint32_t moduleNCurrent; } PSU_09_t;
typedef struct { uint8_t enable; uint8_t rsvd1[7]; } PSU_1A_t;
typedef struct { uint8_t moduleVoltage[4]; uint8_t moduleCurrentTotal[4]; } PSU_1C_t;
typedef struct { uint8_t enable; uint8_t rsvd1[7]; } PSU_1D_t;
#pragma pack(pop)

/* Константы */
#define CAN_DELAY                10    // мс
#define CAN_TIMEOUT             1000   // мс
#define PSU_ENABLE_RETRY_DELAY  200    // минимальный интервал между повторными Enable
#define PSU_VOLTAGE_THRESHOLD    20
#define PSU_SYNC_TIMEOUT        3000   // мс: если фактический режим не совпадает с командой — пересылаем

PSU_State_t PSU_State[PSU_MAX_ADDR];
uint8_t     PSU_ActiveAddrs[PSU_MAX_MODULES] = {0, 1};
uint8_t     PSU_ActiveCount = 2;

int32_t  PSU_TotalCurrent = 0;
uint16_t PSU_TotalVoltage = 0;

static uint32_t can_lastpacket[PSU_MAX_ADDR];
static uint32_t psu_enable_last_sent[PSU_MAX_ADDR];
static uint8_t  psu_enable_last[PSU_MAX_ADDR];
static uint8_t  psu_hv_mode[PSU_MAX_ADDR];
static uint8_t  psu_hv_last[PSU_MAX_ADDR];   // последнее успешно отправленное HV-состояние
static uint8_t  psu_faulted[PSU_MAX_ADDR];   // 1 = модуль отключился под нагрузкой, ждёт ручного сброса
static uint8_t  psu_kz_faulted[PSU_MAX_ADDR]; // 1 = КЗ зафиксировано; снимается только при перезапуске платы

/* Добавляет декодированный код в историю модуля.
 * Пропускает код, если он уже присутствует в любом из 3 слотов (дедупликация).
 * Принимает только коды 04–20: 04=офлайн, 05–20=ошибки.
 * Коды 01–03 (CV/CC/мощность) и 21 (всегда взведён) не сохраняются. */
/* Добавляет декодированный код в историю модуля.
 * Пропускает код только если он совпадает с текущим топом (codes[0]) —
 * повторное вхождение не имеет смысла подряд.
 * Комбинация [X][Y][X] допустима: после [Y] приходит новый [X] → пушим. */
void PSU_PushStatusCode(uint8_t addr, uint8_t code) {
    if (addr >= PSU_MAX_ADDR) return;
    PSU_StatusHistory_t *h = &PSU_State[addr].history;
    if (h->codes[0] == code) return;
    h->codes[2] = h->codes[1];
    h->codes[1] = h->codes[0];
    h->codes[0] = code;
}

static void set_updated_flag(uint8_t addr) {
    if (!PSU_State[addr].updated) PSU_State[addr].updated = true;
}

/* Декодирование байтов статуса в код 0–21 по таблице из спецификации.
   Возвращает 0 если ни один бит не активен. */
uint8_t PSU_DecodeStatusBits(uint8_t s0, uint8_t s1, uint8_t s2) {
    if (s2 & (1u<<7)) return  9;  // PFC module off
    if (s2 & (1u<<6)) return 10;  // Input overvoltage
    if (s2 & (1u<<5)) return 11;  // Low input voltage
    if (s2 & (1u<<4)) return 12;  // Phase imbalance
    if (s2 & (1u<<3)) return 13;  // Phase loss
    if (s2 & (1u<<2)) return  5;  // severeUnevenFlowFault — единственный передаваемый признак КЗ на выходе
                                  // (настоящий бит status0.bit0 не влезает в 8-байтный фрейм 0x04).
    if (s2 & (1u<<0)) return 14;  // Power limiting mode
    if (s1 & (1u<<7)) return  8;  // CAN link interrupted
    if (s1 & (1u<<6)) return 15;  // Output overcurrent
    if (s1 & (1u<<5)) return 16;  // Output overvoltage
    if (s1 & (1u<<4)) return  6;  // Overheating
    if (s1 & (1u<<3)) return  7;  // Fan failure
    if (s1 & (1u<<2)) return 17;  // Module protection alarm
    if (s1 & (1u<<1)) return 18;  // Module fault alarm
    if (s1 & (1u<<0)) return 19;  // DC-side module off
    if (s0 & (1u<<5)) return 20;  // Discharge error
    if (s0 & (1u<<2)) return 21;  // Internal communication fault
    if (s0 & (1u<<0)) return  5;  // Output short circuit
    return 0;
}

/* Надёжная отправка с повторными попытками */
static HAL_StatusTypeDef PSU_SendCmd(uint8_t src, uint8_t dst, uint8_t cmd, void *data)
{
    CanId_t CanId;
    CanId.source = src;
    CanId.destination = dst;
    CanId.command = cmd;
    CanId.device = 0x0A;
    CanId.error = 0;

    CAN_TxHeaderTypeDef tx_header;
    memcpy(&tx_header.ExtId, &CanId, sizeof(CanId_t));
    tx_header.RTR = CAN_RTR_DATA;
    tx_header.IDE = CAN_ID_EXT;
    tx_header.DLC = 8;

    for (int retry = 10; retry > 0; retry--) {
        if (HAL_CAN_GetTxMailboxesFreeLevel(&hcan1) > 0) {
            uint32_t tx_mailbox;
            if (HAL_CAN_AddTxMessage(&hcan1, &tx_header, (uint8_t*)data, &tx_mailbox) == HAL_OK) {
                // Зеркалируем управляющие фреймы на CAN-2 — PC видит уставки и команды платы
                if (cmd == 0x1A || cmd == 0x1C || cmd == 0x1D) {
                    CAN_TxHeaderTypeDef fwd = {
                        .ExtId              = tx_header.ExtId,
                        .IDE                = tx_header.IDE,
                        .RTR                = tx_header.RTR,
                        .DLC                = tx_header.DLC,
                        .TransmitGlobalTime = DISABLE,
                    };
                    uint32_t mb;
                    if (HAL_CAN_GetTxMailboxesFreeLevel(&hcan2) > 0)
                        HAL_CAN_AddTxMessage(&hcan2, &fwd, (uint8_t*)data, &mb);
                }
                return HAL_OK;
            }
        }
        HAL_Delay(1);   // ждём 1 мс перед следующей попыткой
    }
    return HAL_ERROR;
}

void PSU_Init(void) {
    memset(PSU_State, 0, sizeof(PSU_State));
    for (int i = 0; i < PSU_MAX_ADDR; i++) {
        PSU_State[i].online = false;
        PSU_State[i].temperature = 20;
        /* 0xFF = пустой слот (не было событий); 0x00 = событие «норма» */
        memset(PSU_State[i].history.codes, 0xFF, sizeof(PSU_State[i].history.codes));
        psu_enable_last[i] = 0xFF;
        psu_hv_mode[i] = 0;
        psu_hv_last[i] = 0xFF;          // неопределённое, при первом poll уйдёт disable
        can_lastpacket[i] = 0;
        psu_enable_last_sent[i] = 0;
        psu_faulted[i] = 0;
        psu_kz_faulted[i] = 0;
    }

    CAN_FilterTypeDef sFilterConfig = {0};
    sFilterConfig.FilterBank = 0;
    sFilterConfig.FilterMode = CAN_FILTERMODE_IDMASK;
    sFilterConfig.FilterScale = CAN_FILTERSCALE_32BIT;
    sFilterConfig.FilterFIFOAssignment = CAN_RX_FIFO0;
    sFilterConfig.FilterActivation = ENABLE;
    sFilterConfig.SlaveStartFilterBank = 14;  // банки 0–13 для CAN1, 14–27 для CAN2
    HAL_CAN_ConfigFilter(&hcan1, &sFilterConfig);
    HAL_CAN_Start(&hcan1);
    HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING);

    // При старте выключаем оба модуля
    for (int i = 0; i < PSU_MAX_ADDR; i++) {
        PSU_Enable(i, 0);
    }
}

void PSU_CAN2_BridgeInit(void) {
    CAN_FilterTypeDef f = {0};
    f.FilterBank           = 14;                     // банки 14–27 принадлежат CAN2 на STM32F107
    f.FilterMode           = CAN_FILTERMODE_IDMASK;
    f.FilterScale          = CAN_FILTERSCALE_32BIT;
    f.FilterFIFOAssignment = CAN_RX_FIFO1;
    f.FilterActivation     = ENABLE;
    f.SlaveStartFilterBank = 14;                     // CAN2SB=14: иначе все банки достаются CAN1 и CAN2 не принимает
    // FilterIdHigh/Low и FilterMaskIdHigh/Low = 0 → пропускать все фреймы
    HAL_CAN_ConfigFilter(&hcan2, &f);
    HAL_CAN_Start(&hcan2);
    HAL_CAN_ActivateNotification(&hcan2, CAN_IT_RX_FIFO1_MSG_PENDING);
}

void PSU_Loop(void) {
    PSU_TotalCurrent = 0;
    PSU_TotalVoltage = 0;

    for (uint8_t i = 0; i < PSU_ActiveCount; i++) {
        uint8_t addr = PSU_ActiveAddrs[i];
        bool was_online = PSU_State[addr].online;

        if ((HAL_GetTick() - can_lastpacket[addr]) > CAN_TIMEOUT) {
            if (was_online) {
                // Если модуль отключился пока был активирован — запрещаем авторестарт.
                if (psu_enable_last[addr] == 1) {
                    psu_faulted[addr] = 1;
                }
                PSU_PushStatusCode(addr, 4);  /* офлайн-событие в историю */
                PSU_State[addr].online = false;
                PSU_State[addr].mode = 0;
                PSU_State[addr].outputVoltage = 0;
                PSU_State[addr].outputCurrent = 0;
                PSU_State[addr].outputPower = 0;
                psu_hv_mode[addr] = 0;
                psu_hv_last[addr] = 0xFF;   // заставит переслать HV-команду при возврате
                psu_enable_last[addr] = 0xFF; // сбросить: при сбросе fault потребует новой команды
                set_updated_flag(addr);
            }
            // не добавляем в сумму, модуль офлайн
        } else {
            if (!was_online) {
                PSU_State[addr].online = true;
                set_updated_flag(addr);
            }
            // суммируем только то, что реально пришло
            PSU_TotalCurrent += (int32_t)PSU_State[addr].outputCurrent * 1000;
            if (PSU_State[addr].outputVoltage > PSU_TotalVoltage) {
                PSU_TotalVoltage = PSU_State[addr].outputVoltage;
            }

            // Синхронизация: если фактический режим выхода не совпадает с отправленной командой
            // дольше PSU_SYNC_TIMEOUT — сбрасываем флаг, чтобы следующий PSU_Enable переслал команду.
            if (!psu_faulted[addr] && psu_enable_last[addr] != 0xFF) {
                if (psu_enable_last[addr] != PSU_State[addr].mode) {
                    if ((HAL_GetTick() - psu_enable_last_sent[addr]) >= PSU_SYNC_TIMEOUT) {
                        psu_enable_last[addr] = 0xFF;
                    }
                }
            }
        }
    }
}

void PSU_UpdateAll(uint16_t voltage, uint16_t current, uint8_t enable)
{
    uint8_t zero[8] = {0};
    uint32_t total_current_ma = (uint32_t)current * 1000;
    uint32_t current_per_module = (PSU_ActiveCount > 0) ? (total_current_ma / PSU_ActiveCount) : 0;

    // 1. Запрос статуса с небольшими паузами
    for (uint8_t i = 0; i < PSU_ActiveCount; i++) {
        uint8_t addr = PSU_ActiveAddrs[i];
        PSU_SendCmd(0xF0, addr, 0x04, zero);
        HAL_Delay(2);
        PSU_SendCmd(0xF0, addr, 0x06, zero);
        HAL_Delay(2);
        PSU_SendCmd(0xF0, addr, 0x09, zero);
        HAL_Delay(2);
    }

    // 2. Отправка уставок и enable
    for (uint8_t i = 0; i < PSU_ActiveCount; i++) {
        uint8_t addr = PSU_ActiveAddrs[i];

        // Режим HV/LV определяется уставкой напряжения, а не измеренным выходом.
        psu_hv_mode[addr] = (voltage > 500) ? 1 : 0;

        uint8_t hv_before = psu_hv_last[addr];
        PSU_SetHVMode(addr, psu_hv_mode[addr]);
        // Если только что сменили режим — даём модулю время перестроиться перед уставкой.
        if (psu_hv_last[addr] != hv_before) HAL_Delay(100);
        HAL_Delay(2);

        PSU_SetVoltageCurrent(addr, voltage, current_per_module);
        HAL_Delay(2);
        /* При fault-latch шлём явный OFF — иначе модуль продолжает аппаратные
           авторестарты (у него внутри «командован ВКЛ»). OFF сбрасывает это
           состояние и останавливает попытки. Идемпотентность PSU_Enable
           гарантирует, что повторные вызовы не спамят CAN. */
        PSU_Enable(addr, psu_faulted[addr] ? 0u : enable);
        PSU_State[addr].forceApply = false;
    }
}

void PSU_ClearFault(uint8_t addr) {
    if (addr >= PSU_MAX_ADDR) return;
    psu_faulted[addr] = 0;
    psu_enable_last[addr] = 0xFF;  // следующий PSU_Enable принудительно пошлёт команду
}

void PSU_Enable(uint8_t addr, uint8_t enable) {
    if (addr >= PSU_MAX_ADDR) return;

    // КЗ: жёсткий latch — включение заблокировано до пересброса питания платы.
    if (psu_kz_faulted[addr] && enable) return;

    // Не перезапускаем модуль если он отключился под нагрузкой.
    // Ждём явного сброса оператором через PSU_ClearFault().
    if (psu_faulted[addr] && enable) return;

    // Если желаемое состояние не изменилось с последней успешной отправки – не шлём
    if (enable == psu_enable_last[addr]) return;

    // Проверяем минимальный интервал между попытками (чтобы не спамить)
    if ((HAL_GetTick() - psu_enable_last_sent[addr]) < PSU_ENABLE_RETRY_DELAY) return;

    PSU_1A_t data;
    memset(&data, 0, sizeof(data));
    data.enable = !enable;    // инвертированная логика модуля

    if (PSU_SendCmd(0xF0, addr, 0x1A, &data) == HAL_OK) {
        psu_enable_last[addr] = enable;
        psu_enable_last_sent[addr] = HAL_GetTick();
    }
    // Если отправка не удалась – попробуем снова при следующем вызове (через 200 мс)
}

void PSU_SetHVMode(uint8_t addr, uint8_t enable) {
    if (addr >= PSU_MAX_ADDR) return;
    if (enable == psu_hv_last[addr]) return;

    PSU_1D_t data;
    memset(&data, 0, sizeof(data));
    data.enable = !enable;   // инвертированная логика, как у 0x1A

    if (PSU_SendCmd(0xF0, addr, 0x1D, &data) == HAL_OK) {
        psu_hv_last[addr] = enable;
    }
}

void PSU_SetVoltageCurrent(uint8_t addr, uint16_t voltage, uint32_t current_ma) {
    if (addr >= PSU_MAX_ADDR) return;
    if (voltage < MIN_VOLTAGE) voltage = MIN_VOLTAGE;
    if (psu_hv_mode[addr] == 0 && voltage > 499) voltage = 499;

    uint32_t voltage_mv = voltage * 1000UL;

    PSU_1C_t data;
    memset(&data, 0, sizeof(data));
    data.moduleCurrentTotal[0] = (current_ma >> 24) & 0xFF;
    data.moduleCurrentTotal[1] = (current_ma >> 16) & 0xFF;
    data.moduleCurrentTotal[2] = (current_ma >>  8) & 0xFF;
    data.moduleCurrentTotal[3] = (current_ma >>  0) & 0xFF;
    data.moduleVoltage[0] = (voltage_mv >> 24) & 0xFF;
    data.moduleVoltage[1] = (voltage_mv >> 16) & 0xFF;
    data.moduleVoltage[2] = (voltage_mv >>  8) & 0xFF;
    data.moduleVoltage[3] = (voltage_mv >>  0) & 0xFF;

    PSU_SendCmd(0xF0, addr, 0x1C, &data);
    // Небольшая пауза после отправки
    HAL_Delay(2);
}

/* Обработчик входящих CAN-сообщений */
void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan) {
    static CAN_RxHeaderTypeDef RxHeader;
    static uint8_t RxData[8];
    CanId_t CanId;

    if (HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO0, &RxHeader, RxData) != HAL_OK) return;

    // Пробрасываем все фреймы CAN-1 → CAN-2 прозрачно (PC видит ответы PSU)
    {
        CAN_TxHeaderTypeDef fwd = {
            .ExtId              = RxHeader.ExtId,
            .IDE                = RxHeader.IDE,
            .RTR                = RxHeader.RTR,
            .DLC                = RxHeader.DLC,
            .TransmitGlobalTime = DISABLE,
        };
        uint32_t mb;
        if (HAL_CAN_GetTxMailboxesFreeLevel(&hcan2) > 0)
            HAL_CAN_AddTxMessage(&hcan2, &fwd, RxData, &mb);
        // Если mailbox занят — фрейм теряется; NART на CAN-2 гарантирует разморозку
    }

    memcpy(&CanId, &RxHeader.ExtId, sizeof(CanId_t));
    uint8_t addr = CanId.source;
    if (addr >= PSU_MAX_ADDR) return;

    can_lastpacket[addr] = HAL_GetTick();
    PSU_State_t *s = &PSU_State[addr];

    switch (CanId.command) {
        case 0x04: {
            PSU_04_t *p = (PSU_04_t*)RxData;
            if (s->temperature != (uint8_t)p->temperature) {
                s->temperature = (uint8_t)p->temperature;
                set_updated_flag(addr);
            }
            uint8_t s0 = 0;  // status0 формально вне 8-байтного фрейма
            uint8_t s1 = p->status1, s2 = p->status2;
            if (s->status0 != s0 || s->status1 != s1 || s->status2 != s2) {
                s->status0 = s0; s->status1 = s1; s->status2 = s2;
                uint8_t fault = PSU_DecodeStatusBits(s0, s1, s2);
                /* Код 14 (ограничение мощности, s2[0]) также взводится при рампах
                   старт/стоп на любой нагрузке. Пишем его в историю только если уставка
                   реально превышает физический предел 50 кВт. */
                if (fault >= 5 && fault <= 20) {
                    if (fault != 14 || (uint32_t)Set_Voltage * Set_Current > 50000u)
                        PSU_PushStatusCode(addr, fault);
                }
                /* Код 14 имеет больший приоритет в PSU_DecodeStatusBits, чем блокирующие
                   коды из s1 (6–8, 15–19). Если s1 что-то говорит — извлекаем вторично.
                   Подавляем при psu_enable_last==0: s1-биты (например s1[3]=вентилятор)
                   также транзиентно взводятся во время рампы выключения. */
                uint8_t secondary = 0;
                if (fault == 14) {
                    secondary = PSU_DecodeStatusBits(s0, s1, s2 & ~0x01u);
                    if (secondary >= 5 && secondary <= 20 && secondary != 14) {
                        /* 0xFF = начальное/неизвестное состояние (PSU_Enable ещё не отправился):
                           не пушим вторичный код — s1-биты (вентилятор и др.) это шум инициализации.
                           Пушим только если явно скомандовано ВКЛ (== 1). */
                        if (psu_enable_last[addr] == 1)
                            PSU_PushStatusCode(addr, secondary);
                    }
                }
                /* КЗ или блокирующая неисправность при включённом модуле —
                   запрещаем авторестарт до явного сброса оператором.
                   psu_faulted обычно взводится при потере CAN, но модуль может
                   оставаться на шине при КЗ и других неисправностях.
                   Если fault==14, проверяем secondary (14 может маскировать s1).
                   Код 14 сам по себе не является основанием для fault-latch. */
                if (psu_enable_last[addr] == 1) {
                    uint8_t fc = (fault == 14 && secondary >= 5 && secondary <= 20) ? secondary : fault;
                    if (fc == 5 || (fc >= 6 && fc <= 13) || (fc >= 15 && fc <= 20)) {
                        psu_faulted[addr] = 1;
                    }
                    /* КЗ: сильный лatch — не сбрасывается PSU_ClearFault,
                       только при перезапуске платы (сброс питания модуля). */
                    if (fc == 5) {
                        psu_kz_faulted[addr] = 1;
                    }
                }
                set_updated_flag(addr);
            }
            break;
        }
        case 0x06: {
            /* Фазные напряжения AB/BC/CA, big-endian uint16, единицы 0.1 В.
               PSU аппаратно не всегда выставляет s2[3]/s2[4] (коды 13/12) при обрыве фазы —
               диагностируем сами по соотношению min/max линейных напряжений. */
            uint16_t vab = ((uint16_t)RxData[0] << 8) | RxData[1];
            uint16_t vbc = ((uint16_t)RxData[2] << 8) | RxData[3];
            uint16_t vca = ((uint16_t)RxData[4] << 8) | RxData[5];
            uint16_t vmax = (vab > vbc) ? (vab > vca ? vab : vca) : (vbc > vca ? vbc : vca);
            uint16_t vmin = (vab < vbc) ? (vab < vca ? vab : vca) : (vbc < vca ? vbc : vca);
            if (vmax >= 1000u) {  /* ≥ 100.0 В — фильтр нулей и шума */
                uint32_t ratio_pct = ((uint32_t)vmin * 100u) / vmax;
                uint8_t phase_fault = (ratio_pct < 70u) ? 13u :
                                      (ratio_pct < 85u) ? 12u : 0u;
                /* Дисбаланс фаз также возникает при рампе выключения: PSU
                   поочерёдно снимает фазы. Пушим код, если модуль скомандован ВКЛ.
                   НЕ требуем s->mode==1: при обрыве фазы выход проседает (V<20В → mode=0),
                   и с гейтом по mode код 13 терялся (на e-ink не появлялся, хотя ПК его видел).
                   Гейт psu_enable_last==1 сам подавляет ложные 12/13 при штатном выключении. */
                if (phase_fault > 0u && psu_enable_last[addr] == 1)
                    PSU_PushStatusCode(addr, phase_fault);
            }
            break;
        }
        case 0x09: {
            PSU_09_t *p = (PSU_09_t*)RxData;
            uint32_t volt_mv = ((uint32_t)p->moduleNVoltage_[0]<<24) |
                               (p->moduleNVoltage_[1]<<16) |
                               (p->moduleNVoltage_[2]<<8)  |
                               p->moduleNVoltage_[3];
            uint32_t curr_ma = ((uint32_t)p->moduleNCurrent_[0]<<24) |
                               (p->moduleNCurrent_[1]<<16) |
                               (p->moduleNCurrent_[2]<<8)  |
                               p->moduleNCurrent_[3];
            uint16_t new_v = volt_mv / 1000;
            int16_t  new_i = curr_ma / 1000;
            uint32_t new_p = (uint32_t)new_v * new_i;

            if (s->outputVoltage != new_v) { s->outputVoltage = new_v; set_updated_flag(addr); }
            if (s->outputCurrent != new_i) { s->outputCurrent = new_i; set_updated_flag(addr); }
            if (s->outputPower != new_p)   { s->outputPower = new_p;   set_updated_flag(addr); }

            // Обновляем mode по фактическому напряжению (только для отображения)
            uint8_t new_mode = (new_v >= PSU_VOLTAGE_THRESHOLD) ? 1 : 0;
            if (s->mode != new_mode) {
                s->mode = new_mode;
                set_updated_flag(addr);
            }
            // psu_hv_mode управляется уставкой в PSU_UpdateAll, а не измеренным выходом.
            break;
        }
    }
}

/* Приём команд от PC (CAN-2, FIFO1) — пробрас на CAN-1 + синхронизация состояния */
void HAL_CAN_RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan) {
    static CAN_RxHeaderTypeDef RxHeader;
    static uint8_t RxData[8];
    CanId_t CanId;

    if (HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO1, &RxHeader, RxData) != HAL_OK) return;
    memcpy(&CanId, &RxHeader.ExtId, sizeof(CanId_t));

    /* Keep-alive от ПК: отвечаем на CAN-2, на CAN-1 НЕ форвардим (служебный кадр).
       Ответ идёт напрямую через hcan2 (NART — не блокирует, не зависит от CAN-1).
       Полезная нагрузка: байт0 = битмап онлайн-модулей, байты1/2 = последние коды истории. */
    if (CanId.command == PSU_KEEPALIVE_CMD) {
        CanId_t reply;
        reply.source      = PSU_BOARD_ADDR;
        reply.destination = CanId.source;
        reply.command     = PSU_KEEPALIVE_CMD;
        reply.device      = 0x0A;
        reply.error       = 0;
        CAN_TxHeaderTypeDef tx = {0};
        memcpy(&tx.ExtId, &reply, sizeof(CanId_t));
        tx.IDE = CAN_ID_EXT;
        tx.RTR = CAN_RTR_DATA;
        tx.DLC = 8;
        uint8_t pong[8] = {0};
        pong[0] = (PSU_State[0].online ? 0x01u : 0u) | (PSU_State[1].online ? 0x02u : 0u);
        pong[1] = PSU_State[0].history.codes[0];
        pong[2] = PSU_State[1].history.codes[0];
        uint32_t mb;
        if (HAL_CAN_GetTxMailboxesFreeLevel(&hcan2) > 0)
            HAL_CAN_AddTxMessage(&hcan2, &tx, pong, &mb);
        return;
    }

    // Синхронизируем внутреннее состояние прошивки по управляющим командам PC,
    // чтобы superloop не перетёр команду PC своими закоммиченными значениями.
    switch (CanId.command) {

    case 0x1A: {
        PSU_1A_t *p = (PSU_1A_t *)RxData;
        /* data[0]==0 → ВКЛ (инвертированная логика).
           КЗ-latch: блокируем ВКЛ от ПК — не обновляем ON_OFF и не форвардим. */
        uint8_t kz_dst = CanId.destination;
        if (p->enable == 0 && kz_dst < PSU_MAX_ADDR && psu_kz_faulted[kz_dst]) {
            return;
        }
        // Та же инверсия, что в PSU_Enable: 0=вкл → ON_OFF=2, 1=выкл → ON_OFF=1
        ON_OFF = p->enable ? 1u : 2u;
        break;
    }

    case 0x1C: {
        PSU_1C_t *p = (PSU_1C_t *)RxData;
        uint32_t v_mv = ((uint32_t)p->moduleVoltage[0]      << 24)
                      | ((uint32_t)p->moduleVoltage[1]      << 16)
                      | ((uint32_t)p->moduleVoltage[2]      <<  8)
                      |  (uint32_t)p->moduleVoltage[3];
        uint32_t i_ma = ((uint32_t)p->moduleCurrentTotal[0] << 24)
                      | ((uint32_t)p->moduleCurrentTotal[1] << 16)
                      | ((uint32_t)p->moduleCurrentTotal[2] <<  8)
                      |  (uint32_t)p->moduleCurrentTotal[3];
        // PC присылает ток на один модуль; Set_Current — суммарный по всем модулям
        uint16_t v       = (uint16_t)(v_mv / 1000u);
        uint16_t i_total = (uint16_t)((i_ma / 1000u) * (PSU_ActiveCount > 0 ? PSU_ActiveCount : 1u));
        if (v       >= 150u && v       <= 1000u) Set_Voltage = v;
        if (i_total >=   5u && i_total <=  150u) Set_Current = i_total;
        break;
    }

    default:
        break;
    }

    // Пробрасываем фрейм на CAN-1 → PSU исполняет команду немедленно,
    // не дожидаясь следующей итерации superloop.
    {
        CAN_TxHeaderTypeDef fwd = {
            .ExtId              = RxHeader.ExtId,
            .IDE                = RxHeader.IDE,
            .RTR                = RxHeader.RTR,
            .DLC                = RxHeader.DLC,
            .TransmitGlobalTime = DISABLE,
        };
        uint32_t mb;
        if (HAL_CAN_GetTxMailboxesFreeLevel(&hcan1) > 0)
            HAL_CAN_AddTxMessage(&hcan1, &fwd, RxData, &mb);
    }
}
