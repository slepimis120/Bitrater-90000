# Bitrater-90000

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![NumPy](https://img.shields.io/badge/numpy-%23013243.svg?style=for-the-badge&logo=numpy&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)

***
Tool that detects the real bitrate of MP3 files by analyzing their spectrum, instead of trusting what the file says.

## Introduction
A lot of MP3 files out there claim to be 320 kbps, but were actually upscaled from a lower quality source (usually a 128 kbps MP3 or a YouTube rip). Re-encoding a low quality file to a higher bitrate can't bring back the lost frequencies. The file just gets bigger, while the sound stays the same.

The bitrate shown in your player, file explorer or tag editor is read from the file itself, so it can't be used to catch this. The spectrum can: every MP3 encoder cuts off frequencies above a certain point, and that point depends on the bitrate. A real 320 kbps track goes up to ~20 kHz, while a 128 kbps track stops at ~16 kHz, no matter what the file says.

Bitrater-90000 goes through your whole music collection, analyzes the spectrum of every track and writes a report sorted from the worst to the best real quality, so you know exactly which tracks are fake.

## Features
- Spectral analysis of every track (the claimed bitrate is never trusted)
- Codec cutoff detection and real bitrate estimation
- Correct handling of VBR files and tracks with naturally quiet high frequencies
- Detection of damaged files (corrupted audio data hidden behind valid tags)
- Scans a whole folder, including all subfolders
- Parallel processing on all CPU cores
- Text report sorted from the worst to the best real quality
- Never modifies the original files
- Command-line Interface (CLI)

***

## Requirements
- Python 3.10 or higher
- FFmpeg

## Getting started

1. Clone the repository:
   ```sh
   git clone https://github.com/slepimis120/Bitrater-90000.git
   cd Bitrater-90000
   ```

2. Create and activate a virtual environment:
   ```sh
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the requirements:
   ```sh
   pip install -r requirements.txt
   ```

4. Download a static FFmpeg build (for example *ffmpeg-release-essentials* from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)) and place `ffmpeg.exe` into the `bin` folder. If it's not there, Bitrater-90000 will look for FFmpeg on the system `PATH`.

## Usage

Analyze a whole folder and write a report:
```sh
python -m bitrater_90000.cli report "path/to/music" -o report.txt
```

| Option | Description |
|---|---|
| `-o`, `--output` | Report file (default: `bitrater_report.txt`) |
| `-j`, `--jobs` | Number of parallel processes (default: number of CPU cores) |

Analyze a single track:
```sh
python -m bitrater_90000.analyzer "path/to/track.mp3"
```

## Report

```
Bitrater-90000 report
Folder:  C:\Music
Tracks:  1442 total, 1305 OK, 118 fake, 17 uncertain, 2 damaged, 0 errors

 REAL  CLAIMED      CUTOFF  STATUS  FILE
  128      320    16.1 kHz  FAKE    Jesus Belluci - 8.mp3
  128      128    16.8 kHz  OK      Windowshopping - Euthanex.mp3
  192      269    18.9 kHz  FAKE    Trinity Megas - I'm So Into You.mp3
  247      247   ~21.9 kHz  OK      Casper Mcfadden - pppppo.mp3
  320      320    20.2 kHz  OK      Machine Girl - Krystle.mp3
```

| Status | Meaning |
|---|---|
| `OK` | The claimed bitrate matches the real one |
| `FAKE` | The track was upscaled from a lower quality source |
| `UNSURE` | No clear cutoff was found, check the track manually in a spectrogram viewer like [Spek](https://www.spek.cc/) |
| `DAMAGED` | Part of the audio data is corrupted and can't be decoded, the track should be re-downloaded |
| `ERROR` | The file couldn't be read at all |

A `~` in front of the cutoff means there is no codec cutoff at all: the content naturally reaches that frequency, which is a sign of a full quality track.

***

## How it works
1. **Decoding**
   - 8 segments of 12 seconds, spread evenly through the track, are decoded to raw mono audio using FFmpeg. This is enough for a reliable spectrum, while being much faster than decoding the whole track.
2. **Spectrum analysis**
   - The spectrum of every frame is calculated using FFT, and the silent frames are skipped.
   - Instead of averaging, the spectrum is summarized by percentiles. The median can't be fooled by rare spikes above the cutoff, while the higher percentiles catch tracks that have high frequencies only in some parts.
3. **Cutoff detection**
   - The program looks for the steepest drop in the spectrum above 10 kHz, which is the lowpass filter left behind by the original encoder. It starts from the median, and only moves to the higher percentiles if the median gives no clear answer.
   - If there is no drop, but the content reaches above 19.5 kHz, the track is considered full quality.
4. **Bitrate estimation**
   - The cutoff frequency is mapped to the bitrate that produces it:

     | Cutoff | Real bitrate |
     |---|---|
     | ~19.7 kHz+ | 320 kbps |
     | ~19.2 kHz | 256 kbps |
     | ~18.3 kHz | 192 kbps |
     | ~17.2 kHz | 160 kbps |
     | ~15 kHz | 128 kbps |
     | ~12.5 kHz | 96 kbps |
     | lower | 64 kbps |

   - The real bitrate can never be higher than the claimed one. A track is marked as fake if its real bitrate is at least 32 kbps lower than the claimed one, which leaves room for VBR files.
5. **Damage detection**
   - If a segment can't be decoded, the whole track is decoded and the amount of audio that actually exists is measured. If less than 95% of the track can be decoded, it's marked as damaged.

## Limitations
- The analysis is an estimation, just like looking at a spectrogram. Around 1% of tracks end up uncertain, mostly lo-fi productions, sound effects and tracks with very quiet high frequencies.
- The difference between 256 and 320 kbps is only a few hundred Hz of cutoff. Some encoders other than LAME cut lower at 320 kbps, so a 256 result is worth double checking.
- Only MP3 files are supported.

## Roadmap
- [x] Spectral analysis and real bitrate estimation
- [x] Folder scanning with subfolders
- [x] Parallel processing
- [x] Text report sorted by real quality
- [x] Damaged file detection
- [ ] Manual overrides for uncertain tracks
- [ ] Converting fake tracks to their real bitrate, keeping all ID3 tags and the cover art, with the same folder structure on output
- [ ] Lossless mode, which writes the real bitrate into a tag without touching the audio
- [ ] Experimental: reconstructing the original low bitrate MP3 from an upscaled one, without any additional quality loss
- [ ] Standalone `.exe` with bundled FFmpeg (PyInstaller)
- [ ] GUI