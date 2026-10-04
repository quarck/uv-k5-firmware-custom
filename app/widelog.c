/* Wide spectrum logger - F+7.
 *
 * Sweeps 8192 bins of 25 kHz - 204.8 MHz - and every hour writes the strongest
 * reading each bin saw in that hour. 30 frames fill the store exactly, so a
 * session is 30 hours. Peak only: a linear-power accumulator needs a uint64 a
 * bin, which at 8192 bins would be the whole SRAM.
 *
 * Deliberately a separate app from app/speclog.c rather than a mode of it. The
 * narrow logger keeps its 128 bins, its selectable step and its 30 s frames,
 * and nothing here touches it. The two share the EEPROM store but not its
 * layout: each reads the header on entry and offers to reformat when the
 * version is not its own.
 *
 * EEPROM format, all little-endian (k5logdump.py is the reader):
 *
 *   Header, 128 B at WIDE_HEADER_ADDR
 *     0x00  4  magic "K5SL"
 *     0x04  1  format version (7 - the wide layout; 6 is the narrow logger's)
 *     0x05  2  bins (8192; a uint16, because it never fit the byte v6 used)
 *     0x07  1  flags: bit 0 = closed cleanly, bit 1 = peaks (always set here)
 *     0x08  4  frequency of bin 0, 10 Hz units
 *     0x0C  4  bin spacing, 10 Hz units
 *     0x10  2  seconds per frame
 *     0x12  2  frames the store holds
 *     0x14  1  frames per stamp (1)
 *     0x16  1  band correction at bin 0, int8 - informational only, see below
 *     0x18  4  wall clock at the first frame, seconds since midnight
 *     0x1C  4  session tag
 *     0x20  4  frames written     <-- the only fields rewritten in flight,
 *     0x24  4  seconds logged     <-- one aligned 8-byte write per frame
 *     0x28  2  dBm of a zero byte (int16, -185)
 *     0x2A  1  dB per level (1)
 *     0x2B  1  bits per bin (8)
 *     0x2C  4  frame area base
 *     0x30  4  stamp table base
 *
 *   Stamp, 32 B each from WIDE_STAMP_BASE, one per frame
 *     0x00  4  magic "K5LB"
 *     0x04  2  stamp index
 *     0x08  4  wall clock at its frame
 *     0x0C  4  seconds since the session started
 *     0x10  4  the frame it belongs to
 *
 *   Frame, 8192 B from WIDE_FRAME_BASE: one byte per bin, byte = dBm + 185.
 *
 * The band correction is applied PER BIN, not once per frame. dBmCorrTable runs
 * -25..-1 and a 30-235 MHz sweep crosses four of the radio's bands; the same
 * raw reading quantises 21 dB apart between band 2 and band 4, so a single
 * per-frame correction would put most of a sweep out by that much. The header's
 * copy at 0x16 is only a note of what bin 0 used.
 */

#include "app/widelog.h"

#include "app/spectrum.h"   // scan step tables, DrawingTopY/DrawingEndY
#include "driver/backlight.h"
#include "driver/bk4819.h"
#include "driver/eeprom.h"
#include "driver/keyboard.h"
#include "driver/st7565.h"
#include "driver/system.h"
#include "driver/systick.h"
#include "external/printf/printf.h"
#include "frequencies.h"
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

typedef enum
{
    WIDE_START,      // what is stored, and what to do about it
    WIDE_SET_CLOCK,
    WIDE_RUNNING,
    WIDE_FULL,
} WideState;

static WideState state;
static bool      running;

// Sweep
static uint32_t fStart;
static uint32_t fMeasure;
static uint16_t scanReg30;
static uint16_t bin;
static uint16_t sweeps;
static bool     framePending;

// The hour's strongest reading per bin, already quantised, so a frame is a
// straight copy of this and nothing is converted at write time.
static uint8_t  peak[WIDE_BINS];

// Clock and position
static uint32_t startClock;
static uint32_t elapsed;
static uint16_t windowSeconds;
static uint8_t  halfSeconds;
static uint32_t sessionTag;
static uint16_t framesWritten;

