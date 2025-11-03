# BeatFinder Web Interface

Modern web UI for BeatFinder with real-time visualisations and full integration with the BeatFinder recommendation engine.

## What This Is

A fully functional web interface for BeatFinder that:

- **Uses real library data** from Apple Music export or iTunes XML
- **Generates real recommendations** using Last.fm API
- **Runs alongside CLI** - both interfaces work independently
- **Shares configuration** from `.env` with session-based overrides
- **Provides visual feedback** on how settings affect recommendations

Built with Flask + HTMX + Tailwind CSS for a lightweight, responsive experience.

## Features Implemented

### Core Functionality ✅

- **Real library parsing**: Loads artist statistics from Apple Music export (CSV) or iTunes XML
- **Live statistics**: Shows actual artist counts, play counts, skip rates, listening history
- **Tag profile building**: Generates genre tag profile from loved artists via Last.fm
- **Recommendation generation**: Full integration with `RecommendationEngine` class
- **Cache management**: Clear Last.fm cache, recommendations cache, or force library re-scan
- **Session-based settings**: Adjust configuration in UI without modifying `.env` file

### UI Components ✅

- **Rarity slider (1-15)**: Adjusts scoring weight distribution with live chart updates
- **Classification thresholds**: Configure loved/known artist criteria with dynamic statistics
- **Tag management**: Blacklist and ignore list with chip-based interface and tag bucket
- **Artist blacklist**: Add artists that should never be recommended
- **Taste profile exclusion**: Exclude library artists from influencing recommendations
- **Impact metre**: Visual indicator showing how settings affect recommendation scope
- **Preview panel**: Top 5 recommendations from cache (updates after generation)
- **Real-time updates**: HTMX-powered dynamic updates without page reloads

### Advanced Features ✅

- **Tag similarity matching**: Enable/disable genre tag matching with visual tag cloud
- **Play frequency weighting**: Optional weighting based on play counts
- **Date range filtering**: Filter plays by date range (from/to)
- **Data source selection**: Switch between Apple Music export and iTunes XML
- **Export/import settings**: Save and load configuration as JSON
- **Tabbed interface**: Configuration, Results, Visualisation tabs
- **Results tab**: Markdown viewer with export/copy functionality
- **Visualisation tab**: Loads HTML network graph from generated visualisation
- **Previous runs history**: Tracks last 50 runs with settings and timestamps
- **Progress indicators**: Real-time status updates during generation
- **Settings persistence**: Load settings from previous runs

### Integration ✅

- **CLI preserved**: Original `beatfinder.py` works independently, untouched
- **Shared caching**: Both web and CLI use same Last.fm and recommendation caches
- **Module imports**: Web app imports BeatFinder classes without code duplication
- **Error handling**: Graceful fallbacks if library can't be loaded

## Running the Web Interface

### Quick Start

```bash
cd web_prototype
./run.sh
```

Then open http://localhost:5001 in your browser.

### Manual Start

```bash
cd web_prototype

# Install Flask (if needed)
pip install -r requirements.txt

# Run the server
python app.py
```

### Prerequisites

1. **Last.fm API key** configured in `.env` (same as CLI)
2. **Apple Music export** or **iTunes Library XML** configured
3. **Python 3.13+** with virtual environment activated
4. **Flask >=3.1.2** installed

## CLI Still Works

The original CLI is completely preserved and works independently:

```bash
# From project root
python beatfinder.py --rarity 10 --limit 50

# All CLI flags still work
python beatfinder.py --help
python beatfinder.py --scan-library
python beatfinder.py --refresh-cache
```

Both interfaces share the same cache files, so recommendations generated in the web UI are available in the CLI and vice versa.

## File Structure

