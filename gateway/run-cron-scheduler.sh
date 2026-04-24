#!/bin/bash
export PATH="$HOME/.pyenv/shims:$HOME/.local/bin:$PATH"
export PYENV_ROOT="$HOME/.pyenv"
export PYENV_SHELL=bash

cd "$HOME/Documents/GitHub/claude/gateway"
exec python3 cron-scheduler.py
