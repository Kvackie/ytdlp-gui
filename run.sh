#!/bin/sh
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m ytdlp_gui "$@"
