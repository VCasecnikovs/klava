#!/usr/bin/env python3
"""UserPromptSubmit hook - minimal, no pipeline state machine."""
import json
import sys


def main():
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
        }
    }
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
