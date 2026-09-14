/* Spectrum logger - a stripped-down relative of app/spectrum.c.
 *
 * It sweeps a fixed 128-bin window for ever, never listens, never stops on a
 * peak and never opens the audio path. Every LOG_AVG_SECONDS it writes the
 * mean level of each bin over that window into EEPROM as one 128-byte frame,
 * and stops when the store is full.
 *
 * Averaging is per completed sweep, not per measurement: each sweep adds one
 * sample to every bin's accumulator, so all 128 bins always carry the same
 * sample count and one divisor serves the whole frame. The 30 s timer only
 * arms the write; the frame is emitted at the next sweep boundary, which is
 * why a partial sweep can never skew one bin against its neighbours.
 *
 * It averages POWER, not decibels. RSSI is a log quantity, so summing it would
 * give the geometric mean of power - which for a bin that is quiet for 27 s and
 * carries a signal for 3 s reports something close to the noise floor, hiding
 * exactly the bursty traffic a band logger is for. Samples are therefore mapped
 * to linear power, accumulated, and mapped back at the end of the window.
 *
 * linTable[] holds 10^(halfDb/20) and is built at start-up by repeated
 * multiplication rather than stored: 511 float multiplies cost microseconds
 * once, accumulate about 0.0002 dB of error, and save 2 KiB of flash. Going
 * back to dB is a binary search over the same table, so no logarithm is needed
 * anywhere and the stored format is unchanged.
 *
 * EEPROM format, all little-endian (k5logdump.py is the reader):
 *
 *   Header, 128 B at LOG_HEADER_ADDR
 *     0x00  4  magic "K5SL"
 *     0x04  1  format version (4)
 *     0x05  1  bins per frame (128)
 *     0x06  1  bits per bin (4)
 *     0x07  1  flags: bit 0 = session was closed cleanly
 *     0x08  4  frequency of bin 0, in 10 Hz units
 *     0x0C  4  bin spacing, in 10 Hz units
 *     0x10  2  seconds averaged per frame
 *     0x12  2  frames per block (127)
 *     0x14  1  blocks in the store
 *     0x15  1  band index the sweep started in
 *     0x16  1  dBm correction for that band (int8)
 *     0x17  1  reserved
 *     0x18  4  wall clock at the first frame, seconds since midnight
 *     0x1C  4  session tag, to tell one run's leftovers from another's
 *     0x20  4  frames written      <-- the only two fields rewritten in flight,
 *     0x24  4  seconds logged      <-- one aligned 8-byte write per 16 KiB block
 *     0x28  2  level 0 in dBm, int16 (-130; it does not fit in a byte)
 *     0x2A  1  dB per level (1)
 *     0x2B  1  reserved (the level count is 2^bits, so it is not stored: 256
 *              would not fit in a byte)
 *     0x2C  ...  zero
 *
 *   Block, 16 KiB: a 128-byte timestamp record, then 127 frames of 128 bytes:
 *     0x00  4  magic "K5LB"
 *     0x04  2  block index
 *     0x06  2  reserved
 *     0x08  4  wall clock at this block's first frame
 *     0x0C  4  seconds since logging started, same instant
 *     0x10  4  frames written before this block
 *     0x14  ...  zero
 *
 * A frame is one byte per bin: an absolute dBm, byte = dBm + 185, 1 dB steps,
 * with the band correction already folded in (it stays in the header only to
 * say what was used). 4-bit levels on a 5 dB ladder fitted twice as many frames
 * and were tried first, but a UHF sweep put 74% of its samples on the bottom
 * rail, which makes the noise floor unmeasurable and every weak signal
 * indistinguishable from silence. A byte per bin costs half the session -
 * 1778 frames, about 15 hours - and clips at neither end.
 *
 * Wear: every frame slot is written once per session and the header's counter
 * pair once per 16 KiB - roughly once an hour at the default 30 s average.
 *
 * A transfer never straddles a 64 KiB EEPROM device-page boundary, which would
 * wrap: driver/eeprom.c puts the high address bits in the I2C device address
 * and the low 16 in the transfer, so anything crossing 0x10000/0x20000/0x30000
 * would silently read or write the wrong place. Frames are 64 B on a 64 B grid
 * and writes are 8 B on an 8 B grid, so every transfer sits inside one page.
 */

