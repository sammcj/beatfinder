# BeatFinder Web Interface Prototype

Frontend-only prototype demonstrating Flask + HTMX + Tailwind CSS for BeatFinder configuration UI.

## What This Is

A standalone prototype showcasing:

- **Clean, modern UI** built with Tailwind CSS
- **Dynamic, reactive controls** using HTMX (no JavaScript framework needed)
- **Real-time visualisations** showing how settings affect recommendations:
  - Scoring weight distribution (doughnut chart)
  - Artist classification statistics (loved/known/disliked counts)
  - Taste profile tag cloud
  - Recommendation scope impact metre
  - Live preview of top recommendations

All using **mock data** - no actual library parsing or Last.fm API calls yet.

## Key Features Demonstrated

1. **Rarity slider** → Live weight distribution chart updates
2. **Threshold sliders** → Artist classification counts update dynamically
3. **Tag controls** → Tag cloud filters blacklisted/ignored tags
4. **Impact metre** → Visual indicator of how narrow/broad your settings are
5. **Preview panel** → Top 5 recommendations adjust as you change rarity

## Architecture

- **Flask**: Lightweight Python web server (~3MB)
- **HTMX**: Dynamic HTML updates via AJAX (~14KB, CDN)
- **Tailwind CSS**: Utility-first styling (CDN)
- **Chart.js**: Lightweight charts (~200KB, CDN)

Total dependencies: Just Flask. Everything else loads from CDN.

## Running the Prototype

**Quick Start:**
```bash
cd web_prototype
./run.sh
```

**Manual Start:**
```bash
cd web_prototype

# Install Flask (if needed)
pip install -r requirements.txt

# Run the server
python app.py
```

Open http://localhost:5001 in your browser.

## What Works

- ✅ All sliders update visualisations in real-time
- ✅ Tag blacklist/ignore list filtering
- ✅ Artist classification threshold adjustments
- ✅ Scoring weight distribution based on rarity
- ✅ Recommendation scope impact calculation
- ✅ Responsive design (works on mobile)

## What's Mock Data

- Library statistics (total artists, plays, etc.)
- Artist classification counts (loved/known/disliked)
- Tag profile from "loved" artists
- Top 5 recommendation previews
- All settings changes

## Next Steps (If Approved)

If you like the frontend, we can wire it up to the real BeatFinder engine:

1. Import actual `Config`, `AppleMusicExportParser`, `RecommendationEngine`
2. Replace mock data with real library statistics
3. Add "Generate Recommendations" button that runs the full pipeline
4. Display real results with interactive filtering
5. Integrate with existing CLI (keep both working)

## File Structure

```
web_prototype/
├── app.py                          # Flask routes with mock data
├── requirements.txt                # Just Flask
├── templates/
│   ├── base.html                  # Base layout (Tailwind + HTMX)
│   ├── index.html                 # Main config page
│   └── partials/                  # HTMX-swapped fragments
│       ├── weight_chart.html      # Scoring weights doughnut
│       ├── artist_stats.html      # Classification counts
│       ├── tag_cloud.html         # Tag profile visualisation
│       ├── impact_meter.html      # Scope impact gauge
│       └── preview_results.html   # Top recommendations
└── README.md
```

## Design Decisions

- **Lightweight**: No Node.js, no build process, no heavy frameworks
- **Accessible**: Proper ARIA labels, keyboard navigation, colour contrast
- **Progressive enhancement**: Works without JS, enhanced with HTMX
- **Responsive**: Mobile-friendly grid layouts with Tailwind
- **Fast**: Debounced updates (200-500ms) prevent excessive requests

## Screenshots

*(Try it yourself! Start the server and explore.)*

## Customisation Ideas

The prototype makes it easy to:

- Adjust colours (Tailwind colour palette)
- Change chart types (Chart.js supports bar, line, radar, etc.)
- Add more visualisations (listener distribution, genre breakdown)
- Tweak debounce timings for responsiveness
- Add animations/transitions
