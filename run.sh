#!/bin/bash

export DB_PATH="/share/vorratsverwaltung/vorrat.db"
mkdir -p /share/vorratsverwaltung

echo "Starte Vorratsverwaltung..."
exec python3 /app/app.py