// What is already in the store
static bool     haveStored;
static bool     storedMine;      // written by this logger, not the narrow one
static bool     storedClosed;
static uint32_t storedClock;
static uint32_t storedFrames;
static bool     wipeArmed;

static uint8_t  clockDigits[6];
static uint8_t  clockIndex;

#define WIDE_BATTERY_STOP 5
#define WIDE_BATTERY_LOW  20
static uint8_t  batteryPercent = 100;
static uint16_t batteryVoltage;
static bool     statusDirty = true;
static uint8_t  batterySeconds;
static uint8_t  backlightSeconds;

static KEY_Code_t lastKey = KEY_INVALID;
static uint8_t    keySettled;

static char     String[32];
static bool     redraw = true;
static uint8_t  renderPage;

static const BK4819_REGISTER_t regsToSave[] = {
    BK4819_REG_30, BK4819_REG_37, BK4819_REG_3D, BK4819_REG_43,
    BK4819_REG_47, BK4819_REG_48, BK4819_REG_7E,
};
static uint16_t regsStack[ARRAY_SIZE(regsToSave)];

// gFrameBuffer is [7][128] - rows 0..55 - and UI_DrawPixelBuffer checks
// nothing, with gEeprom linked straight after it. A 6-row glyph must start at
// 50 or less (CLAUDE.md, "Traps").
#define WIDE_TEXT_MAX_Y 50u

static void Text(const char *s, uint8_t x, uint8_t y)
{
    if (y <= WIDE_TEXT_MAX_Y)
        GUI_DisplaySmallest(s, x, y, false, true);
}

static void Clock(char *out, uint32_t seconds)
{
    seconds %= 86400u;
    sprintf(out, "%02u:%02u:%02u", (unsigned)(seconds / 3600u),
            (unsigned)((seconds / 60u) % 60u), (unsigned)(seconds % 60u));
}

// ---------------------------------------------------------------- EEPROM ---

static void Write(uint32_t addr, const void *data, uint16_t size)
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

static void ReadStored(void)
{
    uint8_t h[40];

    EEPROM_ReadBuffer(WIDE_HEADER_ADDR, h, sizeof(h));
    haveStored = (memcmp(h, "K5SL", 4) == 0);
    storedMine = haveStored && h[0x04] == WIDE_VERSION &&
                 (uint16_t)(h[0x05] | (h[0x06] << 8)) == WIDE_BINS;
    storedClosed = haveStored && (h[0x07] & 1u);
    memcpy(&storedClock, &h[0x18], 4);
    memcpy(&storedFrames, &h[0x20], 4);
}

// Zero the header and the stamps. 40 page writes instead of 240 KiB: with no
// header the store reads as empty and with no stamps the frames carry no time.
// It is also how this logger reformats a store the narrow one wrote.
static void WipeStore(void)
{
    const uint8_t zero[8] = {0};

    for (uint16_t i = 0; i < WIDE_HEADER_BYTES; i += 8)
        EEPROM_WriteBuffer(WIDE_HEADER_ADDR + i, zero, 8);

    for (uint16_t i = 0; i < WIDE_FRAMES * WIDE_STAMP_BYTES; i += 8)
        EEPROM_WriteBuffer(WIDE_STAMP_BASE + i, zero, 8);

    haveStored = false;
    storedMine = false;
}

