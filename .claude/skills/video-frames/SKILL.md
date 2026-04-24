---
user_invocable: true
name: video-frames
description: Extract frames from videos using FFmpeg. Use when user wants screenshots from video, frame extraction, or video thumbnails
---

# Video Frames - FFmpeg Frame Extraction

Use this skill to extract frames from video files for analysis or processing.

## When to Use

- Need to analyze specific moments in a video
- Extract thumbnail images from videos
- Get frames at regular intervals
- Convert video to image sequence

## Prerequisites

```bash
brew install ffmpeg
```

## Scripts

### frame.sh - Extract Single Frame
```bash
~/.claude/skills/video-frames/scripts/frame.sh video.mp4 output.jpg [timestamp]

# Examples:
~/.claude/skills/video-frames/scripts/frame.sh video.mp4 /tmp/thumb.jpg        # First frame
~/.claude/skills/video-frames/scripts/frame.sh video.mp4 /tmp/frame.jpg 00:01:30  # At 1:30
```

## Direct FFmpeg Commands

### Extract Single Frame
```bash
# First frame
ffmpeg -i video.mp4 -vframes 1 frame.jpg

# Frame at specific time
ffmpeg -ss 00:01:30 -i video.mp4 -vframes 1 frame.jpg

# With quality control
ffmpeg -ss 00:01:30 -i video.mp4 -vframes 1 -q:v 2 frame.jpg
```

### Extract Multiple Frames
```bash
# Every 1 second
ffmpeg -i video.mp4 -vf "fps=1" frame_%04d.jpg

# Every 10 seconds
ffmpeg -i video.mp4 -vf "fps=1/10" frame_%04d.jpg

# Every 60th frame
ffmpeg -i video.mp4 -vf "select='not(mod(n,60))'" -vsync vfr frame_%04d.jpg
```

### Extract Frame Range
```bash
# Frames from 1:00 to 1:10
ffmpeg -ss 00:01:00 -i video.mp4 -t 10 -vf "fps=1" frame_%04d.jpg

# First 10 frames
ffmpeg -i video.mp4 -vframes 10 frame_%04d.jpg
```

### With Size Adjustment
```bash
# Resize to 640px width, keep aspect ratio
ffmpeg -i video.mp4 -vframes 1 -vf "scale=640:-1" frame.jpg

# Resize to exact dimensions
ffmpeg -i video.mp4 -vframes 1 -vf "scale=1280:720" frame.jpg
```

### Get Video Info
```bash
# Duration and frame count
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 video.mp4

# Resolution
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 video.mp4

# FPS
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 video.mp4
```

## Common Patterns

### Quick Thumbnail (middle of video)
```bash
# Get duration, extract frame from middle
duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 video.mp4)
middle=$(echo "$duration / 2" | bc)
ffmpeg -ss $middle -i video.mp4 -vframes 1 thumbnail.jpg
```

### Contact Sheet / Grid
```bash
# Create 4x4 grid of frames
ffmpeg -i video.mp4 -vf "select='not(mod(n,100))',scale=320:180,tile=4x4" -frames:v 1 grid.jpg
```

## Output Formats

- `.jpg` - Smaller files, some quality loss
- `.png` - Lossless, larger files
- `.bmp` - Uncompressed
- `.webp` - Modern format, good compression
