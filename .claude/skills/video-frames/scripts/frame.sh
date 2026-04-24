#!/bin/bash
# Extract a single frame from video
# Usage: frame.sh video.mp4 output.jpg [timestamp]

VIDEO="$1"
OUTPUT="$2"
TIMESTAMP="${3:-00:00:00}"

if [ -z "$VIDEO" ] || [ -z "$OUTPUT" ]; then
    echo "Usage: frame.sh video.mp4 output.jpg [timestamp]"
    echo "  timestamp: HH:MM:SS format (default: 00:00:00)"
    echo ""
    echo "Examples:"
    echo "  frame.sh video.mp4 thumb.jpg           # First frame"
    echo "  frame.sh video.mp4 thumb.jpg 00:01:30  # Frame at 1:30"
    exit 1
fi

if [ ! -f "$VIDEO" ]; then
    echo "Error: Video file not found: $VIDEO"
    exit 1
fi

# Extract frame with good quality
ffmpeg -ss "$TIMESTAMP" -i "$VIDEO" -vframes 1 -q:v 2 "$OUTPUT" -y 2>/dev/null

if [ -f "$OUTPUT" ]; then
    echo "Frame extracted to: $OUTPUT"
    # Show file size
    ls -lh "$OUTPUT" | awk '{print "Size:", $5}'
else
    echo "Error: Failed to extract frame"
    exit 1
fi