static void WriteHeader(bool closed)
{
    uint8_t h[WIDE_HEADER_BYTES];
    const uint32_t step = WIDE_STEP, frameBase = WIDE_FRAME_BASE;
    const uint32_t stampBase = WIDE_STAMP_BASE;
    const uint16_t window = WIDE_WINDOW, frames = WIDE_FRAMES;
    const int16_t  dbmBase = WIDE_DBM_BASE;

    memset(h, 0, sizeof(h));
    memcpy(h, "K5SL", 4);
    h[0x04] = WIDE_VERSION;
    h[0x05] = (uint8_t)(WIDE_BINS & 0xFFu);
    h[0x06] = (uint8_t)(WIDE_BINS >> 8);
    h[0x07] = (closed ? 1u : 0u) | 2u;        // always peaks
    memcpy(&h[0x08], &fStart, 4);
    memcpy(&h[0x0C], &step, 4);
    memcpy(&h[0x10], &window, 2);
    memcpy(&h[0x12], &frames, 2);
    h[0x14] = 1;                              // a stamp per frame
    h[0x16] = (uint8_t)dBmCorrTable[FREQUENCY_GetBand(fStart)];
    memcpy(&h[0x18], &startClock, 4);
    memcpy(&h[0x1C], &sessionTag, 4);
    memcpy(&h[0x20], &framesWritten, 4);
    memcpy(&h[0x24], &elapsed, 4);
    memcpy(&h[0x28], &dbmBase, 2);
    h[0x2A] = WIDE_DBM_STEP;
    h[0x2B] = 8;
    memcpy(&h[0x2C], &frameBase, 4);
    memcpy(&h[0x30], &stampBase, 4);

    Write(WIDE_HEADER_ADDR, h, sizeof(h));
}

static void UpdateCounters(void)
{
    uint8_t c[8];
    const uint32_t frames = framesWritten;

    memcpy(&c[0], &frames, 4);
    memcpy(&c[4], &elapsed, 4);
    Write(WIDE_HEADER_ADDR + 0x20, c, sizeof(c));
}

static void WriteStamp(void)
{
    uint8_t st[WIDE_STAMP_BYTES];
    const uint32_t wall = startClock + elapsed, frame = framesWritten;
    const uint16_t idx = framesWritten;

    memset(st, 0, sizeof(st));
    memcpy(st, "K5LB", 4);
    memcpy(&st[0x04], &idx, 2);
    memcpy(&st[0x08], &wall, 4);
    memcpy(&st[0x0C], &elapsed, 4);
    memcpy(&st[0x10], &frame, 4);

    Write(WIDE_STAMP_BASE + (uint32_t)idx * WIDE_STAMP_BYTES, st, sizeof(st));
}

// ------------------------------------------------------------------ sweep ---

// Half-dB RSSI to a stored byte, with the correction for THIS bin's band.
// FREQUENCY_GetBand walks seven entries - about 1 us against the 118 us a bin
// already costs - and always returns 0..6, so the table index is safe.
static uint8_t Quantise(uint16_t halfDb, uint32_t f)
{
    const int32_t bias = 2 * (int32_t)dBmCorrTable[FREQUENCY_GetBand(f)] +
                         2 * (WIDE_RSSI_DBM_OFFSET - WIDE_DBM_BASE);
    int32_t level = ((int32_t)halfDb + bias + WIDE_DBM_STEP) / (2 * WIDE_DBM_STEP);

    if (level < 0)
        level = 0;
    else if (level > WIDE_LEVELS - 1)
        level = WIDE_LEVELS - 1;

    return (uint8_t)level;
}