```
web_prototype/
├── app.py                          # Flask routes with real BeatFinder integration
├── requirements.txt                # Flask dependency
├── run.sh                         # Quick start script
├── templates/
│   ├── base.html                  # Base layout with tabs, import/export
│   ├── index.html                 # Main config page with 4-column layout
│   └── partials/                  # HTMX-swapped fragments
│       ├── weight_chart.html      # Scoring weights doughnut chart
│       ├── artist_stats.html      # Classification counts (loved/known/disliked)
│       ├── tag_cloud.html         # Tag profile visualisation
│       ├── impact_meter.html      # Recommendation scope gauge
│       ├── preview_results.html   # Top 5 recommendations with blacklist buttons
│       └── run_details.html       # Modal for previous run details
├── cache/                         # Shared cache with CLI (gitignored)
├── data/                          # Persistent data (gitignored)
└── README.md
```

## Architecture

### Backend
- **Flask**: Lightweight Python web server
- **Real BeatFinder classes**: Imports `AppleMusicExportParser`, `AppleMusicLibrary`, `LastFmClient`, `RecommendationEngine`
- **Session management**: Per-user config overrides stored in Flask sessions
- **Error handling**: Try/except blocks with fallback to empty data

### Frontend
- **HTMX**: Dynamic HTML updates via AJAX (~14KB, CDN)
- **Tailwind CSS**: Utility-first styling (CDN)
- **Chart.js**: Lightweight charts for visualisations (~200KB, CDN)
- **Vanilla JavaScript**: Tag/artist management, form handling, fetch API calls

### Data Flow

1. User adjusts slider → HTMX posts to Flask route
2. Flask updates session + recalculates stats/weights
3. Flask renders partial template with new data
4. HTMX swaps updated HTML fragment
5. Chart.js re-renders if needed (with animations disabled)

## Configuration

The web UI uses the same `.env` configuration as the CLI. Session overrides are temporary and don't modify `.env`.

### Session-based Settings (UI adjustments)
- Rarity preference
- Max recommendations
- Artist classification thresholds
- Tag blacklist/ignore lists
- Artist blacklist
- Taste profile exclusions
- Feature toggles (tag similarity, play frequency weighting)

### Environment Settings (from `.env`)
- Last.fm API key
- Data source (Apple export vs iTunes XML)
- Export directory path
- Cache expiry times
- Performance settings

## Known Limitations

See **Unfinished Items** section below for features not yet implemented.

## Recently Completed ✓

### Core Features (Just Implemented)

- [x] **Results tab markdown viewer**: Display generated recommendations in markdown format
  - Loads cached recommendations and formats as markdown
  - Export as .md file or copy to clipboard
  - Includes library statistics and settings metadata
  - Simple markdown-to-HTML converter for display

- [x] **Visualisation tab**: HTML network graph from `recommendations_visualisation.html`
  - Loads generated visualisation HTML if available
  - Shows friendly error if visualisation not generated
  - Refresh button to reload visualisation
  - Full-width responsive container

- [x] **Previous runs history**: Track and display past recommendation runs
  - Stores last 50 runs in `data/run_history.json`
  - Shows timestamp, recommendation count, and key settings
  - Click to load settings from any previous run
  - Auto-refreshes after new generation
  - Persists independently of cache

- [x] **Export/import settings**: Full settings portability
  - Export current settings as JSON file
  - Import settings from JSON file
  - Settings load into session immediately
  - Includes all configuration options

- [x] **Date range picker functionality**: Wire up date filtering
  - Date inputs connected to backend
  - Filters library by last_played dates
  - Shows filtered artist count in success message
  - Gracefully handles invalid dates

- [x] **Progress indicators**: Real-time status updates during generation
  - Processing status with spinner animation
  - Success status with checkmark
  - Error status with X icon
  - Status persists in "Processing Status" panel

## Remaining Items

### High Priority

- [ ] **Apple Music export path browser**: File picker for selecting export directory
  - Currently just a text input
  - Should validate path exists and contains required CSV files
  - Show warning if path is invalid
  - Note: Browser file pickers can't select folders, may need alternative approach

### Medium Priority

- [ ] **Artist/genre autocomplete**: Suggest artist names when typing in blacklist/exclusion fields
  - Pull from library artist list
  - Fuzzy matching for typos
  - Dropdown with suggestions

