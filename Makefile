.PHONY: setup install run scan refresh clean help

help:
	@echo "BeatFinder - Artist recommendation tool"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup         - Install dependencies and create .env"
	@echo "  make install       - Install dependencies only"
	@echo "  make run           - Run with cached data (fast)"
	@echo "  make scan          - Re-scan Music library (slow, first time only)"
	@echo "  make refresh       - Refresh Last.fm metadata cache"
	@echo "  make clean         - Clear all caches"
	@echo "  make help          - Show this help"

setup:
	./setup.sh

install:
	pip3 install -r requirements.txt
	playwright install chromium

run:
	python3 beatfinder.py

scan:
	python3 beatfinder.py --scan-library

refresh:
	python3 beatfinder.py --refresh-cache

clean:
	rm -rf cache/
	rm -f recommendations*.md recommendations*.json
	@echo "✓ Cache and output files removed"
