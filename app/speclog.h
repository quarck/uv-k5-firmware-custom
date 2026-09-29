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
#define LOG_BIN_BITS         4u                    // two bins to a byte
#define LOG_FRAME_BYTES      (LOG_BINS * LOG_BIN_BITS / 8u)          // 64
#define LOG_FRAMES_PER_BLOCK ((LOG_BLOCK - LOG_STAMP) / LOG_FRAME_BYTES)  // 254
#define LOG_AVG_SECONDS      30u

// Level encoding: 16 steps of 8 dB, -132 to -12 dBm. A stored level is an
// absolute dBm and the reader calibrates nothing.
//
// 4 bits doubles the session, and 8 dB is coarse but enough to see occupancy.
// The base is -132 rather than the -128 the range suggests, for a measured
// reason: two real logs from this radio run -128..-68 dBm, and their noise
// floors sit 5 dB apart (-126 in one, -121 in the other). With the base at -128,
// 96% of the quieter log's samples round onto level 0 and its floor becomes
// unmeasurable - the same rail that made a 5 dB ladder useless on UHF. Four dB
// lower puts that floor on level 1 (0.2% on the rail) and still leaves the top
// at -12 dBm, far above the -68 dBm peak either log has seen.
#define LOG_DBM_BASE         (-132)
#define LOG_DBM_STEP         8
#define LOG_LEVELS           16                    // 2^LOG_BIN_BITS
#define LOG_RSSI_DBM_OFFSET  (-160)                // dBm = rssi/2 + this + band correction

void APP_RunSpectrumLogger(void);

#endif
