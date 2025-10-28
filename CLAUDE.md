# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BeatFinder is a Python application that analyses your Apple Music library and generates artist recommendations using the Last.fm API. It extracts library data from Apple Music's XML export, builds a taste profile from "loved" artists, and recommends new artists based on similarity, rarity, and genre tag matching.

## Development Commands

### Setup
```bash
make setup          # Install dependencies and create .env from .env.example
make install        # Install Python dependencies only
```

### Running
```bash
make run            # Run with cached data (fast, default mode)
make scan           # Re-scan Apple Music library XML (slow, first time only)
make refresh        # Refresh Last.fm metadata cache
make clean          # Clear all caches and output files

# Advanced usage
python beatfinder.py --refresh-recommendations  # Regenerate recommendations with current settings
python beatfinder.py --refresh-all             # Clear all caches (Last.fm + recommendations)
python beatfinder.py --clear-rejected          # Clear rejected artists cache
python beatfinder.py --no-interactive          # Skip interactive filtering menu
python beatfinder.py --regenerate-html         # Regenerate HTML visualisation only
python beatfinder.py --limit 20                # Change number of recommendations
python beatfinder.py --rarity 9                # Adjust rarity preference (1-15)
```

## Architecture

### Core Classes

**`AppleMusicLibrary`** (lines 116-276)
- Parses Apple Music's XML library export (plist format)
- Extracts artist statistics: play counts, ratings, loved status, track counts, last played dates
- Caches parsed library data to avoid re-parsing large XML files
- Methods:
  - `get_artist_stats()`: Returns dict of artist stats with caching support
  - `_parse_library_xml()`: Parses plist and aggregates track data by artist

**`LastFmClient`** (lines 300-465)
- Thread-safe Last.fm API client with response caching
- Implements global rate limiting (5 req/sec by default)
- Uses `RateLimiter` class for thread-safe rate limiting across concurrent requests
- Caches all API responses with configurable expiry (7 days default)
- Methods:
  - `get_similar_artists()`: Fetch similar artists with tags
  - `get_artist_tags()`: Get top genre tags for an artist
  - `get_artist_info()`: Get detailed stats (listeners, play count)

**`RecommendationEngine`** (lines 467-787)
- Core recommendation logic
- Builds set of "known" artists (filtered from recommendations)
- Identifies "loved" artists (used for taste profile building)
- Supports concurrent API requests via `ThreadPoolExecutor`
- Methods:
  - `get_loved_artists()`: Artists matching loved criteria (high plays/ratings)
  - `build_tag_profile()`: Build genre tag profile from loved artists
  - `calculate_tag_similarity()`: Score recommendations by tag overlap
  - `generate_recommendations()`: Main recommendation algorithm

**`interactive_filter`** (interactive_filter.py)
- Interactive TUI filtering for recommendations using InquirerPy
- Manages cache of rejected artists that persist across runs
- Functions:
  - `load_rejected_artists()`: Load set of rejected artist names from cache
  - `save_rejected_artists()`: Save rejected artists to cache
  - `filter_rejected_from_recommendations()`: Filter rejected artists from recommendations
  - `show_interactive_filter()`: Display checkbox menu for selecting artists to keep
- Cache file: `cache/rejected_artists.json`
- Rejected artists are cached permanently until cleared with `--clear-rejected`

### Artist Classification

**"Known" Artists** (filtered from recommendations):
- Artists with `KNOWN_ARTIST_MIN_PLAY_COUNT`+ plays (default: 3), OR
- Artists with `KNOWN_ARTIST_MIN_TRACKS`+ tracks in library (default: 5)

**"Loved" Artists** (used for taste profile):
- Any track explicitly marked as "loved" in Apple Music, OR
- `LOVED_PLAY_COUNT_THRESHOLD`+ plays (default: 50), OR
- Track rated `LOVED_MIN_TRACK_RATING`+ stars (default: 4) with `LOVED_MIN_ARTIST_PLAYS`+ plays (default: 10)
- Note: Artists meeting disliked criteria are excluded from loved artists (see below)

**"Disliked" Artists** (filtered from recommendations AND excluded from taste profile):
- Artists with `DISLIKED_MIN_TRACK_COUNT`+ disliked tracks (default: 2) AND no loved tracks
- These artists are completely excluded: they won't be recommended, and they won't be used to generate recommendations

### Caching System

**Multi-tier cache architecture**:

1. **Last.fm API cache** (`cache/lastfm_cache.json`)
   - Caches all API responses (similar artists, tags, artist info)
   - Expiry: `CACHE_EXPIRY_DAYS` (default: 7 days)
   - Cleared with `--refresh-cache` or `--refresh-all`

2. **Recommendations cache** (`cache/recommendations_cache.json`)
   - Caches scored/ranked recommendations
   - Invalidated if rarity preference changes or cache expires
   - Expiry: `RECOMMENDATIONS_CACHE_EXPIRY_DAYS` (default: 7 days)
   - Cleared with `--refresh-recommendations` or `--refresh-all`

3. **Library cache** (`cache/library_cache.json`)
   - Caches parsed Apple Music library XML
   - Cleared with `--scan-library`

4. **Apple Music scrape cache** (`cache/apple_music_scrape_cache.json`)
   - Caches scraped song IDs and URLs from Apple Music catalogue
   - Expiry: 7 days
   - Avoids re-scraping artists on subsequent runs
   - Automatically updated when new artists are scraped

