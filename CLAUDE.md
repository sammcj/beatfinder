# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BeatFinder is a Python application that analyses your Apple Music listening history and generates artist recommendations using the Last.fm API.

**Primary data source (recommended):** Apple Music privacy export from privacy.apple.com - provides complete streaming history with explicit likes/dislikes, skip detection, and engagement metrics from years of listening data.

**Alternative data source:** iTunes Library XML export - only includes local library tracks (purchased/matched music), missing streaming-only plays. Best for users who primarily listen to downloaded music rather than streaming.

The app builds a taste profile from "loved" artists, then uses Last.fm's API to find similar artists. Recommendations are scored by frequency, similarity, rarity, and optional tag matching, then filtered to exclude artists already in your library.

**IMPORTANT**: If you modify the recommendation flow or filtering logic, update the Mermaid diagram in README.md to reflect the changes. The diagram shows the complete processing pipeline from library parsing through to final output.

## Development Commands

### Setup
```bash
make setup          # Install dependencies and create .env from .env.example
make install        # Install Python dependencies only
```

### Running
```bash
make run            # Run with cached data (fast, default mode)
make scan           # Re-scan library data (Apple Music export CSV or iTunes XML)
make refresh        # Refresh Last.fm metadata cache
make filter         # Review and filter recommendations interactively (same as make run)
make clear-rejected # Clear rejected artists cache
make clean          # Clear all caches and output files

# Advanced usage
python beatfinder.py --scan-library            # Force re-parse of Apple Music export or iTunes XML
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

**`AppleMusicExportParser`** (apple_export_parser.py, PRIMARY DATA SOURCE)
- Parses Apple Music privacy export data (CSV files from privacy.apple.com)
- Data sources:
  - "Apple Music - Favorites.csv": Explicit LIKE/DISLIKE preferences
  - "Apple Music - Play History Daily Tracks.csv": Complete streaming history with play/skip counts
- Provides much richer data than iTunes XML: years of streaming history, explicit preferences, skip detection, engagement metrics
- Uses pandas + pickle caching for efficient parsing (9MB CSV, 72k plays parsed in ~3 seconds)
- Methods:
  - `get_artist_stats(force_refresh)`: Returns dict of artist stats compatible with AppleMusicLibrary format
  - `get_library_stats()`: Returns library statistics (oldest play, history span, total plays, skip rate, loved/disliked counts)
  - `_parse_favorites()`: Extract explicit likes/dislikes from Favorites.csv
  - `_parse_play_history()`: Parse daily play aggregations with skip detection
  - `_aggregate_by_artist()`: Combine favorites and play history into artist statistics
- Key stats calculated:
  - Play counts, skip counts, completion rates
  - Loved/disliked from explicit preferences
  - Last played dates, total play duration
  - Inferred ratings based on engagement (completion rate × skip penalty)

**`AppleMusicLibrary`** (library_parser.py, ALTERNATIVE DATA SOURCE)
- Parses iTunes Library XML export (plist format) from Music.app
- Only includes local library tracks (purchased/matched music)
- Missing: streaming-only plays, explicit like/dislike data, skip detection
- Best for users who don't stream or haven't requested Apple privacy export
- Extracts artist statistics: play counts, ratings, loved status, track counts, last played dates
- Caches parsed library data to avoid re-parsing large XML files (can be 100MB+)
- Methods:
  - `get_artist_stats()`: Returns dict of artist stats with caching support
  - `get_library_stats()`: Returns empty dict (iTunes XML doesn't include play history dates)
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
- Manages persistent storage of rejected artists that survive cache clearing
- Functions:
  - `load_rejected_artists()`: Load set of rejected artist names from persistent storage
  - `save_rejected_artists()`: Save rejected artists to persistent storage
  - `filter_rejected_from_recommendations()`: Filter rejected artists from recommendations
  - `show_interactive_filter()`: Display checkbox menu for selecting artists to keep
- Data file: `data/rejected_artists.json` (persists independently of cache/ folder)
- Rejected artists persist permanently until cleared with `--clear-rejected`

### Data Source Selection

**Configuration** (config.py, beatfinder.py):
```python
# In .env
USE_APPLE_EXPORT=true  # Use Apple Music privacy export (recommended)
APPLE_EXPORT_DIR=/path/to/Apple Music Activity/

