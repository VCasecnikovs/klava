---
user_invocable: true
name: edge-tts
description: Text-to-speech using Microsoft Edge voices. Use when user asks to generate audio, read text aloud, voice synthesis, or озвучь
---

# Edge TTS - Text-to-Speech

Use this skill to convert text to speech using Microsoft Edge's high-quality neural voices. Supports multiple languages including Russian and English.

## When to Use

- User asks to read text aloud
- Generate audio files from text
- Need natural-sounding voice synthesis
- Russian or English TTS needed

## Prerequisites

```bash
pip3 install edge-tts
```

## Scripts

### speak.sh - Quick TTS
```bash
~/.claude/skills/edge-tts/scripts/speak.sh "Text to speak" [output.mp3] [voice]

# Examples:
~/.claude/skills/edge-tts/scripts/speak.sh "Hello world"
~/.claude/skills/edge-tts/scripts/speak.sh "Привет мир" /tmp/hello.mp3 ru-RU-DmitryNeural
```

## Direct Commands

### Generate Audio
```bash
# English (default voice)
edge-tts --text "Hello world" --write-media /tmp/output.mp3

# Russian - Dmitry (male)
edge-tts --voice ru-RU-DmitryNeural --text "Привет мир" --write-media /tmp/output.mp3

# Russian - Svetlana (female)
edge-tts --voice ru-RU-SvetlanaNeural --text "Привет мир" --write-media /tmp/output.mp3

# Play immediately
edge-tts --text "Hello" --write-media /tmp/temp.mp3 && afplay /tmp/temp.mp3
```

### List Available Voices
```bash
edge-tts --list-voices

# Filter by language
edge-tts --list-voices | grep ru-RU
edge-tts --list-voices | grep en-US
```

## Common Voices

| Voice | Language | Gender | Notes |
|-------|----------|--------|-------|
| ru-RU-DmitryNeural | Russian | Male | Natural, clear |
| ru-RU-SvetlanaNeural | Russian | Female | Warm, professional |
| en-US-GuyNeural | English | Male | Natural American |
| en-US-JennyNeural | English | Female | Natural American |
| en-GB-RyanNeural | English | Male | British accent |

## Advanced Options

```bash
# Adjust speed (rate)
edge-tts --rate="+50%" --text "Fast speech" --write-media fast.mp3
edge-tts --rate="-25%" --text "Slow speech" --write-media slow.mp3

# Adjust volume
edge-tts --volume="+50%" --text "Loud" --write-media loud.mp3

# Adjust pitch
edge-tts --pitch="+10Hz" --text "Higher" --write-media high.mp3
```

## Integration

### Play Audio After Generation
```bash
edge-tts --text "$TEXT" --write-media /tmp/tts.mp3 && afplay /tmp/tts.mp3
```

### From File
```bash
edge-tts --file input.txt --write-media output.mp3
```