### Scoring Algorithm

**Basic scoring** (when advanced features disabled):
- Frequency weight: How many loved artists recommend this artist
- Match weight: Last.fm similarity score
- Rarity weight: Inverse of listener count (configurable via `--rarity` 1-10)

**Advanced scoring** (when `ENABLE_TAG_SIMILARITY` or `ENABLE_PLAY_FREQUENCY_WEIGHTING` enabled):
- Uses configurable weights from `.env`:
  - `SCORING_FREQUENCY_WEIGHT` (default: 0.3)
  - `SCORING_TAG_OVERLAP_WEIGHT` (default: 0.3)
  - `SCORING_MATCH_WEIGHT` (default: 0.2)
  - `SCORING_RARITY_WEIGHT` (default: 0.2)

### Concurrent Processing

- Uses `ThreadPoolExecutor` with `MAX_CONCURRENT_REQUESTS` workers (default: 10)
- Global rate limiting via `RateLimiter` class ensures thread-safe API access
- Thread-safe cache access via `threading.Lock`

## Configuration

All settings in `.env` (copy from `.env.example`):

### Required
- `LASTFM_API_KEY`: Get from https://www.last.fm/api/account/create

### Key Settings
- `MAX_RECOMMENDATIONS`: Number of recommendations (default: 15)
- `RARITY_PREFERENCE`: 1 (popular) to 15 (very obscure), default: 7
- `KNOWN_ARTIST_MIN_PLAY_COUNT`: Threshold for filtering known artists (default: 3)
- `KNOWN_ARTIST_MIN_TRACKS`: Track count threshold for known artists (default: 5)

### Advanced Features
- `ENABLE_TAG_SIMILARITY`: Match genre tags to taste profile (default: false)
- `ENABLE_PLAY_FREQUENCY_WEIGHTING`: Weight by play counts (default: false)
- `LAST_MONTHS_FILTER`: Time-based filtering in months, 0=disabled (default: 0)
- `TAG_IGNORE_LIST`: Comma-separated tags to exclude from scoring
- `CREATE_APPLE_MUSIC_PLAYLIST`: Auto-create playlist (default: false, requires macOS)
- `GENERATE_HTML_VISUALISATION`: Generate interactive graph (default: false)

## Output Files

- `recommendations.md`: Markdown report with ranked artists
- `recommendations_visualisation.html`: Interactive vis.js network graph (if enabled)
- `cache/`: All cache files

## Platform Requirements

- **macOS only** for Apple Music/Music.app integration
- Python 3.9+
- Last.fm API key (free)
- Apple Music library XML export

## Important Implementation Details

### XML Parsing
- Library XML files can be 100MB+, parsing takes 5-10 seconds
- Uses `plistlib` (built-in) for parsing
- Shows progress every 10,000 tracks
- Star ratings stored as 0-100 (multiply by 20: 4 stars = 80)

### Apple Music Web API Integration

**Why this approach exists:**
- Apple's official MusicKit API requires paid Apple Developer subscription
- This uses browser-extracted tokens to bypass subscription requirement
- Tokens extracted from https://music.apple.com when logged in

**Token sources & expiry** (critical for playlist creation):
- `APPLE_MUSIC_WEB_DEV_TOKEN`: JWT found in URL params/network requests (~6 month expiry)
- `APPLE_MUSIC_WEB_MEDIA_USER_TOKEN`: Found in browser cookies/storage (~weeks expiry)
- When expired, user must manually re-extract from browser - no automatic refresh

**Non-obvious behaviours:**
- Playlist changes may take 1-3 minutes to update in Apple Music UI (API succeeds immediately but UI lags)
- Library filtering uses equivalents API to detect songs user already has (prevents duplicate adds)
- Regional availability: 500 errors trigger automatic equivalent lookup for user's region
- Country code hardcoded to 'au' (Australia) - change `COUNTRY_CODE` in `apple_music_web_api.py` if needed

### Artist Name Normalisation
- `_normalise_artist_name()` handles quote variations and spacing
- Important for matching artists between library and Last.fm API

### Thread Safety
- All Last.fm cache operations use `self.cache_lock`
- Rate limiter uses `threading.Lock` for thread-safe timestamp management
- Concurrent processing in `generate_recommendations()` and `build_tag_profile()`

## Dependencies

- `requests`: HTTP library for Last.fm API
- `python-dotenv`: Environment variable management
- `playwright`: Browser automation for Apple Music scraping
- `urllib3`: HTTP client for Apple Music web API
- Standard library: `plistlib`, `threading`, `concurrent.futures`, `subprocess`, `json`, `pathlib`

## Non-Obvious Design Decisions & Gotchas

### Why Playwright for Scraping
- Apple Music catalogue has no public API for song search
- Web scraping is the only way to get song IDs without Apple Developer subscription
- Playwright scraper clicks first artist result - can match wrong artist if name is ambiguous

### Cache Invalidation Rules
- Changing `RARITY_PREFERENCE` in `.env` automatically invalidates recommendations cache
- This is intentional: rarity affects scoring, so cached recommendations become stale

### Star Ratings Format
- Apple Music XML stores ratings as 0-100 integers (4 stars = 80)
- Code divides by 20 to get 1-5 scale - don't change this or loved artist detection breaks
