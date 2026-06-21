#!/bin/bash

if pgrep -f kronos_telegram_router.py >/dev/null; then
    echo "OK router running"
else
    echo "FAIL router stopped"
fi