static uint16_t ReadRssi(void)
{
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

static void ResetWindow(void)
{
    memset(peak, 0, sizeof(peak));
    sweeps = 0;
    windowSeconds = 0;
    framePending = false;
}

static void EmitFrame(void)
{
    // 8192 bytes is 1,024 page writes, about 10 s with the sweep stopped. Say
    // so, or it reads as a hang.
    sprintf(String, "WRITING FRAME %u", (unsigned)(framesWritten + 1u));
    Text(String, 2, 50);
    ST7565_BlitFullScreen();

    WriteStamp();
    Write(WIDE_FRAME_BASE + (uint32_t)framesWritten * WIDE_BINS, peak, WIDE_BINS);
    framesWritten++;
    UpdateCounters();

    if (framesWritten >= WIDE_FRAMES)
    {
        state = WIDE_FULL;
        WriteHeader(true);
    }

    ResetWindow();
    redraw = true;
}

static void SweepStep(void)
{
    const uint32_t f = fStart + (uint32_t)bin * WIDE_STEP;
    uint8_t level;

    TuneBin(f);
    level = Quantise(ReadRssi(), f);
    if (level > peak[bin])
        peak[bin] = level;

    if (++bin < WIDE_BINS)
        return;

    bin = 0;
    sweeps++;

    // Cut a frame only at a sweep boundary, so every bin has had the same
    // number of looks.
    if (framePending && state == WIDE_RUNNING)
        EmitFrame();
    else
        redraw = true;
}

static void StartScan(void)
{
    // Centred on the VFO, but never below 30 MHz: under that the front end has
    // nothing useful to say, and a 204.8 MHz sweep from a 2 m VFO would
    // otherwise start in the HF noise.
    fStart = gTxVfo->pRX->Frequency - (uint32_t)WIDE_BINS * WIDE_STEP / 2u;
    if (fStart < WIDE_FLOOR)
        fStart = WIDE_FLOOR;

    bin = 0;
    fMeasure = 0;
    BK4819_PickRXFilterPathBasedOnFrequency(fStart);
    scanReg30 = BK4819_ReadRegister(BK4819_REG_30) & ~(1u << 9);
    BK4819_WriteRegister(BK4819_REG_43, scanStepBWRegValues[S_STEP_25_0kHz]);
    ResetWindow();
}

// --------------------------------------------------------------- display ---

static void RenderStart(void)
{
    UI_DisplayClear();

    sprintf(String, "WIDE LOGGER  204.8MHZ");
    Text(String, 2, 2);

    if (!haveStored)
    {
        sprintf(String, "STORE EMPTY");
        Text(String, 2, 12);
    }
    else if (storedMine)
    {
        sprintf(String, "HELD %u FRAMES  %uH", (unsigned)storedFrames,
                (unsigned)storedFrames);
        Text(String, 2, 12);
        Clock(String, storedClock);
        Text(String, 2, 19);
        sprintf(String, "%s", storedClosed ? "CLOSED" : "CUT SHORT");
        Text(String, 40, 19);
    }
    else
    {
        sprintf(String, "HELD: NARROW FORMAT");
        Text(String, 2, 12);
        sprintf(String, "REFORMAT TO USE IT HERE");
        Text(String, 2, 19);
    }

    sprintf(String, "MENU  RECORD %uH", (unsigned)WIDE_FRAMES);
    Text(String, 2, 33);

    sprintf(String, wipeArmed ? "7     AGAIN TO WIPE"
                              : (haveStored && !storedMine) ? "7     REFORMAT STORE"
                                                            : "7     WIPE THE STORE");
    Text(String, 2, 40);

    sprintf(String, "EXIT  QUIT");
    Text(String, 2, 47);
}

static void RenderClockEntry(void)
{
    UI_DisplayClear();

    sprintf(String, "WIDE LOGGER");
    Text(String, 2, 2);

    sprintf(String, "TIME OF DAY, 6 DIGITS");
    Text(String, 2, 9);

    for (uint8_t i = 0; i < 6; i++)
        String[i] = (i < clockIndex) ? (char)('0' + clockDigits[i]) : '-';
    String[6] = 0;
    sprintf(String + 8, "%c%c:%c%c:%c%c", String[0], String[1], String[2],
            String[3], String[4], String[5]);
    UI_PrintStringSmall(String + 8, 2, 127, 3);

    sprintf(String, "%u.%01u-%u.%01uMHZ 25kHz",
            (unsigned)(fStart / 100000u), (unsigned)((fStart / 10000u) % 10u),
            (unsigned)((fStart + (uint32_t)WIDE_BINS * WIDE_STEP) / 100000u),
            (unsigned)(((fStart + (uint32_t)WIDE_BINS * WIDE_STEP) / 10000u) % 10u));
    Text(String, 2, 36);

    sprintf(String, "%u FRAMES = %uH, 1H EACH", (unsigned)WIDE_FRAMES,
            (unsigned)WIDE_FRAMES);
    Text(String, 2, 43);

    sprintf(String, "MENU=START  EXIT=QUIT");
    Text(String, 2, WIDE_TEXT_MAX_Y);
}

static void RenderBars(void)
{
    uint8_t lo = 255, hi = 0;

    if (sweeps == 0)
        return;

    for (uint16_t i = 0; i < WIDE_BINS; i++)
    {
        if (peak[i] < lo) lo = peak[i];
        if (peak[i] > hi) hi = peak[i];
    }
    if (hi < lo + 10u)
        hi = (uint8_t)(lo + 10u);

    // The screen is 128 px wide, so each column is the strongest of 64 bins.
    const uint8_t height = DrawingEndY - DrawingTopY;

    for (uint8_t x = 0; x < 128u; x++)
    {
        uint8_t v = 0;

        for (uint16_t k = 0; k < WIDE_BINS / 128u; k++)
        {
            const uint8_t t = peak[(uint16_t)x * (WIDE_BINS / 128u) + k];
            if (t > v)
                v = t;
        }

        uint8_t px = (uint8_t)(((uint32_t)(v - lo) * height) / (hi - lo));
        if (px > height)
            px = height;

        for (uint8_t y = DrawingEndY - px; y <= DrawingEndY; y++)
            PutPixel(x, y, true);
    }
}

static void RenderRunning(void)
{
    UI_DisplayClear();

    sprintf(String, "%u", (unsigned)(fStart / 100000u));
    Text(String, 0, 1);
    sprintf(String, "%u", (unsigned)((fStart + (uint32_t)WIDE_BINS * WIDE_STEP)
                                     / 100000u));
    Text(String, 112, 1);

    RenderBars();

    Clock(String, startClock + elapsed);
    Text(String, 2, 43);

    sprintf(String, "%u/%u", (unsigned)framesWritten, (unsigned)WIDE_FRAMES);
    Text(String, 52, 43);

    sprintf(String, "%u%%", (unsigned)batteryPercent);
    Text(String, 108, 43);

    if (state == WIDE_FULL)
        sprintf(String, "FULL - STOPPED, EXIT");
    else
        sprintf(String, "REC %um  %u SWEEPS",
                (unsigned)((WIDE_WINDOW - windowSeconds + 59u) / 60u),
                (unsigned)sweeps);
    Text(String, 2, 50);
}

static void RenderStatus(void)
{
    memset(gStatusLine, 0, sizeof(gStatusLine));

    sprintf(String, "WIDE %u.%02uV %u%%%s",
            (unsigned)(batteryVoltage / 100), (unsigned)(batteryVoltage % 100),
            (unsigned)batteryPercent,
            (batteryPercent < WIDE_BATTERY_LOW) ? " LOW" : "");
    GUI_DisplaySmallest(String, 2, 1, true, true);

    gStatusLine[116] = 0b00011100;
    gStatusLine[117] = 0b00111110;
    for (uint8_t i = 118; i <= 126; i++)
        gStatusLine[i] = 0b00100010;
    for (uint8_t i = 127; i >= 118; i--)
        if (127u - i <= ((unsigned)batteryPercent + 5u) * 9u / 100u)
            gStatusLine[i] = 0b00111110;

    ST7565_BlitStatusLine();
    statusDirty = false;
}

static void Render(void)
{
    if (state == WIDE_START)
        RenderStart();
    else if (state == WIDE_SET_CLOCK)
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
    sessionTag = startClock ^ (0x5744u << 16) ^ (fStart << 3);

    elapsed = 0;
    halfSeconds = 0;
    framesWritten = 0;

    StartScan();
    WriteHeader(false);
    state = WIDE_RUNNING;
}

static void HandleKey(KEY_Code_t key)
{
    BACKLIGHT_TurnOn();
    backlightSeconds = 0;
    redraw = true;

    if (state == WIDE_START)
    {
        switch (key)
        {
        case KEY_MENU:
            state = WIDE_SET_CLOCK;
            clockIndex = 0;
            break;
        case KEY_7:
            if (wipeArmed)
                WipeStore();
            wipeArmed = !wipeArmed;
            break;
        case KEY_EXIT:
            running = false;
            break;
        default:
            wipeArmed = false;
            break;
        }
        return;
    }

    if (state == WIDE_SET_CLOCK)
    {
        if (key <= KEY_9)
        {
            if (clockIndex < 6)
                clockDigits[clockIndex++] = (uint8_t)key;
            // Reject an impossible time as it is typed, not at the end.
            if ((clockIndex == 1 && clockDigits[0] > 2) ||
                (clockIndex == 2 && clockDigits[0] == 2 && clockDigits[1] > 3) ||
                (clockIndex == 3 && clockDigits[2] > 5) ||
                (clockIndex == 5 && clockDigits[4] > 5))
                clockIndex--;
            return;
        }
        if (key == KEY_EXIT)
        {
            if (clockIndex)
                clockIndex--;
            else
                state = WIDE_START;
            return;
        }
        if (key == KEY_MENU && clockIndex == 6)
            StartLogging();
        return;
    }

    if (key == KEY_EXIT)
    {
        WriteHeader(true);   // so the reader can tell finished from cut short
        running = false;
    }
}

static void CheckBattery(void)
{
    BOARD_ADC_GetBatteryInfo(&gBatteryVoltages[gBatteryCheckCounter++ % 4],
                             &gBatteryCurrent);

    batteryVoltage = (gBatteryVoltages[0] + gBatteryVoltages[1] +
                      gBatteryVoltages[2] + gBatteryVoltages[3]) /
                     4 * 760 / gBatteryCalibration[3];
    batteryPercent = BATTERY_VoltsToPercent(batteryVoltage);
    statusDirty = true;

    // elapsed > 0 keeps the very first sample from closing the app the instant
    // it opens on a low pack.
    if (state == WIDE_RUNNING && elapsed > 0 && batteryPercent < WIDE_BATTERY_STOP)
    {
        WriteHeader(true);
        state = WIDE_FULL;
        running = false;
    }
}

static void Tick(void)
{
    if (gNextTimeslice_500ms)
    {
        gNextTimeslice_500ms = false;

        if (++halfSeconds >= 2)
        {
            halfSeconds = 0;

            if (state == WIDE_RUNNING)
            {
                elapsed++;
                if (++windowSeconds >= WIDE_WINDOW)
                    framePending = true;   // cut at the next sweep boundary
            }

            if (backlightSeconds < 255 && ++backlightSeconds == 20)
                BACKLIGHT_TurnOff();

            if (++batterySeconds >= 10)
            {
                batterySeconds = 0;
                CheckBattery();
            }

            redraw = true;
        }
    }

#ifdef ENABLE_UART
    if (UART_IsCommandAvailable())
        UART_HandleCommand();
#endif

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

        ST7565_BlitLine(renderPage);
        if (++renderPage >= FRAME_LINES)
            renderPage = 0;
    }

    if (state == WIDE_RUNNING)
        SweepStep();

    if (statusDirty)
        RenderStatus();

    if (redraw)
    {
        Render();
        redraw = false;
    }
}

