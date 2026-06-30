#include "YRD0150BBS810F0MP-M7.h"
#include "spi.h"          // содержит hspi1

extern SPI_HandleTypeDef hspi1;

static EpaperBusyCb_t busy_cb = NULL;

void Epaper_SetBusyCallback(EpaperBusyCb_t cb) {
    busy_cb = cb;
}

// ========== Приблизительная микросекундная задержка ==========
static void delay_us(uint32_t us)
{
    uint32_t count = us * (SystemCoreClock / 1000000) / 5;
    for(uint32_t i = 0; i < count; i++)
        __NOP();
}

// ========== Аппаратный SPI ==========
static void SPI_WriteByte(uint8_t data)
{
    HAL_SPI_Transmit(&hspi1, &data, 1, HAL_MAX_DELAY);
}

// ========== Команда / данные ==========
static void WriteCommand(uint8_t cmd)
{
    HAL_GPIO_WritePin(CS_PORT, CS_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(DC_PORT, DC_PIN, GPIO_PIN_RESET);
    delay_us(5);
    SPI_WriteByte(cmd);
    delay_us(5);
    HAL_GPIO_WritePin(CS_PORT, CS_PIN, GPIO_PIN_SET);
}

static void WriteData(uint8_t data)
{
    HAL_GPIO_WritePin(CS_PORT, CS_PIN, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(DC_PORT, DC_PIN, GPIO_PIN_SET);
    delay_us(5);
    SPI_WriteByte(data);
    delay_us(5);
    HAL_GPIO_WritePin(CS_PORT, CS_PIN, GPIO_PIN_SET);
}

// ========== Ожидание BUSY ==========
static void WaitBusy(void)
{
    uint32_t last_cb = 0;
    while(HAL_GPIO_ReadPin(BUSY_PORT, BUSY_PIN) == GPIO_PIN_SET) {
        if (busy_cb != NULL) {
            uint32_t t = HAL_GetTick();
            if ((t - last_cb) >= 50u) {
                last_cb = t;
                busy_cb();
            }
        }
        delay_us(5);
    }
    delay_us(100);
}

// ========== Инициализация пинов (вызывать после MX_GPIO_Init и MX_SPI1_Init) ==========
void EpaperIO_Init(void)
{
    // Установить начальные уровни
    HAL_GPIO_WritePin(CS_PORT, CS_PIN, GPIO_PIN_SET);
    HAL_GPIO_WritePin(DC_PORT, DC_PIN, GPIO_PIN_SET);
    HAL_GPIO_WritePin(RES_PORT, RES_PIN, GPIO_PIN_SET);
    // BUSY – вход, ничего не пишем
}

// ========== Полная инициализация дисплея ==========
void Epaper_Initial(void)
{
    // Сброс
    HAL_GPIO_WritePin(RES_PORT, RES_PIN, GPIO_PIN_RESET);
    HAL_Delay(10);
    HAL_GPIO_WritePin(RES_PORT, RES_PIN, GPIO_PIN_SET);
    HAL_Delay(10);
    WaitBusy();

    WriteCommand(0x12);   // soft reset
    WaitBusy();

    WriteCommand(0x01);
    WriteData(Y_Addr_Start_L);
    WriteData(Y_Addr_Start_H);
    WriteData(0x00);

    WriteCommand(0x11);
    WriteData(0x01);      // Y decrement, X increment

    WriteCommand(0x44);
    WriteData(X_Addr_Start);
    WriteData(X_Addr_End);

    WriteCommand(0x45);
    WriteData(Y_Addr_Start_L);
    WriteData(Y_Addr_Start_H);
    WriteData(Y_Addr_End_L);
    WriteData(Y_Addr_End_H);

    WriteCommand(0x4E);
    WriteData(X_Addr_Start);
    WriteCommand(0x4F);
    WriteData(Y_Addr_Start_L);
    WriteData(Y_Addr_Start_H);

    WriteCommand(0x3C);
    WriteData(0x05);
    WriteCommand(0x21);
    WriteData(0x00);
    WriteData(0x00);
    WriteCommand(0x3C);
    WriteData(0x80);
}

void Epaper_Initial_partial(void)
{
    HAL_GPIO_WritePin(RES_PORT, RES_PIN, GPIO_PIN_RESET);
    HAL_Delay(10);
    HAL_GPIO_WritePin(RES_PORT, RES_PIN, GPIO_PIN_SET);
    HAL_Delay(10);
    WaitBusy();

    WriteCommand(0x3C);
    WriteData(0x80);
}

// ========== Обновление экрана ==========
void Epaper_Update_and_Deepsleep_full_update(void)
{
    WriteCommand(0x22);
    WriteData(0xF7);
    WriteCommand(0x20);
    WaitBusy();
    WriteCommand(0x10);
    WriteData(0x01);
    HAL_Delay(100);
}

void Epaper_Update_and_Deepsleep_partial_update(void)
{
    WriteCommand(0x22);
    WriteData(0xFF);
    WriteCommand(0x20);
    WaitBusy();
    WriteCommand(0x10);
    WriteData(0x01);
    HAL_Delay(100);
}

// ========== Заливка цветом ==========
void Epaper_Load_White(void)
{
    WriteCommand(0x24);
    for(uint32_t col = 0; col < MAX_COLUMN_BYTES; col++)
        for(uint32_t line = 0; line < MAX_LINE_BYTES; line++)
            WriteData(0xFF);
}

void Epaper_Load_Black(void)
{
    WriteCommand(0x24);
    for(uint32_t col = 0; col < MAX_COLUMN_BYTES; col++)
        for(uint32_t line = 0; line < MAX_LINE_BYTES; line++)
            WriteData(0x00);
}

// ========== Загрузка изображения ==========
void Epaper_load_image_new(uint8_t *BN_DTM)
{
    uint32_t i;
    uint8_t temp;
    uint32_t col = 0, line = 0;

    WriteCommand(0x24);
    for(i = 0; i < ALLSCREEN_BYTES; i++)
    {
        temp = BN_DTM[line * MAX_COLUMN_BYTES + col];
        line++;
        if(line >= MAX_LINE_BYTES)
        {
            col++;
            line = 0;
        }
        WriteData(temp);
    }

    col = 0; line = 0;
    WriteCommand(0x26);
    for(i = 0; i < ALLSCREEN_BYTES; i++)
    {
        temp = BN_DTM[line * MAX_COLUMN_BYTES + col];
        line++;
        if(line >= MAX_LINE_BYTES)
        {
            col++;
            line = 0;
        }
        WriteData(temp);
    }
}

void Epaper_load_image_new_patial(uint8_t *BN_DTM)
{
    uint32_t i;
    uint8_t temp;
    uint32_t col = 0, line = 0;

    WriteCommand(0x24);
    for(i = 0; i < ALLSCREEN_BYTES; i++)
    {
        temp = BN_DTM[line * MAX_COLUMN_BYTES + col];
        line++;
        if(line >= MAX_LINE_BYTES)
        {
            col++;
            line = 0;
        }
        WriteData(temp);
    }
}

// ========== Пользовательские функции ==========
void Display_black(void)
{
    Epaper_Initial();
    Epaper_Load_Black();
    Epaper_Update_and_Deepsleep_full_update();
}

void Display_white(void)
{
    Epaper_Initial();
    Epaper_Load_White();
    Epaper_Update_and_Deepsleep_full_update();
}

void Display_image_new(uint8_t *BN_DTM)
{
    Epaper_Initial();
    Epaper_load_image_new(BN_DTM);
    Epaper_Update_and_Deepsleep_full_update();
}

void Display_image_new_partial_update(uint8_t *BN_DTM)
{
    Epaper_Initial_partial();
    Epaper_load_image_new_patial(BN_DTM);
    Epaper_Update_and_Deepsleep_partial_update();
}
