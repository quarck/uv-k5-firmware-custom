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

// One contiguous run of blocks. In this build nothing in the firmware reads
// any EEPROM address at or above 0x2000 (doppler's 0x02BA0/0x1E200 and the
// bootloader's 0x41000 are the only higher constants in the tree, and both are
// compiled out), so the store needs no holes. It stops at 0x3C000 to leave the
// SI4732 SSB patch at 0x3C228 alone - this build does not need it, but the
// normal firmware does, and a missing patch fails silently.
#define LOG_BLOCK_BASE       0x04000u
#define LOG_BLOCKS_TOTAL     14u                   // 0x04000-0x3C000
#define LOG_STAMP            128u                  // header record, and each block's first record
#define LOG_BLOCK            (LOG_STAMP * 128u)    // 16 KiB, the header-update unit
#define LOG_BINS             128u
#define LOG_BIN_BITS         8u                    // one byte per bin
#define LOG_FRAME_BYTES      (LOG_BINS * LOG_BIN_BITS / 8u)          // 128
#define LOG_FRAMES_PER_BLOCK ((LOG_BLOCK - LOG_STAMP) / LOG_FRAME_BYTES)  // 127
#define LOG_AVG_SECONDS      30u

// Level encoding: 256 steps of 1 dB, so a stored level is an absolute dBm and
// the reader needs no calibration of its own.
//
// The base is -185 because that is the lowest reading the radio can produce:
// RSSI 0 is -160 dBm before the band correction, and dBmCorrTable bottoms out
// at -25. Nothing can therefore rail at the bottom - which a 16-level ladder
// from -130 did, with 74% of a UHF sweep sitting on the bottom rail and the
// noise floor unmeasurable. The top, +70 dBm, is far past anything the front
// end survives, so in practice neither end clips.
#define LOG_DBM_BASE         (-185)
#define LOG_DBM_STEP         1
#define LOG_LEVELS           256                   // 2^LOG_BIN_BITS
#define LOG_RSSI_DBM_OFFSET  (-160)                // dBm = rssi/2 + this + band correction

// Live stream (F+7). Same sweep and the same averaging as the recorder, but the
// window is shorter and each frame goes straight out of the UART instead of
// into EEPROM, so nothing is stored and the session is as long as you like.
// k5stream.py is the reader.
//
// One packet per window, little-endian, 152 bytes:
//
//   0   2  magic "K5"
//   2   1  stream format version (1)
//   3   1  bins (128)
//   4   2  sequence, wraps at 65536 - a gap means frames were lost
//   6   4  seconds since the app started
//  10   4  frequency of bin 0, 10 Hz units
//  14   2  bin spacing, 10 Hz units
//  16   2  sweeps averaged into this frame
//  18   2  dBm of a zero byte (int16, -185)
//  20   1  dB per step (1)
//  21   1  band correction already applied (int8, informational)
//  22 128  one byte per bin, byte = dBm - the value at offset 18
// 150   2  CRC-16/XMODEM over bytes 0..149, the same one app/uart.c uses
//
#define LOG_STREAM_SECONDS   10u
#define LOG_STREAM_VERSION   1u
#define LOG_STREAM_HEAD      22u
#define LOG_STREAM_BYTES     (LOG_STREAM_HEAD + LOG_FRAME_BYTES + 2u)   // 152

void APP_RunSpectrumLogger(void);
void APP_RunSpectrumStream(void);

#endif