// ----------------------------------------------------------------- entry ---

void APP_RunSpectrumWide(void)
{
    for (uint32_t i = 0; i < ARRAY_SIZE(regsToSave); i++)
        regsStack[i] = BK4819_ReadRegister(regsToSave[i]);

    RADIO_SetModulation(MODULATION_FM);
    BK4819_SetFilterBandwidth(BK4819_FILTER_BW_WIDE, false);
    RADIO_SetupAGC(false, false);
    BK4819_ToggleGpioOut(BK4819_GPIO6_PIN2_GREEN, false);

    lastKey = KEY_INVALID;
    keySettled = 0;
    wipeArmed = false;
    running = true;
    redraw = true;
    backlightSeconds = 0;

    // The plan is shown on the entry screens, so work it out before the first
    // draw even though recording has not started.
    fStart = gTxVfo->pRX->Frequency - (uint32_t)WIDE_BINS * WIDE_STEP / 2u;
    if (fStart < WIDE_FLOOR)
        fStart = WIDE_FLOOR;

    ReadStored();
    state = WIDE_START;
    clockIndex = 0;

    batterySeconds = 0;
    CheckBattery();
    RenderStatus();

    while (running)
        Tick();

    for (uint32_t i = 0; i < ARRAY_SIZE(regsToSave); i++)
        BK4819_WriteRegister(regsToSave[i], regsStack[i]);

    gInputBoxIndex = 0;
    gVfoConfigureMode = VFO_CONFIGURE;
    BACKLIGHT_TurnOn();
}
