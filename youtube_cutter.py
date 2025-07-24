#!/usr/bin/env python3
"""
Cut and concatenate media clips (local files or YouTube URLs) with optional pauses and fades.

Usage:
    python youtube_cutter.py <pause> <fade> file1 start1 end1 [file2 start2 end2 ...] [-o output.mp4]
    # Note: in zsh, quote URLs containing '?', e.g.:
    #   python youtube_cutter.py 2 2 \
    #     'https://youtu.be/k4yXQkG2s1E?si=...' 00:39 01:06 \
    #     'https://youtu.be/YxWlaYCA8MU?si=...' 01:12 01:30

Arguments:
  pause        Pause duration in seconds between clips
  fade         Fade‑in/out duration in seconds for each clip
  fileX        Path or URL to media file
  startX       Start time (seconds or mm:ss) for fileX
  endX         End time (seconds or mm:ss) for fileX

Options:
  -o, --output  Output filename (default: output.mp4)
"""
import argparse
import os
import shutil
import sys
import tempfile
import subprocess
import subprocess

from pytube import YouTube
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    AudioClip,
    ColorClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut


def parse_time(t):
    """Parse time in seconds or hh:mm:ss format to seconds (float)."""
    if ':' in t:
        parts = [float(p) for p in t.split(':')]
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h = 0.0
            m, s = parts
        else:
            raise ValueError(f"Invalid time format: {t}")
        return h * 3600 + m * 60 + s
    return float(t)


def download_video(url, output_path):
    # strip URL query parameters (e.g. '?si=...') and normalize URL
    clean_url = url.split('?', 1)[0]
    if 'youtu.be/' in clean_url:
        vid = clean_url.rsplit('/', 1)[1]
        clean_url = f'https://www.youtube.com/watch?v={vid}'
    # attempt pytube download (video->audio)
    try:
        yt = YouTube(clean_url)
        stream = yt.streams.filter(progressive=True, file_extension='mp4') \
            .order_by('resolution').desc().first()
        if not stream:
            raise RuntimeError(f"No suitable stream found for {url}")
        stream.download(output_path=os.path.dirname(output_path), filename=os.path.basename(output_path))
        return output_path
    except Exception as err:
        # fallback to yt-dlp for bestaudio
        print(f"pytube failed ({err}), falling back to yt-dlp...", file=sys.stderr)
        cmd = [
            'yt-dlp', '-f', 'bestaudio',
            '-o', output_path,
            clean_url,
        ]
        subprocess.run(cmd, check=True)
        return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Cut local or YouTube media segments and concatenate with optional pauses and fades."
    )
    parser.add_argument(
        'pause', type=float,
        help='Pause duration in seconds between clips'
    )
    parser.add_argument(
        'fade', type=float,
        help='Fade-in/out duration in seconds for each clip'
    )
    parser.add_argument(
        'segments', nargs='+',
        help='Segments as triples: file1 start1 end1 [file2 start2 end2 ...]'
    )
    parser.add_argument(
        '-o', '--output', default='output.mp4',
        help='Output filename'
    )
    args = parser.parse_args()

    clips = []
    temp_dir = tempfile.mkdtemp(prefix='youtube_cutter_')
    try:
        # Parse segments from command-line triples
        entries = []
        if len(args.segments) % 3 != 0:
            sys.exit("Segments must be triples: file1 start1 end1 [file2 start2 end2 ...]")
        for i in range(0, len(args.segments), 3):
            entries.append((args.segments[i], args.segments[i+1], args.segments[i+2]))

        audio_mode = None
        for idx, (src, t0, t1) in enumerate(entries, start=1):
            start = parse_time(t0)
            end = parse_time(t1)
            print(f"Processing segment {idx}: {src} ({start}s to {end}s)")
            # Fetch YouTube sources; always extract audio from URLs
            is_url = src.startswith(('http://', 'https://'))
            if is_url:
                local_path = os.path.join(temp_dir, f"media_{idx}.mp4")
                try:
                    download_video(src, local_path)
                except Exception as exc:
                    sys.exit(f"Error downloading '{src}': {exc}")
                src = local_path
            # Determine audio vs video segments
            if is_url or src.lower().endswith(('.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg')):
                # audio-only (use subclipped for AudioFileClip)
                clip = AudioFileClip(src).subclipped(start, end)
                mode = 'audio'
            else:
                clip = VideoFileClip(src).subclip(start, end)
                mode = 'video'
            # Set audio/video mode consistency
            if audio_mode is None:
                audio_mode = (mode == 'audio')
            elif audio_mode and mode != 'audio':
                sys.exit("Cannot mix audio and video segments")
            # Apply fades
            if args.fade > 0:
                if mode == 'audio':
                    clip = clip.with_effects([
                        AudioFadeIn(args.fade),
                        AudioFadeOut(args.fade)
                    ])
                else:
                    clip = clip.fx(AudioFadeIn, args.fade).fx(AudioFadeOut, args.fade)

            clips.append(clip)
            # Insert pause if requested
            if args.pause > 0:
                if audio_mode:
                    pause = AudioClip(lambda t: 0, duration=args.pause, fps=clip.fps)
                else:
                    w, h = clip.size
                    pause = ColorClip(size=(w, h), color=(0, 0, 0), duration=args.pause)
                    pause = pause.set_fps(clip.fps).without_audio()
                clips.append(pause)

        if not clips:
            sys.exit("No clips to process.")
        # Remove final pause
        if args.pause > 0:
            clips = clips[:-1]

        # Concatenate and write
        print(f"Writing output to {args.output}")
        if audio_mode:
            final = concatenate_audioclips(clips)
            out_path = args.output
            # ensure audio-friendly extension
            base, ext = os.path.splitext(out_path)
            if not ext:
                out_path = base + '.mp3'
            elif ext.lower() in ('.mp4', '.mkv', '.mov', '.avi'):
                out_path = base + '.mp3'
                print(f"Audio-only mode: writing to {out_path}")
            final.write_audiofile(out_path)
        else:
            final = concatenate_videoclips(clips, method='compose')
            final.write_videofile(
                args.output,
                codec='libx264',
                audio_codec='aac'
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
