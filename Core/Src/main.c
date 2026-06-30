/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "can.h"
#include "spi.h"
#include "tim.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "ssd1306_fonts.h"
#include <stdlib.h>
#include <stdio.h>
#include "YRD0150BBS810F0MP-M7.h"
#include "epaper_text.h"
#include "psu_control.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define Delay 70
#define SETTINGS_FLASH_ADDR  0x0803F800UL   // последняя страница Flash (page 127, 2 KB)
#define SETTINGS_MAGIC       0xA55A5AA5UL   // маркер валидных данных
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */

// Глобальные массивы для совместимости
extern CAN_HandleTypeDef hcan1;

static uint8_t epaper_buf[ALLSCREEN_BYTES];

//Buttons
uint8_t Left;
uint8_t Right;
uint8_t Middle;
uint8_t Top;
uint8_t Bottom;

uint8_t previous_Left;
uint8_t previous_Right;
uint8_t previous_Middle;
uint8_t previous_Top;
uint8_t previous_Bottom;

//Parametr's
uint8_t Something_Changed = 1;
uint8_t Add_Number = 1;
uint8_t Button_Speed = 0;
static uint32_t last_volt_up = 0, last_volt_dn = 0;
static uint32_t last_curr_up = 0, last_curr_dn = 0;
static uint32_t last_onoff_tick = 0;
uint8_t Selected = 0;
uint8_t String_Number = 1;
uint8_t Screen = 2;
uint8_t ON_OFF = 1;// Off = 1 On = 2
uint16_t Set_Current = 5;
uint16_t Set_Voltage = 200;
uint16_t Current = 0;
uint16_t Voltage = 0;
char buffer[12];
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
static uint8_t compute_mode_code(uint8_t addr);
static void Settings_Load(void);
static void Settings_Save(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

void ReadButtons(void)
{
	Bottom = HAL_GPIO_ReadPin(BTN0_GPIO_Port, BTN0_Pin);
	Top = HAL_GPIO_ReadPin(BTN1_GPIO_Port, BTN1_Pin);
	Middle = HAL_GPIO_ReadPin(BTN2_GPIO_Port, BTN2_Pin);
	Right = HAL_GPIO_ReadPin(BTN3_GPIO_Port, BTN3_Pin);
	Left = HAL_GPIO_ReadPin(BTN4_GPIO_Port, BTN4_Pin);
	/* В режиме редактирования Left/Right тоже регулируют значение (level-triggered),
	 * поэтому ранний выход и сброс скорости должны учитывать их состояние. */
	uint8_t editing = (Selected == 1 && Screen == 2);
	if (Top == 1 && Bottom == 1 && (!editing || (Left == 1 && Right == 1))) {
		Button_Speed = 0;
		Add_Number = 1;
		last_volt_up = 0; last_volt_dn = 0;
		last_curr_up = 0; last_curr_dn = 0;
	}
	uint8_t prev_top    = previous_Top;
	uint8_t prev_bottom = previous_Bottom;
	if ((Right == previous_Right && Left == previous_Left && Middle == previous_Middle)
	    && (Top == 1 && Bottom == 1)
	    && (!editing || (Left == 1 && Right == 1))) {
		previous_Top = Top; previous_Bottom = Bottom;
		return;
	}
	previous_Left = Left;
	previous_Middle = Middle;
	previous_Right = Right;

	if (Top == 0 || Bottom == 0 || (editing && (Left == 0 || Right == 0)))
	{
		Button_Speed++;
		if (Button_Speed > 37) Add_Number = 96;
	}

	if (Middle == 0) {
		Selected++;
		Button_Speed = 0;
		Add_Number = 1;
		HAL_Delay(Delay);
	}

	if (Selected == 1 && Screen == 1) {
		uint32_t now_oo = HAL_GetTick();
		if (last_onoff_tick == 0 || (now_oo - last_onoff_tick) >= 5000u) {
			ON_OFF++;
			last_onoff_tick = now_oo ? now_oo : 1u;
		}
		Selected = 0;
	}
	if (Selected == 1 && Screen == 2)
	{
		// Ограничение скорости через время, а не HAL_Delay — чтобы не блокировать цикл
		// и не зависеть от скорости накопления Button_Speed.
		// fast = удержание >15 итераций (~750 мс при цикле ~50 мс).
		uint32_t now  = HAL_GetTick();
		uint8_t  fast = (Button_Speed > 37);

		if (String_Number == 1)
		{
			// При первом тике быстрого режима — выравниваем до ближайшего кратного 10
			// в сторону движения, чтобы дальше шло 390-400-410, а не 387-397-407.
			if (Button_Speed == 38) {
				if (Bottom == 0 || Left == 0)
					Set_Voltage = (Set_Voltage / 10u) * 10u;           // вниз: 387→380
				else if (Top == 0 || Right == 0)
					Set_Voltage = ((Set_Voltage + 9u) / 10u) * 10u;    // вверх: 387→390
				last_volt_up = now;
				last_volt_dn = now;
			}
			// Короткое: 1В/70 мс; долгое: 10В/100 мс
			uint32_t iv = fast ? 100u : 70u;
			uint16_t sv = fast ? 10u  : 1u;
			if ((Bottom == 0 || Left  == 0) && (now - last_volt_dn) >= iv) { Set_Voltage -= sv; last_volt_dn = now; }
			if ((Top   == 0 || Right == 0) && (now - last_volt_up) >= iv) { Set_Voltage += sv; last_volt_up = now; }
		}
		if (String_Number == 2)
		{
			// Короткое: 1А/200 мс (~5 А/с); долгое: 1А/50 мс (~20 А/с)
			uint32_t ic = fast ? 50u : 200u;
			if ((Bottom == 0 || Left  == 0) && (now - last_curr_dn) >= ic) { Set_Current--; last_curr_dn = now; }
			if ((Top   == 0 || Right == 0) && (now - last_curr_up) >= ic) { Set_Current++; last_curr_up = now; }
		}
	}
	else{
		if (Bottom == 0 && prev_bottom == 1) { String_Number--; HAL_Delay(Delay); }
		if (Top    == 0 && prev_top    == 1) { String_Number++; HAL_Delay(Delay); }
		if (Right == 0){
			Screen++;
			HAL_Delay(Delay);
		}
		if (Left == 0){
			Screen--;
			HAL_Delay(Delay);
		}
	}

	if (Selected > 1) Selected = 0;
	if (String_Number > 2) String_Number = 1;
	if (String_Number < 1) String_Number = 2;
	if (Screen > 2) Screen = 1;
	if (Screen < 1) Screen = 2;
	if (ON_OFF > 2) ON_OFF = 1;
	if (ON_OFF < 1) ON_OFF = 2;

	if (Set_Voltage >1000) Set_Voltage = 1000;
	if (Set_Voltage < 200) Set_Voltage = 200;
	if (Set_Current >150) Set_Current = 150;
	if (Set_Current < 10) Set_Current = 10;
	/*if (Set_Current < 20 && String_Number == 2) {
		Button_Speed = 0;
		Add_Number = 1;
	}*/
	{
	    uint16_t i_max = (uint16_t)(50000u / Set_Voltage);
	    if (Set_Current > i_max) Set_Current = i_max;
	}
	previous_Bottom = Bottom;
	previous_Top = Top;
}

void ShowScreen(void){
	if (Screen == 1){
		ssd1306_Fill(Black);
		ssd1306_SetCursor(16, 5);
		// Фактическое состояние: хотя бы один онлайн-модуль с активным выходом
		uint8_t actual_on = 0;
		for (uint8_t _i = 0; _i < PSU_ActiveCount; _i++) {
			uint8_t _a = PSU_ActiveAddrs[_i];
			if (PSU_State[_a].online && PSU_State[_a].mode == 1) { actual_on = 1; break; }
		}
		if (actual_on)
			ssd1306_WriteStringUTF8(">СTOп", White);
		else
			ssd1306_WriteStringUTF8(">Пуck", White);//Пуck

		ssd1306_SetCursor(5, 44);
		snprintf(buffer, sizeof(buffer), "U=%dВ", Voltage);
		ssd1306_WriteStringUTF8(buffer, White);
		ssd1306_SetCursor(5, 77);
		snprintf(buffer, sizeof(buffer), "I=%dA", Current);
		ssd1306_WriteStringUTF8(buffer, White);

		// Рамка вокруг параметра, в который уперлись: CV (01) → напряжение, CC (02) → ток
		uint8_t _any_cv = 0, _any_cc = 0;
		for (uint8_t _mi = 0; _mi < PSU_ActiveCount; _mi++) {
			uint8_t _mc = compute_mode_code(PSU_ActiveAddrs[_mi]);
			if (_mc == 1) _any_cv = 1;
			if (_mc == 2) _any_cc = 1;
		}
		if (_any_cv) ssd1306_DrawRectangle(0, 42, 127, 70, White);
		if (_any_cc) ssd1306_DrawRectangle(0, 75, 127, 103, White);

		// Заданные значения мелким шрифтом в рамке внизу, одной строкой: напр. "250B 20A"
		ssd1306_DrawRectangle(0, 105, 127, 127, White);
		snprintf(buffer, sizeof(buffer), "%dB %dA", Set_Voltage, Set_Current);
		ssd1306_SetCursor(8, 107);
		ssd1306_WriteString11x18(buffer, White);

		ssd1306_UpdateScreen();
	}
	else{
		ssd1306_Fill(Black);
		ssd1306_SetCursor(0, 5);
		ssd1306_WriteStringUTF8("ВВОД", White);
		ssd1306_SetCursor(0, 33);
		ssd1306_WriteStringUTF8("ЗНАЧЕНИЙ", White);
		ssd1306_Line(0, 94, 128, 94, White);
		ssd1306_DrawRectangle(0, 60, 127, 127, White);

		if (String_Number == 1 && Selected == 0)
		{
			ssd1306_SetCursor(5, 67);
			snprintf(buffer, sizeof(buffer), ">\x01=%dВ ", Set_Voltage);
			ssd1306_WriteStringUTF8(buffer, White);
			ssd1306_SetCursor(5, 100);
			snprintf(buffer, sizeof(buffer), " \x02=%dA ", Set_Current);
			ssd1306_WriteStringUTF8(buffer, White);
			ssd1306_UpdateScreen();
		}

		if (String_Number == 2 && Selected == 0)
		{
			ssd1306_SetCursor(5, 67);
			snprintf(buffer, sizeof(buffer), " \x01=%dВ ", Set_Voltage);
			ssd1306_WriteStringUTF8(buffer, White);
			ssd1306_SetCursor(5, 100);
			snprintf(buffer, sizeof(buffer), ">\x02=%dA ", Set_Current);
			ssd1306_WriteStringUTF8(buffer, White);
			ssd1306_UpdateScreen();
		}

		if (String_Number == 1 && Selected == 1)
		{
			ssd1306_SetCursor(5, 67);
			snprintf(buffer, sizeof(buffer), " \x01=%dВ ", Set_Voltage);
			ssd1306_WriteStringUTF8(buffer, Black);
			ssd1306_SetCursor(5, 100);
			snprintf(buffer, sizeof(buffer), " \x02=%dA ", Set_Current);
			ssd1306_WriteStringUTF8(buffer, White);
			ssd1306_UpdateScreen();
		}

		if (String_Number == 2 && Selected == 1)
		{
			ssd1306_SetCursor(5, 67);
			snprintf(buffer, sizeof(buffer), " \x01=%dВ ", Set_Voltage);
			ssd1306_WriteStringUTF8(buffer, White);
			ssd1306_SetCursor(5, 98);
			snprintf(buffer, sizeof(buffer), " \x02=%dA ", Set_Current);
			ssd1306_WriteStringUTF8(buffer, Black);
			ssd1306_UpdateScreen();
		}
	}
}

/*void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance == TIM7)
    {
    	Something_Changed = 1;
    }
}*/

/* Возвращает код из истории событий модуля addr.
 * slot 0 = новейший, slot 2 = старейший. 0 = пустой слот. */
static uint8_t decode_slot(uint8_t addr, uint8_t slot) {
    if (slot >= 3) slot = 2;
    return PSU_State[addr].history.codes[slot];
}

/* Вычисляет текущий рабочий код (01–03) для активного модуля.
 * Возвращает 0 если модуль не в активном состоянии или режим не определён.
 * Используем уставку на модуль (Set_Voltage / PSU_ActiveCount): каждый модуль
 * выдаёт свою долю напряжения, поэтому сравнение с полной уставкой неверно. */
static uint8_t compute_mode_code(uint8_t addr) {
    if (!PSU_State[addr].online || PSU_State[addr].mode == 0) return 0;
    uint16_t v    = PSU_State[addr].outputVoltage;
    int16_t  i    = PSU_State[addr].outputCurrent;
    uint32_t p    = PSU_State[addr].outputPower;
    uint16_t i_sp = (PSU_ActiveCount > 0u) ? (Set_Current / PSU_ActiveCount) : Set_Current;
    uint16_t v_sp = Set_Voltage;  /* модули параллельные: каждый выдаёт полное уставочное напряжение */
    if (p >= 25000u) return 3;
    if (v >= (uint16_t)(v_sp > 10u ? v_sp - 10u : 0u) &&
        i  <  (int16_t)(i_sp > 1u ? i_sp - 1u : 0)) return 1;
    if (i >= (int16_t)(i_sp > 1u ? i_sp - 1u : 0) &&
        v  <  (uint16_t)(v_sp > 10u ? v_sp - 10u : 0u)) return 2;
    return 0;
}

static void Settings_Load(void) {
    uint32_t magic = *(volatile uint32_t*)SETTINGS_FLASH_ADDR;
    if (magic != SETTINGS_MAGIC) return;
    uint32_t vc = *(volatile uint32_t*)(SETTINGS_FLASH_ADDR + 4);
    uint16_t v = (uint16_t)(vc & 0xFFFFu);
    uint16_t c = (uint16_t)(vc >> 16);
    if (v >= 200u && v <= 1000u && c >= 10u && c <= 150u) {
        Set_Voltage = v;
        Set_Current = c;
    }
}

static void Settings_Save(void) {
    FLASH_EraseInitTypeDef erase = {0};
    uint32_t pageError = 0;
    HAL_FLASH_Unlock();
    erase.TypeErase   = FLASH_TYPEERASE_PAGES;
    erase.PageAddress = SETTINGS_FLASH_ADDR;
    erase.NbPages     = 1;
    HAL_FLASHEx_Erase(&erase, &pageError);
    HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, SETTINGS_FLASH_ADDR, SETTINGS_MAGIC);
    uint32_t vc = ((uint32_t)Set_Current << 16) | Set_Voltage;
    HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, SETTINGS_FLASH_ADDR + 4, vc);
    HAL_FLASH_Lock();
}

