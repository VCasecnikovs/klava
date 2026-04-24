#!/bin/bash
# Quick text-to-speech using edge-tts
# Usage: speak.sh "text" [output.mp3] [voice]

TEXT="$1"
OUTPUT="${2:-/tmp/tts_output.mp3}"
VOICE="${3:-ru-RU-DmitryNeural}"

if [ -z "$TEXT" ]; then
    echo "Usage: speak.sh \"text to speak\" [output.mp3] [voice]"
    echo "Voices: ru-RU-DmitryNeural, ru-RU-SvetlanaNeural, en-US-GuyNeural, en-US-JennyNeural"
    exit 1
fi

edge-tts --voice "$VOICE" --text "$TEXT" --write-media "$OUTPUT"
echo "Audio saved to: $OUTPUT"

# Play if no custom output specified (default to /tmp)
if [ "$OUTPUT" = "/tmp/tts_output.mp3" ]; then
    afplay "$OUTPUT"
fi
