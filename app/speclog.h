/* Spectrum logger - unattended band-occupancy recorder.
 *
 * The on-EEPROM format is described in app/speclog.c; k5logdump.py reads it.
 */

#ifndef SPECLOG_H
#define SPECLOG_H

#include <stdint.h>

// Log store. All three regions are inside EEPROM space that this build does
// not use: 0x04000-0x1C000 and 0x20000-0x28000 are the holes left by the
// Chinese font and pinyin tables (see CLAUDE.md, "Free space"), and the header
// sits below the first of them. Nothing here reaches 0x40000, where the custom
// bootloader keeps its multi-boot table.
#define LOG_HEADER_ADDR      0x03000u

// One contiguous run of blocks, ending exactly at the top of a 2 Mbit part.
// Nothing in the firmware reads any EEPROM address at or above 0x2000 (doppler's
// 0x02BA0/0x1E200 and the bootloader's 0x41000 are the only higher constants in
// the tree, and both are compiled out), so the store needs no holes. It used to
// stop at 0x3C000 to spare the SI4732 SSB patch at 0x3C228; with the chip
// removed there is nothing left to avoid.
#define LOG_BLOCK_BASE       0x04000u
#define LOG_BLOCKS_TOTAL     15u                   // 0x04000-0x40000, the whole chip
#define LOG_STAMP            128u                  // header record, and each block's first record
#define LOG_BLOCK            (LOG_STAMP * 128u)    // 16 KiB, the header-update unit
#define LOG_BINS             128u
#define LOG_BIN_BITS         8u                    // one byte per bin
#define LOG_FRAME_BYTES      (LOG_BINS * LOG_BIN_BITS / 8u)          // 128
#define LOG_FRAMES_PER_BLOCK ((LOG_BLOCK - LOG_STAMP) / LOG_FRAME_BYTES)  // 127
#define LOG_AVG_SECONDS      30u

// Level encoding: 256 steps of 1 dB, so a stored level is an absolute dBm and
// the reader calibrates nothing.
//
// The base is -185 because that is the lowest reading the radio can produce:
// RSSI 0 is -160 dBm before the band correction, and dBmCorrTable bottoms out
// at -25. Nothing can rail at the bottom, and the top, +70 dBm, is far past
// what the front end survives - so in practice neither end clips.
//
// 4 bits at 8 dB was tried, to double the session. It fits the data on paper
// and looks flat in practice: two hours of it read as dull steps, because a
// band's interesting range is 30-40 dB and 8 dB quantises that to four or five
// values. A byte a bin costs half the session and is worth it.
#define LOG_DBM_BASE         (-185)
#define LOG_DBM_STEP         1
#define LOG_LEVELS           256                   // 2^LOG_BIN_BITS
#define LOG_RSSI_DBM_OFFSET  (-160)                // dBm = rssi/2 + this + band correction

void APP_RunSpectrumLogger(void);

#endif