#include "app/speclog.h"

#include "app/spectrum.h"   // scan step tables, DrawingTopY/DrawingEndY
#include "driver/backlight.h"
#include "driver/bk4819.h"
#include "driver/eeprom.h"
#include "driver/keyboard.h"
#include "driver/st7565.h"
#include "driver/system.h"
#include "driver/systick.h"
#include "external/printf/printf.h"
#include "helper/battery.h"
#include "misc.h"
#include "radio.h"
#include "ui/helper.h"
#include "ui/inputbox.h"
#include "ui/main.h"        // dBmCorrTable

#ifdef ENABLE_UART
#include "app/uart.h"
#endif

#include <string.h>

#define LOG_FRAMES_TOTAL (LOG_BLOCKS_TOTAL * LOG_FRAMES_PER_BLOCK)   // 3556

// Selectable spacing, as indices into scanStepValues[]. 8.33 kHz is left out
// on purpose: it is the one step the spectrum has to round frequencies for.
static const uint8_t stepChoices[] = {
    S_STEP_6_25kHz, S_STEP_12_5kHz, S_STEP_25_0kHz, S_STEP_50_0kHz, S_STEP_100_0kHz};
static uint8_t stepChoice = 2;   // 25 kHz, so 128 bins span 3.2 MHz

typedef enum
{
    LOG_SET_CLOCK,   // entering the time of day, nothing is being recorded yet
    LOG_RUNNING,
    LOG_FULL,
} LoggerState;

static LoggerState state;
static bool        running;

// Sweep
static uint32_t fStart;          // bin 0, 10 Hz units
static uint16_t fStep;
static uint32_t fMeasure;
static uint16_t scanReg30;
static uint16_t bin;

// Averaging window. Float, because the linear span of the RSSI range is far
// wider than any integer accumulator: bin 0 to bin 511 is 10^25.5.
static float    linTable[512];
static float    acc[LOG_BINS];
static uint16_t sweeps;
static bool     framePending;    // the 30 s are up; emit at the next sweep end

// Clock and position in the store
static uint32_t startClock;      // seconds since midnight, as typed by the operator
static uint32_t elapsed;         // seconds since the first frame
static uint16_t avgSeconds;      // seconds into the current averaging window
static uint8_t  halfSeconds;
static uint32_t sessionTag;
static uint32_t framesWritten;
static uint8_t  block;
static uint8_t  frameInBlock;

// Time entry
static uint8_t clockDigits[6];
static uint8_t clockIndex;

// Battery. An unattended logger can easily outlive the pack, and while this
// app runs the main loop's battery handling does not, so watch it here and
// close the session while there is still enough left to write the header.
#define LOG_BATTERY_STOP_PERCENT 5
static uint8_t batteryPercent = 100;

// Keys
static KEY_Code_t lastKey = KEY_INVALID;
static uint8_t    keySettled;

// Display
static char     String[32];
static uint8_t  backlightSeconds;
static bool     redraw = true;
static uint8_t  renderPage;

static const BK4819_REGISTER_t registers_to_save[] = {
    BK4819_REG_30, BK4819_REG_37, BK4819_REG_3D, BK4819_REG_43,
    BK4819_REG_47, BK4819_REG_48, BK4819_REG_7E,
};
static uint16_t registers_stack[ARRAY_SIZE(registers_to_save)];

// ---------------------------------------------------------------- EEPROM ---

static uint32_t BlockAddr(uint8_t b)
{
    return LOG_BLOCK_BASE + (uint32_t)b * LOG_BLOCK;
}