static void DrawEpaperStatusTable(void) {
    char str[4];
    epaper_clear_buffer(epaper_buf);

    /* Дисплей повёрнут 90°: x = вертикаль для наблюдателя, y = горизонталь.
     * Экран 200×200.
     *
     * Viewer y: 0..99 = левая половина (модуль I), 100..199 = правая (модуль II).
     * Viewer x (сверху вниз):
     *   x=8        → заголовки "I" / "II"
     *   x=46..47   → горизонтальная разделительная линия
     *   x=52       → слот 0
     *   x=90       → слот 1
     *   x=128      → слот 2
     *
     * Вертикальная линия: y=99..100 (вся высота).
     *
     * scale=4 → символ 32×32px.
     * Центрирование в 100px половинке:
     *   1 символ (32px) → отступ (100-32)/2 = 34
     *   2 символа (64px) → отступ (100-64)/2 = 18
     */
    const uint8_t  scale  = 4;
    const uint16_t cs     = 8u * scale;    // 32 px

    const uint16_t x_hdr  = 8;
    const uint16_t x_hlin = x_hdr + cs + 6u;   // 46
    const uint16_t x_s0   = x_hlin + 6u;        // 52
    const uint16_t x_s1   = x_s0  + cs + 6u;   // 90
    const uint16_t x_s2   = x_s1  + cs + 6u;   // 128

    // y_start, центрированный в левой/правой половине для 1- и 2-символьных строк
    const uint16_t y_hdr0  = (100u - 1u * cs) / 2u;         // "I"  → 34
    const uint16_t y_hdr1  = 100u + (100u - 2u * cs) / 2u;  // "II" → 118
    const uint16_t y_cod0  = (100u - 2u * cs) / 2u;         // "XX" → 18
    const uint16_t y_cod1  = 100u + (100u - 2u * cs) / 2u;  // "XX" → 118

    // ── Вертикальная линия по центру дисплея (y=99, 100) ──────────────────
    for (uint16_t xi = 0; xi < 200u; xi++) {
        epaper_set_pixel(epaper_buf, xi, 99u,  0);
        epaper_set_pixel(epaper_buf, xi, 100u, 0);
    }

    // ── Горизонтальная линия под заголовками (x=x_hlin, x_hlin+1) ─────────
    for (uint16_t yi = 0; yi < 200u; yi++) {
        epaper_set_pixel(epaper_buf, x_hlin,     yi, 0);
        epaper_set_pixel(epaper_buf, x_hlin + 1u, yi, 0);
    }

    // ── Заголовки ──────────────────────────────────────────────────────────
    epaper_draw_string(epaper_buf, x_hdr, y_hdr0, "I",  font8x8_basic, scale);
    epaper_draw_string(epaper_buf, x_hdr, y_hdr1, "II", font8x8_basic, scale);

    // ── 3 строки статусов: фиксированные позиции ──────────────────────────
    // слот 0 → колонка 0 (новейший), слот 1 → колонка 1, слот 2 → колонка 2.
    // Позиции не сдвигаются; пустой слот оставляет пустое место.
    const uint16_t x_rows[3] = {x_s0, x_s1, x_s2};

    for (uint8_t slot = 0; slot < 3; slot++) {
        uint8_t c0 = decode_slot(0, slot);
        /* 0xFF = пустой слот; 0x00 = событие «норма». */
        if (c0 != 0xFF) {
            snprintf(str, sizeof(str), "%02u", (unsigned)c0);
            epaper_draw_string(epaper_buf, x_rows[slot], y_cod0, str, font8x8_basic, scale);
        }

        uint8_t c1 = decode_slot(1, slot);
        if (c1 != 0xFF) {
            snprintf(str, sizeof(str), "%02u", (unsigned)c1);
            epaper_draw_string(epaper_buf, x_rows[slot], y_cod1, str, font8x8_basic, scale);
        }
    }
}

