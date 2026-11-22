"""Add background music to the demo video (the picture is copied, not re-encoded).

Usage: python add_music.py <video_in.mp4> <music.mp3> <video_out.mp4> [music_start_seconds]

Music: fade in 0.8 s, fade out over the last 2.5 s, loudness normalised to -16 LUFS.
"""

import re
import subprocess
import sys

import imageio_ffmpeg

VIDEO, MUSIC, OUT = sys.argv[1:4]
START = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
FF = imageio_ffmpeg.get_ffmpeg_exe()

probe = subprocess.run([FF, "-i", VIDEO], capture_output=True, text=True).stderr
h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe).groups()
length = int(h) * 3600 + int(m) * 60 + float(s)
fade_out = 2.5

audio = (f"[1:a]atrim=start={START}:duration={length},asetpts=PTS-STARTPTS,"
         f"loudnorm=I=-16:TP=-1.5:LRA=11,volume=-2dB,"  # single-pass loudnorm runs ~2 dB hot
         f"afade=t=in:st=0:d=0.8,afade=t=out:st={length - fade_out:.2f}:d={fade_out}[a]")
subprocess.run([FF, "-y", "-loglevel", "error", "-i", VIDEO, "-i", MUSIC, "-filter_complex", audio,
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-shortest", "-movflags", "+faststart", OUT], check=True)
print(f"{OUT}: {length:.1f} s with music from {START:.1f} s")