// EEPROM_WriteBuffer() is an 8-byte-page affair everywhere else in this
// firmware (settings.c, app/uart.c both chunk at 8), and it sleeps 10 ms per
// call, so a full 128-byte record costs ~160 ms. That is once per 30 s and
// only ever between sweeps.
static void LogWrite(uint32_t addr, const void *data, uint16_t size)
{
    const uint8_t *p = (const uint8_t *)data;

    while (size)
    {
        const uint8_t n = (size > 8u) ? 8u : (uint8_t)size;
        EEPROM_WriteBuffer(addr, p, n);
        addr += n;
        p += n;
        size -= n;
    }
}

static void WriteHeader(bool closed)
{
    uint8_t h[LOG_STAMP];

    memset(h, 0, sizeof(h));
    memcpy(h, "K5SL", 4);
    h[0x04] = 4;
    h[0x05] = LOG_BINS;
    h[0x06] = LOG_BIN_BITS;
    h[0x07] = closed ? 1 : 0;
    memcpy(&h[0x08], &fStart, 4);
    const uint32_t stepUnits = fStep;   // 10 Hz units, like every frequency here
    memcpy(&h[0x0C], &stepUnits, 4);
    h[0x10] = LOG_AVG_SECONDS;
    h[0x12] = (uint8_t)(LOG_FRAMES_PER_BLOCK & 0xFFu);
    h[0x13] = (uint8_t)(LOG_FRAMES_PER_BLOCK >> 8);
    h[0x14] = LOG_BLOCKS_TOTAL;
    h[0x15] = gRxVfo->Band;
    h[0x16] = (uint8_t)dBmCorrTable[gRxVfo->Band];
    memcpy(&h[0x18], &startClock, 4);
    memcpy(&h[0x1C], &sessionTag, 4);
    memcpy(&h[0x20], &framesWritten, 4);
    memcpy(&h[0x24], &elapsed, 4);
    const int16_t dbmBase = LOG_DBM_BASE;
    memcpy(&h[0x28], &dbmBase, 2);
    h[0x2A] = LOG_DBM_STEP;

    LogWrite(LOG_HEADER_ADDR, h, sizeof(h));
}

// The in-flight counter update: one 8-byte write, because frames and seconds
// were laid out adjacent and 8-byte aligned for exactly this.
static void UpdateHeaderCounters(void)
{
    uint8_t c[8];

    memcpy(&c[0], &framesWritten, 4);
    memcpy(&c[4], &elapsed, 4);
    LogWrite(LOG_HEADER_ADDR + 0x20, c, sizeof(c));
}

static void WriteBlockStamp(void)
{
    uint8_t s[32];
    const uint32_t wall = startClock + elapsed;
    const uint16_t idx = block;

    memset(s, 0, sizeof(s));
    memcpy(s, "K5LB", 4);
    memcpy(&s[0x04], &idx, 2);
    memcpy(&s[0x08], &wall, 4);
    memcpy(&s[0x0C], &elapsed, 4);
    memcpy(&s[0x10], &framesWritten, 4);

    LogWrite(BlockAddr(block), s, sizeof(s));
}

// ------------------------------------------------------------- averaging ---

static void ResetWindow(void)
{
    memset(acc, 0, sizeof(acc));
    sweeps = 0;
    avgSeconds = 0;
    framePending = false;
}