# Or
USE_APPLE_EXPORT=false  # Use iTunes Library XML (alternative)
```

**Parser selection** (beatfinder.py):
- `get_library_parser()` helper function returns appropriate parser based on `USE_APPLE_EXPORT` setting
- Both parsers implement same interface: `get_artist_stats()` and `get_library_stats()`
- Apple Music export parser populates library stats (play history dates, total plays, skip rate)
- iTunes XML parser returns empty dict from `get_library_stats()` (no historical data available)

### Artist Classification

**"Known" Artists** (filtered from recommendations):
- Artists with `KNOWN_ARTIST_MIN_PLAY_COUNT`+ plays, OR
- Artists with `KNOWN_ARTIST_MIN_TRACKS`+ tracks in library

**"Loved" Artists** (used for taste profile):
- **Apple Music Export:** Artists with explicit "LIKE" in Favorites.csv, OR artists meeting play count thresholds
- **iTunes Library XML:** Any track explicitly marked as "loved" in Apple Music, OR `LOVED_PLAY_COUNT_THRESHOLD`+ plays, OR track rated `LOVED_MIN_TRACK_RATING`+ stars with `LOVED_MIN_ARTIST_PLAYS`+ plays
- Note: Artists meeting disliked criteria are excluded from loved artists (see below)
- Apple Music export provides more accurate loved artist detection via explicit user preferences rather than inferred ratings

**"Disliked" Artists** (filtered from recommendations AND excluded from taste profile):
- **Apple Music Export:** Artists with explicit "DISLIKE" in Favorites.csv AND no loved tracks
- **iTunes Library XML:** Artists with `DISLIKED_MIN_TRACK_COUNT`+ disliked tracks AND no loved tracks
- These artists are completely excluded: they won't be recommended, and they won't be used to generate recommendations
- Apple Music export provides explicit dislike data from user preferences

### Caching System

**Multi-tier cache architecture**:

1. **Last.fm API cache** (`cache/lastfm_cache.json`)
   - Caches all API responses (similar artists, tags, artist info)
   - Expiry: `CACHE_EXPIRY_DAYS`
   - Cleared with `--refresh-cache` or `--refresh-all`

2. **Recommendations cache** (`cache/recommendations_cache.json`)
   - Caches scored/ranked recommendations
   - Invalidated if rarity preference changes or cache expires
   - Expiry: `RECOMMENDATIONS_CACHE_EXPIRY_DAYS`
   - Cleared with `--refresh-recommendations` or `--refresh-all`

3. **Library cache** (location depends on data source)
   - **Apple Music Export:**
     - `cache/apple_export/artist_stats.json`: Aggregated artist statistics
     - `cache/apple_export/favorites.pkl`: Parsed favorites (likes/dislikes) with pandas pickle
     - `cache/apple_export/play_activity.pkl`: Parsed play history with pandas pickle
     - Pickle caching makes re-parsing fast (~1 second vs 3 seconds for 9MB CSV)
   - **iTunes Library XML:**
     - `cache/library_cache.json`: Parsed library data
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
  - `SCORING_FREQUENCY_WEIGHT`
  - `SCORING_TAG_OVERLAP_WEIGHT`
  - `SCORING_MATCH_WEIGHT`
  - `SCORING_RARITY_WEIGHT`

### Concurrent Processing

- Uses `ThreadPoolExecutor` with `MAX_CONCURRENT_REQUESTS` workers
- Global rate limiting via `RateLimiter` class ensures thread-safe API access
- Thread-safe cache access via `threading.Lock`

## Configuration

All settings in `.env` (copy from `.env.example`):

### Required
- `LASTFM_API_KEY`: Get from https://www.last.fm/api/account/create

### Data Source
- `USE_APPLE_EXPORT`: Use Apple Music privacy export (true, recommended) or iTunes Library XML (false)
- `APPLE_EXPORT_DIR`: Path to "Apple Music Activity" folder from Apple privacy export (required if USE_APPLE_EXPORT=true)

### Key Settings
- `MAX_RECOMMENDATIONS`: Number of recommendations
- `RARITY_PREFERENCE`: 1 (popular) to 15 (very obscure), default: 7
- `KNOWN_ARTIST_MIN_PLAY_COUNT`: Threshold for filtering known artists
- `KNOWN_ARTIST_MIN_TRACKS`: Track count threshold for known artists

### Advanced Features
- `ENABLE_TAG_SIMILARITY`: Match genre tags to taste profile
- `ENABLE_PLAY_FREQUENCY_WEIGHTING`: Weight by play counts
- `LAST_MONTHS_FILTER`: Time-based filtering in months, 0=disabled
- `TAG_SIMILARITY_IGNORE_LIST`: Comma-separated tags excluded from similarity scoring (artists with these tags can still be recommended)
- `TAG_BLACKLIST`: Comma-separated tags that completely filter out artists (artists with any blacklisted tag will never be recommended)
- `CREATE_APPLE_MUSIC_PLAYLIST`: Auto-create playlist
- `GENERATE_HTML_VISUALISATION`: Generate interactive graph

## Output Files

- `recommendations.md`: Markdown report with ranked artists (includes library statistics if using Apple Music export)
- `recommendations_visualisation.html`: Interactive vis.js network graph with library statistics (if enabled)
- `cache/`: Cached files / state
- `data/`: Persistent data files (e.g. rejected artists)

## Platform Requirements

- **macOS only** for Apple Music/Music.app integration
- Python 3.9+
- Last.fm API key (free)
- **One of:**
  - **Apple Music privacy export** (recommended) - Request from privacy.apple.com
  - iTunes Library XML export (alternative) - Export from Music.app (File → Library → Export Library)

## Important Implementation Details

### Apple Music Privacy Export Parsing
- CSV files are much smaller than iTunes XML (9MB vs 100MB+)
- Parsing is fast: ~3 seconds first run, ~1 second when cached (pickle format)
- Uses pandas for efficient CSV parsing with automatic type inference
- Play History CSV format: aggregated daily play counts (one row = one artist-day)
- Favorites CSV format: explicit LIKE/DISLIKE preferences with timestamps
- Artist extraction from "Artist - Song Title" format in Track Description field
- Stores library statistics: play history dates, total plays/skips, skip rate, loved/disliked counts

### iTunes Library XML Parsing (Alternative)
- Library XML files can be 100MB+, parsing takes 5-10 seconds
- Uses `plistlib` (built-in) for parsing
- Shows progress every 10,000 tracks
- Star ratings stored as 0-100 (multiply by 20: 4 stars = 80)
- No library statistics available (no historical play data in XML)

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
- `pandas`: CSV parsing and data manipulation for Apple Music export (with pickle caching)
- `playwright`: Browser automation for Apple Music scraping
- `inquirerpy`: Interactive TUI for recommendation filtering
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

### Playlist Genre Sorting
- When creating Apple Music playlists, recommendations are sorted by primary genre tag before playlist creation
- Grouping similar genres together creates a more cohesive listening experience
- Within each genre group, artists are still ordered by score (highest first)
- Sorting happens just before passing to playlist creation (doesn't affect markdown/HTML output order)

### Tag Filtering - Two Distinct Approaches

**TAG_SIMILARITY_IGNORE_LIST** (scoring exclusion):
- Excludes specific tags from taste profile building and similarity calculations
- Artists with these tags can still be recommended
- Use case: Generic/broad tags that don't help narrow down taste (e.g., "american", "female vocalists", "alternative")
- Example: Artist tagged "electronic, pop, ambient" with "pop" in ignore list → "electronic" and "ambient" still contribute to similarity scoring

**TAG_BLACKLIST** (complete filtering):
- Completely filters out any artist with blacklisted tags from recommendations
- Artists are removed after similar artist collection, before scoring
- Use case: Genres/styles you absolutely don't want (e.g., "pop", "country", "christmas")
- Example: Artist tagged "indie pop, dreamy" with "pop" in blacklist → completely filtered out, never recommended
- Filtering happens in `generate_recommendations()` at line 450-465

**When to use each:**
- Ignore list: Tags that are too generic or don't define your taste (e.g., "indie", "rock", "electronic" if you like many subgenres)
- Blacklist: Genres you actively dislike and never want recommended (e.g., "pop", "country", "edm")

## Virtual Environment

- We should always use a virtual environment in .venv to manage dependencies, as such it must be sourced before running any commands (`source .venv/bin/activate`)
- Don't try to run the scan for me unless I explicitly ask you too! you'll blow away my playlist!
