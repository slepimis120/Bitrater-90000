# Bitrater-90000

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![NumPy](https://img.shields.io/badge/numpy-%23013243.svg?style=for-the-badge&logo=numpy&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)

***
Tool that calculates a track's accurate bitrate and re-encodes it, so the bitrate it reports is the real one.

## Introduction
A lot of MP3 files out there claim to be 320 kbps, but were actually upscaled from a lower quality source (usually 128 kbps or a YouTube rip). Re-encoding a low quality file to a higher bitrate can't bring back the lost frequencies. The file just gets bigger, while the sound stays the same.

This is easy to spot on a spectrogram: every MP3 encoder cuts off frequencies above a certain point, and that point depends on the bitrate. A real 320 kbps track goes up to ~20 kHz, while a 128 kbps track stops at ~16 kHz, no matter what the file says.

Bitrater-90000 analyzes the spectrum of every track, finds its real cutoff frequency, estimates the accurate bitrate and re-encodes the track to it, keeping all of the metadata and the cover art.

## Features
- Spectrum analysis and cutoff frequency detection
- Accurate bitrate estimation based on the cutoff
- Re-encoding only the tracks that lie about their bitrate (honest tracks are copied untouched)
- Keeps all ID3 tags and the cover art
- Processes a whole folder, including all subfolders
- Recreates the original folder structure in the output location
- Never touches the original files
- Command-line Interface (CLI)
- No Python or FFmpeg installation needed for end users *(planned)*
- GUI *(planned)*

***

## Requirements
- Python 3.10 or higher
- FFmpeg (with `libmp3lame`)

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

Analyze a single track:
```sh
python -m bitrater_90000.analyzer "path/to/track.mp3"
```

Process a whole folder:
```sh
python -m bitrater_90000.cli "path/to/music" "path/to/output"
```

***

## How it works
1. **Decoding**
   - The track is decoded to raw mono audio using FFmpeg.
2. **Spectrum analysis**
   - The average frequency spectrum of the whole track is calculated using FFT, skipping silent parts.
3. **Cutoff detection**
   - The program looks for the steepest drop in the spectrum above 10 kHz, which is the lowpass filter left behind by the original encoder.
4. **Bitrate estimation**
   - The cutoff frequency is mapped to the bitrate that produces it:

     | Cutoff | Accurate bitrate |
     |---|---|
     | ~19.7 kHz+ | 320 kbps |
     | ~19.2 kHz | 256 kbps |
     | ~18.3 kHz | 192 kbps |
     | ~17.2 kHz | 160 kbps |
     | ~15 kHz | 128 kbps |
     | ~12.5 kHz | 96 kbps |
     | lower | 64 kbps |

   - If no clear cutoff is found, the track is marked as uncertain and left untouched.
5. **Re-encoding**
   - If the estimated bitrate is lower than the claimed one, the track is re-encoded to the estimated bitrate, keeping the original sample rate. Otherwise, it's copied as is.
6. **Metadata**
   - All ID3 tags and the cover art are copied from the original file to the new one.

## Limitations
- Re-encoding MP3 to MP3 is one more round of lossy compression. At the estimated bitrate the difference is practically inaudible, but it's not zero, which is why the original files are never modified.
- Some tracks naturally have very little high frequency content (quiet, acoustic or old recordings), which can make them look lower quality than they are.

## Roadmap
- [x] Spectrum analysis and bitrate estimation
- [ ] Re-encoding and copying metadata and cover art
- [ ] Folder processing with the same folder structure on output
- [ ] Parallel processing and CSV report
- [ ] Standalone `.exe` with bundled FFmpeg (PyInstaller)
- [ ] GUI

## License
This project is licensed under GNU GENERAL PUBLIC LICENSE v3.