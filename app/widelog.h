/* Wide spectrum logger - 204.8 MHz in one sweep, an hour a frame.
 *
 * A separate app from app/speclog.c, not a mode of it: that logger keeps its
 * 128 bins, its selectable step and its own store format, untouched. This one
 * trades all time resolution for coverage.
 *
 * The two share the EEPROM store but not its layout, so each reads the header
 * on entry and offers to reformat when it finds the other's. The format is
 * described in app/widelog.c; k5logdump.py reads both.
 */

#ifndef WIDELOG_H
#define WIDELOG_H

#include <stdint.h>

#define WIDE_BINS            8192u      // 8192 x 25 kHz = 204.8 MHz
#define WIDE_STEP            2500u      // 10 Hz units
#define WIDE_WINDOW          3600u      // seconds per frame
#define WIDE_FLOOR           3000000u   // never sweep below 30 MHz (10 Hz units)

// Store: header, then a stamp per frame, then the frames packed back to back.
// 245,760 / 8,192 = 30 frames with nothing wasted, which is why the bin count
// is a power of two.
#define WIDE_HEADER_ADDR     0x03000u
#define WIDE_HEADER_BYTES    128u
#define WIDE_STAMP_BASE      0x03080u
#define WIDE_STAMP_BYTES     32u
#define WIDE_FRAME_BASE      0x04000u
#define WIDE_FRAMES          ((0x40000u - WIDE_FRAME_BASE) / WIDE_BINS)   // 30
#define WIDE_VERSION         7u

// Same ladder as the narrow logger: one byte per bin, 1 dB steps, dBm + 185.
#define WIDE_DBM_BASE        (-185)
#define WIDE_DBM_STEP        1
#define WIDE_LEVELS          256
#define WIDE_RSSI_DBM_OFFSET (-160)

void APP_RunSpectrumWide(void);

#endif
