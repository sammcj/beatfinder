#!/usr/bin/env python3
"""
Configuration settings for BeatFinder
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Last.fm API
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")

# Library source - Apple Music export (streaming history) or iTunes XML (local library)
USE_APPLE_EXPORT = os.getenv("USE_APPLE_EXPORT", "false").lower() == "true"
APPLE_EXPORT_DIR = os.getenv("APPLE_EXPORT_DIR", "")

# Recommendation settings
MAX_RECOMMENDATIONS = int(os.getenv("MAX_RECOMMENDATIONS", "15"))

# Artist classification thresholds
KNOWN_ARTIST_MIN_PLAY_COUNT = int(os.getenv("KNOWN_ARTIST_MIN_PLAY_COUNT", "3"))
KNOWN_ARTIST_MIN_TRACKS = int(os.getenv("KNOWN_ARTIST_MIN_TRACKS", "5"))
LOVED_PLAY_COUNT_THRESHOLD = int(os.getenv("LOVED_PLAY_COUNT_THRESHOLD", "50"))
LOVED_MIN_TRACK_RATING = int(os.getenv("LOVED_MIN_TRACK_RATING", "4"))  # 1-5 stars
LOVED_MIN_ARTIST_PLAYS = int(os.getenv("LOVED_MIN_ARTIST_PLAYS", "10"))

# Disliked artist filtering
LIB_DISLIKED_MIN_TRACK_COUNT = int(os.getenv("LIB_DISLIKED_MIN_TRACK_COUNT", "2"))  # Min disliked tracks to filter artist

# Cache settings
CACHE_EXPIRY_DAYS = int(os.getenv("CACHE_EXPIRY_DAYS", "7"))
RECOMMENDATIONS_CACHE_EXPIRY_DAYS = int(os.getenv("RECOMMENDATIONS_CACHE_EXPIRY_DAYS", "7"))

# Rarity preference
RARITY_PREFERENCE = int(os.getenv("RARITY_PREFERENCE", "7"))

# Validate rarity preference
if not 1 <= RARITY_PREFERENCE <= 15:
    print(f"Warning: RARITY_PREFERENCE={RARITY_PREFERENCE} is out of range (1-15). Using default: 7")
    RARITY_PREFERENCE = 7

# Performance settings
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
MAX_REQUESTS_PER_SECOND = int(os.getenv("MAX_REQUESTS_PER_SECOND", "5"))

# Advanced recommendation features
ENABLE_TAG_SIMILARITY = os.getenv("ENABLE_TAG_SIMILARITY", "false").lower() == "true"
ENABLE_PLAY_FREQUENCY_WEIGHTING = os.getenv("ENABLE_PLAY_FREQUENCY_WEIGHTING", "false").lower() == "true"
LAST_MONTHS_FILTER = int(os.getenv("LAST_MONTHS_FILTER", "0"))

# Tag similarity ignore list - tags ignored when calculating similarity scores (not for filtering)
LIB_TAG_IGNORE_LIST_RAW = os.getenv("LIB_TAG_IGNORE_LIST", "")
LIB_TAG_IGNORE_LIST = set(tag.strip().lower() for tag in LIB_TAG_IGNORE_LIST_RAW.split(",") if tag.strip())

# Tag blacklist - completely filter out artists with these tags from recommendations
REC_TAG_BLACKLIST_RAW = os.getenv("REC_TAG_BLACKLIST", "")
REC_TAG_BLACKLIST = set(tag.strip().lower() for tag in REC_TAG_BLACKLIST_RAW.split(",") if tag.strip())

# Apple Music playlist creation
CREATE_PLAYLIST = os.getenv("CREATE_PLAYLIST", "false").lower() == "true"
PLAYLIST_SONGS_PER_ARTIST = int(os.getenv("PLAYLIST_SONGS_PER_ARTIST", "3"))
AM_SCRAPE_BATCH_SIZE = int(os.getenv("AM_SCRAPE_BATCH_SIZE", "5"))
PLAYLIST_MERGE_MODE = os.getenv("PLAYLIST_MERGE_MODE", "true").lower() == "true"

# Interactive filtering
CLI_INTERACTIVE_FILTERING = os.getenv("CLI_INTERACTIVE_FILTERING", "true").lower() == "true"

# HTML visualisation
HTML_VISUALISATION = os.getenv("HTML_VISUALISATION", "false").lower() == "true"

# Scoring weights (when advanced features enabled)
SCORING_FREQUENCY_WEIGHT = float(os.getenv("SCORING_FREQUENCY_WEIGHT", "0.3"))
SCORING_TAG_OVERLAP_WEIGHT = float(os.getenv("SCORING_TAG_OVERLAP_WEIGHT", "0.3"))
SCORING_MATCH_WEIGHT = float(os.getenv("SCORING_MATCH_WEIGHT", "0.2"))
SCORING_RARITY_WEIGHT = float(os.getenv("SCORING_RARITY_WEIGHT", "0.2"))

# Directories
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

# Data directory for persistent user data (not cleared with cache)
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


def show_config():
    """Display configuration settings"""
    print("\n" + "="*60)
    print("BeatFinder Configuration")
    print("="*60)
    print(f"Library source: {'Apple Music Export (streaming)' if USE_APPLE_EXPORT else 'iTunes XML (local library)'}")
    print(f"Max recommendations: {MAX_RECOMMENDATIONS}")
    print(f"\nArtist classification:")
    print(f"  'Known' (filtered from recommendations):")
    print(f"    - {KNOWN_ARTIST_MIN_PLAY_COUNT}+ plays, OR")
    print(f"    - {KNOWN_ARTIST_MIN_TRACKS}+ tracks in library")
    print(f"  'Loved' (used for taste profile):")
    print(f"    - {LOVED_PLAY_COUNT_THRESHOLD}+ plays, OR")
    print(f"    - {LOVED_MIN_TRACK_RATING}+ star rating with {LOVED_MIN_ARTIST_PLAYS}+ plays")
    print(f"  'Disliked' (filtered from recommendations):")
    print(f"    - {LIB_DISLIKED_MIN_TRACK_COUNT}+ disliked tracks AND no loved tracks")
    print(f"\nRarity preference: {RARITY_PREFERENCE}")
    print(f"Last.fm cache expiry: {CACHE_EXPIRY_DAYS} days")
    print(f"Recommendations cache expiry: {RECOMMENDATIONS_CACHE_EXPIRY_DAYS} days")

    # Show advanced features if enabled
    advanced_features = []
    if ENABLE_TAG_SIMILARITY:
        advanced_features.append("Tag similarity matching")
    if ENABLE_PLAY_FREQUENCY_WEIGHTING:
        advanced_features.append("Play frequency weighting")
    if LAST_MONTHS_FILTER > 0:
        advanced_features.append(f"Time filter: last {LAST_MONTHS_FILTER} months")
    if CREATE_PLAYLIST:
        advanced_features.append(f"Create playlist ({PLAYLIST_SONGS_PER_ARTIST} songs per artist)")

    if advanced_features:
        print("\nAdvanced features enabled:")
        for feature in advanced_features:
            print(f"  • {feature}")

    # Show tag filters if any
    if REC_TAG_BLACKLIST:
        print(f"\nBlacklisted tags (artists filtered): {', '.join(sorted(REC_TAG_BLACKLIST))}")
    if LIB_TAG_IGNORE_LIST:
        print(f"Similarity ignored tags (not used for scoring): {', '.join(sorted(LIB_TAG_IGNORE_LIST))}")

    print("="*60 + "\n")