static void EmitFrame(void)
{
    uint8_t frame[LOG_FRAME_BYTES];

    // 2 * (dBm - LOG_DBM_BASE) = lo + 2*corr + 2*(RSSI_DBM_OFFSET - DBM_BASE),
    // all integer: lo is in half-dB, so working at twice the scale keeps the
    // rounding exact.
    const int32_t bias = 2 * (int32_t)dBmCorrTable[gRxVfo->Band] +
                         2 * (LOG_RSSI_DBM_OFFSET - LOG_DBM_BASE);

    for (uint16_t i = 0; i < LOG_BINS; i++)
    {
        const float mean = acc[i] / (float)sweeps;

        // Largest table entry not above the mean: the mean power expressed
        // back in the radio's own half-dB units. mean is never below
        // linTable[0], since every sample added was at least that.
        uint16_t lo = 0, hi = ARRAY_SIZE(linTable) - 1u;
        while (lo < hi)
        {
            const uint16_t mid = (lo + hi + 1u) >> 1;
            if (linTable[mid] <= mean)
                lo = mid;
            else
                hi = mid - 1u;
        }

        // Onto the 10 dB ladder, rounded to nearest, saturating at both ends.
        int32_t level = ((int32_t)lo + bias + LOG_DBM_STEP) / (2 * LOG_DBM_STEP);
        if (level < 0)
            level = 0;
        else if (level > LOG_LEVELS - 1)
            level = LOG_LEVELS - 1;

        frame[i] = (uint8_t)level;
    }

    if (frameInBlock == 0)
        WriteBlockStamp();

    LogWrite(BlockAddr(block) + LOG_STAMP + (uint32_t)frameInBlock * LOG_FRAME_BYTES,
             frame, sizeof(frame));
    framesWritten++;

    if (++frameInBlock >= LOG_FRAMES_PER_BLOCK)
    {
        frameInBlock = 0;
        block++;
        UpdateHeaderCounters();   // once per 16 KiB, as promised in the header
        if (block >= LOG_BLOCKS_TOTAL)
        {
            state = LOG_FULL;
            WriteHeader(true);
        }
    }

    ResetWindow();
    redraw = true;
}

// ------------------------------------------------------------------ scan ---

static uint16_t ReadRssi(void)
{
    // Same settle-then-discard dance as the spectrum's GetRssi().
    uint8_t guard = 50;
    while (guard-- && (BK4819_ReadRegister(0x63) & 0xFF) >= 200)
        SYSTICK_DelayUs(1);

    BK4819_GetRSSI();
    return BK4819_GetRSSI();
}

static void TuneBin(uint32_t f)
{
    if ((f < 28000000u) != (fMeasure < 28000000u))
        BK4819_PickRXFilterPathBasedOnFrequency(f);

    fMeasure = f;
    BK4819_SetFrequency(f);
    BK4819_WriteRegister(BK4819_REG_30, 0);
    BK4819_WriteRegister(BK4819_REG_30, scanReg30);
}

static void SweepStep(void)
{
    TuneBin(fStart + (uint32_t)bin * fStep);

    uint16_t rssi = ReadRssi();
    if (rssi > 511u)
        rssi = 511u;                 // the register is 9 bits; clamp, never wrap
    acc[bin] += linTable[rssi];

    if (++bin < LOG_BINS)
        return;

    bin = 0;
    sweeps++;

    // A sweep has just completed, so every bin holds the same sample count -
    // the only moment a frame may be cut.
    if (framePending && state == LOG_RUNNING)
        EmitFrame();
    else
        redraw = true;
}

// 10^(1/20): one half-dB step in the linear domain.
#define LOG_HALF_DB_RATIO 1.1220185f

static void BuildLinTable(void)
{
    linTable[0] = 1.0f;
    for (uint16_t i = 1; i < ARRAY_SIZE(linTable); i++)
        linTable[i] = linTable[i - 1] * LOG_HALF_DB_RATIO;
}

static void StartScan(void)
{
    fStep = scanStepValues[stepChoices[stepChoice]];
    fStart = gTxVfo->pRX->Frequency - (uint32_t)(LOG_BINS / 2) * fStep;

    bin = 0;
    fMeasure = 0;
    BK4819_PickRXFilterPathBasedOnFrequency(fStart);
    scanReg30 = BK4819_ReadRegister(BK4819_REG_30) & ~(1u << 9);   // never the AF DAC
    BK4819_WriteRegister(BK4819_REG_43, scanStepBWRegValues[stepChoices[stepChoice]]);
    ResetWindow();
}

// --------------------------------------------------------------- display ---

// gFrameBuffer is [7][128] - rows 0..55 - and UI_DrawPixelBuffer range-checks
// nothing. gEeprom is linked immediately after it, so a glyph drawn past the
// bottom ORs bits straight into the settings struct: KEY_LOCK lives at offset
// 0x0C, which is column 12 of the first overflow row. That is exactly how a
// text line at y=54 locked the keypad until a power cycle reloaded the settings
// from EEPROM. A 6-row glyph must therefore start at 50 or less.
#define LOG_TEXT_MAX_Y 50u

