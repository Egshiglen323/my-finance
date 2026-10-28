#!/usr/bin/env sh
cd "$(dirname "$0")" && . .venv/bin/activate
( sleep 4; (xdg-open http://localhost:8501 || open http://localhost:8501) >/dev/null 2>&1 ) &
streamlit run app.py