static void ShowEpaper(void) {
    if (Selected == 1 && Screen == 2) return;

    static bool     initialized      = false;
    static uint8_t  cached_codes[2][3];
    static bool     cached_online[2];

    uint8_t codes[2][3];
    bool    online[2] = {PSU_State[0].online, PSU_State[1].online};

    for (uint8_t m = 0; m < 2; m++) {
        for (uint8_t slot = 0; slot < 3; slot++) {
            codes[m][slot] = decode_slot(m, slot);
        }
    }

    bool changed = !initialized;
    for (uint8_t m = 0; m < 2 && !changed; m++) {
        if (online[m] != cached_online[m]) changed = true;
        for (uint8_t s = 0; s < 3 && !changed; s++)
            if (codes[m][s] != cached_codes[m][s]) changed = true;
    }

    if (!changed) return;

    for (uint8_t m = 0; m < 2; m++) {
        cached_online[m] = online[m];
        for (uint8_t s = 0; s < 3; s++)
            cached_codes[m][s] = codes[m][s];
    }

    DrawEpaperStatusTable();

    if (!initialized) {
        Display_image_new(epaper_buf);        // первый раз — полное обновление
        initialized = true;
    } else {
        Display_image_new_partial_update(epaper_buf);  // далее — частичное
    }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_CAN1_Init();
  MX_CAN2_Init();
  MX_SPI1_Init();
  MX_SPI2_Init();
  MX_TIM7_Init();
  /* USER CODE BEGIN 2 */
  HAL_CAN_Start(&hcan1);
  HAL_TIM_Base_Start_IT(&htim7);
  PSU_Init();
  PSU_CAN2_BridgeInit();
  // 1. Сканируем адреса модулей
  //PSU_ScanAndStoreAddresses();
  ssd1306_Init();
  ssd1306_Rotate0();
  ssd1306_UpdateScreen();

  EpaperIO_Init();
  Epaper_SetBusyCallback(ReadButtons);
  Settings_Load();

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  uint8_t  prev_on_off        = ON_OFF;
  uint16_t committed_voltage  = Set_Voltage;
  uint16_t committed_current  = Set_Current;
  uint16_t saved_voltage      = Set_Voltage;   // последнее сохранённое в Flash
  uint16_t saved_current      = Set_Current;
  while (1)
  {
	  ReadButtons();

	  // Фиксируем уставки только когда пользователь отпустил все кнопки регулировки.
	  // Во время удержания в модуль идут прежние (закоммиченные) значения.
	  uint8_t adjusting = (Selected == 1 && Screen == 2);
	  if (!adjusting) {
		  committed_voltage = Set_Voltage;
		  committed_current = Set_Current;
		  // Сохраняем в Flash если значения изменились
		  if (committed_voltage != saved_voltage || committed_current != saved_current) {
			  Settings_Save();
			  saved_voltage = committed_voltage;
			  saved_current = committed_current;
		  }
	  }

	  // Переключение OFF→ON: сбрасываем fault-флаги всех модулей (ручной рестарт оператором).
	  if (prev_on_off != ON_OFF && ON_OFF == 2) {
		  for (uint8_t _fi = 0; _fi < PSU_ActiveCount; _fi++)
			  PSU_ClearFault(PSU_ActiveAddrs[_fi]);
	  }
	  prev_on_off = ON_OFF;

	  PSU_UpdateAll(committed_voltage, committed_current, (ON_OFF == 2) ? 1 : 0);
	  PSU_Loop();

	  /* Пушим рабочие коды (00–03): только когда модуль в сети */
	  for (uint8_t _m = 0; _m < PSU_ActiveCount; _m++) {
		  uint8_t addr = PSU_ActiveAddrs[_m];
		  if (!PSU_State[addr].online) continue;  /* offline → код 04 уже пушнул PSU_Loop, 00 не добавляем */
		  PSU_PushStatusCode(addr, compute_mode_code(addr));
	  }

	  ShowEpaper();

	  if (PSU_ActiveCount == 0) {
		  HAL_Delay(10);
		  continue;
	  }

	  if (Something_Changed) {
		  Something_Changed = 0;
	  }
	  for (uint8_t i = 0; i < PSU_ActiveCount; i++) {
		  if (PSU_State[PSU_ActiveAddrs[i]].forceApply)
			  PSU_State[PSU_ActiveAddrs[i]].forceApply = false;
	  }

	  Voltage = PSU_TotalVoltage;
	  Current = PSU_TotalCurrent / 1000;
	  ShowScreen();

    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.HSEPredivValue = RCC_HSE_PREDIV_DIV5;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.Prediv1Source = RCC_PREDIV1_SOURCE_PLL2;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL9;
  RCC_OscInitStruct.PLL2.PLL2State = RCC_PLL2_ON;
  RCC_OscInitStruct.PLL2.PLL2MUL = RCC_PLL2_MUL8;
  RCC_OscInitStruct.PLL2.HSEPrediv2Value = RCC_HSE_PREDIV2_DIV5;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure the Systick interrupt time
  */
  __HAL_RCC_PLLI2S_ENABLE();
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