static void LogText(const char *text, uint8_t x, uint8_t y)
{
    if (y > LOG_TEXT_MAX_Y)
        return;   // belt and braces: the layout below already fits

    GUI_DisplaySmallest(text, x, y, false, true);
}

static void DrawClockString(char *out, uint32_t seconds)
{
    seconds %= 86400u;
    sprintf(out, "%02u:%02u:%02u", (unsigned)(seconds / 3600u),
            (unsigned)((seconds / 60u) % 60u), (unsigned)(seconds % 60u));
}

static void RenderClockEntry(void)
{
    UI_DisplayClear();

    sprintf(String, "SPECTRUM LOGGER");
    LogText(String, 2, 2);

    sprintf(String, "TIME OF DAY, 6 DIGITS");
    LogText(String, 2, 9);

    for (uint8_t i = 0; i < 6; i++)
        String[i] = (i < clockIndex) ? (char)('0' + clockDigits[i]) : '-';
    String[6] = 0;
    sprintf(String + 8, "%c%c:%c%c:%c%c", String[0], String[1], String[2],
            String[3], String[4], String[5]);
    UI_PrintStringSmall(String + 8, 2, 127, 3);

    const uint32_t span = (uint32_t)LOG_BINS * fStep;
    sprintf(String, "UP/DN SPAN %u.%02uMHZ %ukHz", (unsigned)(span / 100000u),
            (unsigned)((span / 1000u) % 100u), (unsigned)(fStep / 100u));
    LogText(String, 2, 36);

    sprintf(String, "%u FRAMES = %uH%02u", (unsigned)LOG_FRAMES_TOTAL,
            (unsigned)(LOG_FRAMES_TOTAL * LOG_AVG_SECONDS / 3600u),
            (unsigned)((LOG_FRAMES_TOTAL * LOG_AVG_SECONDS / 60u) % 60u));
    LogText(String, 2, 43);

    sprintf(String, "MENU=START  EXIT=QUIT");
    LogText(String, 2, LOG_TEXT_MAX_Y);
}

static void RenderBars(void)
{
    if (sweeps == 0)
        return;

    uint16_t lo = 0xFFFF, hi = 0;

    for (uint16_t i = 0; i < LOG_BINS; i++)
    {
        const uint16_t v = (uint16_t)(acc[i] / sweeps);
        if (v < lo) lo = v;
        if (v > hi) hi = v;
    }

    // Keep at least 10 dB of scale so a quiet band does not turn noise into
    // full-height bars.
    if (hi < lo + 20u)
        hi = lo + 20u;

    const uint8_t height = DrawingEndY - DrawingTopY;

    for (uint16_t i = 0; i < LOG_BINS; i++)
    {
        const uint16_t v = (uint16_t)(acc[i] / sweeps);
        uint8_t px = (uint8_t)(((uint32_t)(v - lo) * height) / (hi - lo));
        if (px > height)
            px = height;

        for (uint8_t y = DrawingEndY - px; y <= DrawingEndY; y++)
            PutPixel(i, y, true);
    }
}

static void RenderRunning(void)
{
    UI_DisplayClear();

    sprintf(String, "%u.%03u", (unsigned)(fStart / 100000u),
            (unsigned)((fStart / 100u) % 1000u));
    LogText(String, 0, 1);

    const uint32_t fEnd = fStart + (uint32_t)(LOG_BINS - 1u) * fStep;
    sprintf(String, "%u.%03u", (unsigned)(fEnd / 100000u),
            (unsigned)((fEnd / 100u) % 1000u));
    LogText(String, 104, 1);

    RenderBars();

    DrawClockString(String, startClock + elapsed);
    LogText(String, 2, 43);

    sprintf(String, "%u/%u", (unsigned)framesWritten, (unsigned)LOG_FRAMES_TOTAL);
    LogText(String, 40, 43);

    sprintf(String, "BLK%u %u%%", (unsigned)block, (unsigned)batteryPercent);
    LogText(String, 92, 43);

    if (state == LOG_FULL)
        sprintf(String, "FULL - STOPPED, EXIT TO END");
    else
        sprintf(String, "REC %us  %u SWEEPS", (unsigned)(LOG_AVG_SECONDS - avgSeconds),
                (unsigned)sweeps);
    LogText(String, 2, 50);
}