- [ ] **Recommendation filtering in UI**: Interactive filtering similar to CLI
  - Checkbox list to select which recommendations to keep
  - Replace or supplement "Blacklist This Artist" buttons
  - Update preview and results dynamically

- [ ] **Apple Music playlist creation from UI**: Button to create playlist
  - Currently CLI-only feature
  - Web scraping + API calls might timeout in web context
  - Consider background job queue

### Low Priority

- [ ] **Markdown export from results tab**: Download button for recommendations.md
  - Generate markdown from recommendations data
  - Trigger browser download
  - Include library stats and settings snapshot

- [ ] **Batch tag operations**: Select multiple tags at once
  - Shift-click to select range
  - "Add all" / "Remove all" buttons
  - Useful for managing large ignore lists

### Technical Improvements

- [ ] **Error messages in UI**: Show errors inline instead of alerts
  - Toast notifications for success/error
  - Inline validation messages
  - Better UX than browser alerts

- [ ] **Loading states**: Skeleton screens while loading
  - Replace spinners with skeleton UI
  - Perceived performance improvement
  - More polished feel

- [ ] **Input validation**: Client-side validation before submission
  - Min/max ranges for numbers
  - Required fields
  - Format validation (e.g., dates)

### Backend Enhancements

- [ ] **Background job processing**: Long-running tasks shouldn't block UI
  - Celery or RQ for task queue
  - WebSocket or polling for progress updates
  - Job status API endpoints

- [ ] **API endpoints**: RESTful API for programmatic access
  - `/api/recommendations/generate`
  - `/api/library/stats`
  - `/api/settings`
  - Useful for scripting and integrations

- [ ] **Configuration profiles**: Save named setting presets
  - "Obscure discovery" profile
  - "Popular recommendations" profile
  - "Specific genre" profiles
  - Quick switching between use cases

## Design Decisions

- **Lightweight**: No Node.js, no build process, no heavy frameworks
- **Shared logic**: Imports real BeatFinder classes instead of duplicating code
- **Session-based**: Config changes don't require `.env` editing
- **Progressive enhancement**: Works without JavaScript (HTMX degrades gracefully)
- **Responsive**: Mobile-friendly with Tailwind grid layouts
- **Fast**: Debounced updates (100-300ms) prevent excessive requests
- **British English**: Consistent with project guidelines

## Development

### Adding New Features

1. Add route to `app.py` (handle POST/GET, return JSON or template)
2. Create partial template in `templates/partials/` if HTMX swap needed
3. Add JavaScript function in `index.html` if client-side logic needed
4. Update this README checklist when feature is complete

### Testing

```bash
# Start web UI
cd web_prototype
./run.sh

# In another terminal, verify CLI still works
python beatfinder.py --help
python beatfinder.py --limit 10
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"
```bash
cd /Users/samm/git/sammcj/beatfinder
source .venv/bin/activate
pip install Flask==3.1.0
```

### "Last.fm API key not configured"
Ensure `.env` file exists in project root with valid `LASTFM_API_KEY`.

### "No recommendations found"
- Check library has loved/frequently played artists
- Try `--refresh-cache` in CLI to update Last.fm metadata
- Verify library path is correct (Apple export or iTunes XML)

### Web UI shows empty statistics
- Verify `USE_APPLE_EXPORT` and `APPLE_EXPORT_DIR` in `.env`
- Or ensure iTunes Library XML is accessible at default location
- Check console for Python errors

### Changes don't persist between sessions
- This is expected - session settings are temporary
- Use "Export Settings" button to save configuration as JSON
- Or modify `.env` file for permanent changes

## Contributing

Follow the project's coding standards:
- British English spellings (colour, favourite, etc.)
- No placeholder comments or code
- Test both web UI and CLI after changes
- Update this README checklist when completing items

## Future Ideas

- Visual comparison of multiple recommendation runs
- Heatmap showing genre distribution in recommendations
- Integration with Spotify/Apple Music for one-click playlist creation
- Recommendation explanations (why this artist was recommended)
- Social features (share settings, compare tastes with friends)
- Machine learning to learn from accepted/rejected recommendations