static void Render(void)
{
    if (state == LOG_SET_CLOCK)
        RenderClockEntry();
    else
        RenderRunning();
}

// ------------------------------------------------------------------ keys ---

static void StartLogging(void)
{
    startClock = (uint32_t)clockDigits[0] * 36000u + (uint32_t)clockDigits[1] * 3600u +
                 (uint32_t)clockDigits[2] * 600u + (uint32_t)clockDigits[3] * 60u +
                 (uint32_t)clockDigits[4] * 10u + clockDigits[5];
    sessionTag = startClock ^ (0x4B35u << 16) ^ ((uint32_t)fStart << 3);

    elapsed = 0;
    halfSeconds = 0;
    framesWritten = 0;
    block = 0;
    frameInBlock = 0;

    StartScan();
    WriteHeader(false);
    state = LOG_RUNNING;
}

static void HandleKey(KEY_Code_t key)
{
    BACKLIGHT_TurnOn();
    backlightSeconds = 0;
    redraw = true;

    if (state == LOG_SET_CLOCK)
    {
        if (key <= KEY_9)
        {
            if (clockIndex < 6)
                clockDigits[clockIndex++] = (uint8_t)key;
            // Reject an impossible time as it is typed rather than at the end.
            if ((clockIndex == 1 && clockDigits[0] > 2) ||
                (clockIndex == 2 && clockDigits[0] == 2 && clockDigits[1] > 3) ||
                (clockIndex == 3 && clockDigits[2] > 5) ||
                (clockIndex == 5 && clockDigits[4] > 5))
                clockIndex--;
            return;
        }

        switch (key)
        {
        case KEY_EXIT:
            if (clockIndex)
                clockIndex--;
            else
                running = false;
            return;
        case KEY_MENU:
            if (clockIndex == 6)
                StartLogging();
            return;
        case KEY_UP:
            if (stepChoice + 1u < ARRAY_SIZE(stepChoices))
                stepChoice++;
            fStep = scanStepValues[stepChoices[stepChoice]];
            return;
        case KEY_DOWN:
            if (stepChoice)
                stepChoice--;
            fStep = scanStepValues[stepChoices[stepChoice]];
            return;
        default:
            return;
        }
    }

    if (key == KEY_EXIT)
    {
        // Close the session so the reader can tell a finished log from one cut
        // short by a flat battery.
        WriteHeader(true);
        running = false;
    }
}

static void CheckBattery(void)
{
    BOARD_ADC_GetBatteryInfo(&gBatteryVoltages[gBatteryCheckCounter++ % 4],
                             &gBatteryCurrent);

    const uint16_t voltage = (gBatteryVoltages[0] + gBatteryVoltages[1] +
                              gBatteryVoltages[2] + gBatteryVoltages[3]) /
                             4 * 760 / gBatteryCalibration[3];
    batteryPercent = BATTERY_VoltsToPercent(voltage);

    if (state == LOG_RUNNING && batteryPercent < LOG_BATTERY_STOP_PERCENT)
    {
        // Stop logging rather than let the pack die mid-write, and hand back to
        // the main app, whose own low-battery handling then takes over.
        WriteHeader(true);
        state = LOG_FULL;
        running = false;
    }
}

// ------------------------------------------------------------------ tick ---

static void Tick(void)
{
    if (gNextTimeslice_500ms)
    {
        gNextTimeslice_500ms = false;

        if (++halfSeconds >= 2)
        {
            halfSeconds = 0;

            if (state == LOG_RUNNING)
            {
                elapsed++;
                if (++avgSeconds >= LOG_AVG_SECONDS)
                    framePending = true;   // taken at the next sweep boundary
            }

            // An unattended logger should not sit lit for hours.
            if (backlightSeconds < 255 && ++backlightSeconds == 20)
                BACKLIGHT_TurnOff();

            if ((elapsed % 10u) == 0)
                CheckBattery();

            redraw = true;
        }
    }

#ifdef ENABLE_UART
    // Serviced here too, so a session can be dumped over the cable without
    // stopping the log.
    if (UART_IsCommandAvailable())
        UART_HandleCommand();
#endif

    // Keys are sampled on the 10 ms timeslice, not every loop pass: the loop
    // runs a whole sweep step while logging and nothing at all while the clock
    // is being typed, so a per-pass poll would debounce differently in each
    // state. Two equal samples, then one action per press - no auto-repeat.
    if (gNextTimeslice)
    {
        gNextTimeslice = false;

        const KEY_Code_t key = GetKey();
        if (key != lastKey)
        {
            lastKey = key;
            keySettled = 0;
        }
        else if (key != KEY_INVALID && ++keySettled == 2)
        {
            HandleKey(key);
        }

        // Paced off the same 10 ms tick, or the clock-entry screen - which has
        // no sweep to slow it down - would spin the SPI bus flat out pushing
        // an unchanged frame.
        ST7565_BlitLine(renderPage);
        if (++renderPage >= FRAME_LINES)
            renderPage = 0;
    }

    if (state == LOG_RUNNING)
        SweepStep();

    if (redraw)
    {
        Render();
        redraw = false;
    }
}

// ----------------------------------------------------------------- entry ---

void APP_RunSpectrumLogger(void)
{
    for (uint32_t i = 0; i < ARRAY_SIZE(registers_to_save); i++)
        registers_stack[i] = BK4819_ReadRegister(registers_to_save[i]);

    RADIO_SetModulation(MODULATION_FM);
    BK4819_SetFilterBandwidth(BK4819_FILTER_BW_WIDE, false);
    RADIO_SetupAGC(false, false);
    BK4819_ToggleGpioOut(BK4819_GPIO6_PIN2_GREEN, false);

    BuildLinTable();

    lastKey = KEY_INVALID;   // statics: a previous session left its exit key here
    keySettled = 0;

    state = LOG_SET_CLOCK;
    clockIndex = 0;
    running = true;
    redraw = true;
    backlightSeconds = 0;
    fStep = scanStepValues[stepChoices[stepChoice]];
    BACKLIGHT_TurnOn();

    memset(gStatusLine, 0, sizeof(gStatusLine));
    ST7565_BlitStatusLine();

    while (running)
        Tick();

    for (uint32_t i = 0; i < ARRAY_SIZE(registers_to_save); i++)
        BK4819_WriteRegister(registers_to_save[i], registers_stack[i]);

    // This app is entered from inside the main app's own key handler and left
    // with the EXIT key still physically down. CheckKeys() resumes on a key it
    // never saw pressed, and replays it as a fresh press and then a hold, into
    // whatever screen comes back - so wait for the keypad to be quiet first.
    // Bounded, because a stuck key must not trap the radio in here.
    uint8_t quiet = 0;
    uint16_t guard = 300;   // 3 s at 10 ms
    while (quiet < 3 && guard)
    {
        if (gNextTimeslice)
        {
            gNextTimeslice = false;
            guard--;
            quiet = (GetKey() == KEY_INVALID) ? quiet + 1 : 0;
        }
    }
    lastKey = KEY_INVALID;
    keySettled = 0;

    // Anything half-typed before this app took the screen is hours stale, and
    // a non-zero gInputBoxIndex makes GENERIC_Key_F ignore the F key outright -
    // which would leave a locked keypad with no way to unlock it.
    gInputBoxIndex = 0;

    gVfoConfigureMode = VFO_CONFIGURE;
    BACKLIGHT_TurnOn();
}
