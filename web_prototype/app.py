"""
BeatFinder Web Interface - Flask + HTMX
Integrated with real BeatFinder logic
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import beatfinder modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, jsonify, session, Response, stream_with_context
import json
import queue
import threading
from datetime import datetime, timedelta

# Import real BeatFinder classes
from config import (
    LASTFM_API_KEY,
    USE_APPLE_EXPORT,
    APPLE_EXPORT_DIR,
    MAX_RECOMMENDATIONS,
    RARITY_PREFERENCE,
    KNOWN_ARTIST_MIN_PLAY_COUNT,
    KNOWN_ARTIST_MIN_TRACKS,
    LOVED_PLAY_COUNT_THRESHOLD,
    LOVED_MIN_TRACK_RATING,
    LOVED_MIN_ARTIST_PLAYS,
    LIB_DISLIKED_MIN_TRACK_COUNT,
    ENABLE_TAG_SIMILARITY,
    ENABLE_PLAY_FREQUENCY_WEIGHTING,
    LAST_MONTHS_FILTER,
    LIB_TAG_IGNORE_LIST,
    REC_TAG_BLACKLIST,
    REC_TAG_BLACKLIST_TOP_N_TAGS,
    LIB_ARTISTS_IGNORE,
    REC_ARTISTS_BLACKLIST,
    CREATE_PLAYLIST,
    HTML_VISUALISATION,
    CACHE_DIR,
)
from library_parser import AppleMusicLibrary
from apple_export_parser import AppleMusicExportParser
from recommendation_engine import (
    LastFmClient,
    RecommendationEngine,
    load_recommendations_cache,
    save_recommendations_cache,
)
from interactive_filter import (
    filter_rejected_from_recommendations,
    REJECTED_ARTISTS_FILE,
)

# Run history file
RUN_HISTORY_FILE = Path(__file__).parent.parent / 'data' / 'run_history.json'
RUN_HISTORY_FILE.parent.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = 'beatfinder-web-secret-key-change-in-production'

# All available tags (for tag bucket)
ALL_AVAILABLE_TAGS = [
    'electronic', 'ambient', 'techno', 'house', 'experimental', 'idm', 'minimal',
    'downtempo', 'trip-hop', 'glitch', 'drum and bass', 'dubstep', 'breaks',
    'pop', 'pop rock', 'indie pop', 'synth-pop', 'synthpop', 'dance-pop', 'electropop',
    'dream pop', 'power pop', 'art pop', 'pop punk', 'chamber pop', 'baroque pop',
    'rock', 'indie', 'alternative', 'folk', 'country', 'jazz', 'blues',
    'hip-hop', 'rap', 'r&b', 'soul', 'funk', 'disco', 'reggae', 'ska',
    'metal', 'punk', 'hardcore', 'industrial', 'noise', 'drone', 'dark ambient',
    'classical', 'opera', 'soundtrack', 'score', 'world', 'latin', 'afrobeat',
    'k-pop', 'j-pop', 'christmas', 'holiday', 'instrumental', 'acoustic', 'live',
]


def get_library_parser():
    """Get the appropriate library parser based on configuration"""
    if USE_APPLE_EXPORT:
        if not APPLE_EXPORT_DIR:
            raise ValueError("USE_APPLE_EXPORT is enabled but APPLE_EXPORT_DIR is not set")
        return AppleMusicExportParser(APPLE_EXPORT_DIR)
    else:
        return AppleMusicLibrary()


def save_run_history(config, recommendations_count):
    """Save run to history file"""
    try:
        # Load existing history
        if RUN_HISTORY_FILE.exists():
            with open(RUN_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        else:
            history = []

        # Add new run
        run = {
            'id': len(history) + 1,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'recommendations_count': recommendations_count,
            'settings': {
                'rarity': config['rarity_preference'],
                'max_recommendations': config['max_recommendations'],
                'enable_tag_similarity': config['enable_tag_similarity'],
                'enable_play_frequency_weighting': config['enable_play_frequency_weighting'],
                'time_filter': session.get('time_filter', ''),
            }
        }

        history.insert(0, run)  # Add to beginning (most recent first)

        # Keep only last 50 runs
        history = history[:50]

        # Save
        with open(RUN_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        print(f"Warning: Could not save run history: {e}")


def load_run_history():
    """Load run history from file"""
    try:
        if RUN_HISTORY_FILE.exists():
            with open(RUN_HISTORY_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load run history: {e}")
    return []


def calculate_scoring_weights(rarity):
    """Calculate scoring weights based on rarity preference (1-15)"""
    if rarity <= 5:
        freq_weight = 0.50 - (rarity - 1) * 0.02
        match_weight = 0.40 - (rarity - 1) * 0.02
        rarity_weight = 0.10 + (rarity - 1) * 0.04
    elif rarity <= 10:
        freq_weight = 0.42 - (rarity - 6) * 0.02
        match_weight = 0.35 - (rarity - 6) * 0.02
        rarity_weight = 0.23 + (rarity - 6) * 0.04
    else:
        freq_weight = 0.35 - (rarity - 11) * 0.01
        match_weight = 0.20 - (rarity - 11) * 0.01
        rarity_weight = 0.45 + (rarity - 11) * 0.01

    total = freq_weight + match_weight + rarity_weight

    return {
        'frequency': round(freq_weight / total * 100, 1),
        'match': round(match_weight / total * 100, 1),
        'rarity': round(rarity_weight / total * 100, 1),
    }


def get_current_config():
    """Get current configuration from .env + session overrides"""
    return {
        'max_recommendations': session.get('max_recommendations', MAX_RECOMMENDATIONS),
        'rarity_preference': session.get('rarity_preference', RARITY_PREFERENCE),
        'known_artist_min_play_count': session.get('known_artist_min_play_count', KNOWN_ARTIST_MIN_PLAY_COUNT),
        'known_artist_min_tracks': session.get('known_artist_min_tracks', KNOWN_ARTIST_MIN_TRACKS),
        'loved_play_count_threshold': session.get('loved_play_count_threshold', LOVED_PLAY_COUNT_THRESHOLD),
        'loved_min_track_rating': session.get('loved_min_track_rating', LOVED_MIN_TRACK_RATING),
        'loved_min_artist_plays': session.get('loved_min_artist_plays', LOVED_MIN_ARTIST_PLAYS),
        'LIB_DISLIKED_MIN_TRACK_COUNT': session.get('LIB_DISLIKED_MIN_TRACK_COUNT', LIB_DISLIKED_MIN_TRACK_COUNT),
        'enable_tag_similarity': session.get('enable_tag_similarity', ENABLE_TAG_SIMILARITY),
        'enable_play_frequency_weighting': session.get('enable_play_frequency_weighting', ENABLE_PLAY_FREQUENCY_WEIGHTING),
        'last_months_filter': session.get('last_months_filter', LAST_MONTHS_FILTER),
        'LIB_TAG_IGNORE_LIST': list(session.get('LIB_TAG_IGNORE_LIST', LIB_TAG_IGNORE_LIST)),
        'REC_TAG_BLACKLIST': list(session.get('REC_TAG_BLACKLIST', REC_TAG_BLACKLIST)),
        'REC_TAG_BLACKLIST_TOP_N_TAGS': session.get('REC_TAG_BLACKLIST_TOP_N_TAGS', REC_TAG_BLACKLIST_TOP_N_TAGS),
        'REC_ARTISTS_BLACKLIST': session.get('REC_ARTISTS_BLACKLIST', REC_ARTISTS_BLACKLIST),
        'LIB_ARTISTS_IGNORE': session.get('LIB_ARTISTS_IGNORE', LIB_ARTISTS_IGNORE),
        'CREATE_PLAYLIST': session.get('CREATE_PLAYLIST', CREATE_PLAYLIST),
        'HTML_VISUALISATION': session.get('HTML_VISUALISATION', HTML_VISUALISATION),
        'use_apple_export': USE_APPLE_EXPORT,
        'apple_export_dir': APPLE_EXPORT_DIR,
    }


@app.route('/')
def index():
    """Main configuration page"""
    config = get_current_config()
    weights = calculate_scoring_weights(config['rarity_preference'])

    try:
        library = get_library_parser()
        artist_stats = library.get_artist_stats()
        library_stats = library.get_library_stats()

        # Get loved artists count (lightweight - no Last.fm calls)
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)
        loved_artists = engine.get_loved_artists()

        # Only build tag profile if tag similarity is enabled (this is expensive!)
        tag_profile = {}
        if config['enable_tag_similarity']:
            tag_profile = engine.build_tag_profile(loved_artists)

        # Calculate artist classifications
        known_count = sum(1 for stats in artist_stats.values()
                         if stats['play_count'] >= config['known_artist_min_play_count']
                         or stats.get('track_count', 0) >= config['known_artist_min_tracks'])

        # Count disliked artists (artists with explicit dislike preference and not loved)
        disliked_count = sum(1 for artist, stats in artist_stats.items()
                            if stats.get('disliked', False) and artist not in loved_artists)

        # Build stats
        stats = {
            'total_artists': len(artist_stats),
            'loved_artists': len(loved_artists),
            'known_artists': known_count,
            'disliked_artists': disliked_count,
            'total_plays': library_stats.get('total_plays', sum(s['play_count'] for s in artist_stats.values())),
            'skip_rate': library_stats.get('skip_rate', 0) * 100 if library_stats.get('skip_rate') else 0,
            'oldest_play': library_stats.get('oldest_play', 'N/A'),
            'history_span_days': library_stats.get('history_span_days', 0),
        }

    except Exception as e:
        # Fallback to mock data if library can't be loaded
        print(f"Warning: Could not load library: {e}")
        stats = {
            'total_artists': 0,
            'loved_artists': 0,
            'known_artists': 0,
            'disliked_artists': 0,
            'total_plays': 0,
            'skip_rate': 0,
            'oldest_play': 'N/A',
            'history_span_days': 0,
        }
        tag_profile = {}

    # Get cached recommendations if they exist
    cached_recs = load_recommendations_cache(config['rarity_preference'])
    preview_recs = []
    if cached_recs:
        preview_recs = cached_recs[:5]

    # Load run history
    run_history = load_run_history()

    return render_template('index.html',
                         config=config,
                         weights=weights,
                         library_stats=stats,
                         tag_profile=tag_profile,
                         all_tags=sorted(ALL_AVAILABLE_TAGS),
                         previous_runs=run_history[:10],  # Show last 10 runs
                         preview_recommendations=preview_recs)


@app.route('/update-weights', methods=['POST'])
def update_weights():
    """Update scoring weights based on rarity preference"""
    rarity = int(request.form.get('rarity', 8))
    session['rarity_preference'] = rarity
    weights = calculate_scoring_weights(rarity)
    return render_template('partials/weight_chart.html', weights=weights, rarity=rarity)


@app.route('/update-artist-stats', methods=['POST'])
def update_artist_stats():
    """Update artist classification statistics based on threshold changes"""
    known_play_count = int(request.form.get('known_play_count', KNOWN_ARTIST_MIN_PLAY_COUNT))
    loved_play_count = int(request.form.get('loved_play_count', LOVED_PLAY_COUNT_THRESHOLD))

    session['known_artist_min_play_count'] = known_play_count
    session['loved_play_count_threshold'] = loved_play_count

    try:
        library = get_library_parser()
        artist_stats = library.get_artist_stats()

        # Use RecommendationEngine to get accurate loved artists count
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)
        loved_artists = engine.get_loved_artists()

        # Get current track threshold from config
        track_threshold = session.get('known_artist_min_tracks', KNOWN_ARTIST_MIN_TRACKS)

        # Recalculate classifications with new thresholds (must match RecommendationEngine logic)
        known_count = sum(1 for stats in artist_stats.values()
                         if stats['play_count'] >= known_play_count
                         or stats.get('track_count', 0) >= track_threshold)
        disliked_count = sum(1 for artist, stats in artist_stats.items()
                            if stats.get('disliked', False) and artist not in loved_artists)

        stats = {
            'loved_artists': len(loved_artists),
            'known_artists': known_count,
            'disliked_artists': disliked_count,
        }
    except Exception as e:
        print(f"Warning: Could not update stats: {e}")
        stats = {
            'loved_artists': 0,
            'known_artists': 0,
            'disliked_artists': 0,
        }

    return render_template('partials/artist_stats.html', stats=stats)


@app.route('/update-tag-profile', methods=['POST'])
def update_tag_profile():
    """Update tag profile visualisation"""
    enable_tags = request.form.get('enable_tag_similarity') == 'true'
    ignore_list_str = request.form.get('tag_ignore_list', '')
    blacklist_str = request.form.get('REC_TAG_BLACKLIST', '')

    # Parse tag lists
    ignore_list = [t.strip().lower() for t in ignore_list_str.split(',') if t.strip()]
    blacklist = [t.strip().lower() for t in blacklist_str.split(',') if t.strip()]

    session['enable_tag_similarity'] = enable_tags
    session['LIB_TAG_IGNORE_LIST'] = ignore_list
    session['REC_TAG_BLACKLIST'] = blacklist

    try:
        library = get_library_parser()
        artist_stats = library.get_artist_stats()
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)
        loved_artists = engine.get_loved_artists()
        tag_profile = engine.build_tag_profile(loved_artists)

        # Filter out ignored tags
        filtered_tags = {
            tag: count for tag, count in tag_profile.items()
            if tag not in ignore_list
        }
    except Exception as e:
        print(f"Warning: Could not build tag profile: {e}")
        filtered_tags = {}

    return render_template('partials/tag_cloud.html',
                         tag_profile=filtered_tags,
                         blacklisted_tags=blacklist,
                         enabled=enable_tags)


@app.route('/preview-recommendations', methods=['POST'])
def preview_recommendations():
    """Generate preview of recommendations with current settings"""
    config = get_current_config()
    rarity = config['rarity_preference']

    # Try to load from cache first
    cached_recs = load_recommendations_cache(rarity)
    if cached_recs:
        recs = cached_recs[:5]
    else:
        recs = []

    return render_template('partials/preview_results.html', recommendations=recs)


@app.route('/update-impact-meter', methods=['POST'])
def update_impact_meter():
    """Calculate recommendation scope impact"""
    blacklist_str = request.form.get('REC_TAG_BLACKLIST', '')
    blacklist_count = len([t for t in blacklist_str.split(',') if t.strip()])
    time_filter = int(request.form.get('last_months_filter', 0))
    loved_threshold = int(request.form.get('loved_play_count', LOVED_PLAY_COUNT_THRESHOLD))

    narrowness = 0
    narrowness += min(blacklist_count * 15, 40)
    narrowness += min(time_filter * 2, 30)
    narrowness += min((loved_threshold - 20) // 5 * 5, 30)
    narrowness = min(narrowness, 100)

    impact_text = (
        "Very Narrow" if narrowness > 70 else
        "Narrow" if narrowness > 50 else
        "Balanced" if narrowness > 30 else
        "Broad" if narrowness > 15 else
        "Very Broad"
    )

    return render_template('partials/impact_meter.html',
                         narrowness=narrowness,
                         impact_text=impact_text)


@app.route('/generate-recommendations-stream', methods=['GET'])
def generate_recommendations_stream():
    """Generate recommendations with real-time progress updates via SSE"""
    config = get_current_config()

    # Get time filter from request args (GET params)
    time_filter = request.args.get('time_filter', '')

    # Store in session
    session['time_filter'] = time_filter

    def generate():
        progress_queue = queue.Queue()
        result_holder = {'success': False, 'data': None, 'error': None}

        def progress_callback(event_type, message, current=0, total=0):
            """Callback for progress updates"""
            progress_queue.put({
                'type': event_type,
                'message': message,
                'current': current,
                'total': total,
                'percent': int((current / total * 100)) if total > 0 else 0
            })

        def run_generation():
            """Run recommendation generation in background thread"""
            try:
                # Get library and create engine
                library = get_library_parser()
                artist_stats = library.get_artist_stats()
                library_stats = library.get_library_stats()

                # Filter artist stats by time range if provided
                if time_filter:
                    from datetime import datetime, timedelta

                    # Calculate cutoff date
                    cutoff_date = None
                    if time_filter == '7d':
                        cutoff_date = datetime.now() - timedelta(days=7)
                    elif time_filter == '1m':
                        cutoff_date = datetime.now() - timedelta(days=30)
                    elif time_filter == '3m':
                        cutoff_date = datetime.now() - timedelta(days=90)
                    elif time_filter == '6m':
                        cutoff_date = datetime.now() - timedelta(days=180)
                    elif time_filter == '12m':
                        cutoff_date = datetime.now() - timedelta(days=365)
                    elif time_filter == '2y':
                        cutoff_date = datetime.now() - timedelta(days=730)
                    elif time_filter == '5y':
                        cutoff_date = datetime.now() - timedelta(days=1825)

                    if cutoff_date:
                        filtered_stats = {}

                        for artist, stats in artist_stats.items():
                            last_played = stats.get('last_played')
                            if not last_played:
                                continue

                            try:
                                if isinstance(last_played, str):
                                    last_played_date = datetime.fromisoformat(last_played.replace('Z', '+00:00'))
                                else:
                                    last_played_date = last_played

                                if last_played_date >= cutoff_date:
                                    filtered_stats[artist] = stats
                            except (ValueError, AttributeError):
                                # Include artists with invalid/missing dates
                                filtered_stats[artist] = stats

                        artist_stats = filtered_stats

                lastfm = LastFmClient(LASTFM_API_KEY)
                engine = RecommendationEngine(artist_stats, lastfm, progress_callback=progress_callback)

                # Generate recommendations
                recommendations = engine.generate_recommendations(rarity_pref=config['rarity_preference'])

                if not recommendations:
                    result_holder['success'] = False
                    result_holder['error'] = 'No recommendations found. Try adjusting your settings or date range.'
                    return

                # Filter rejected artists
                recommendations = filter_rejected_from_recommendations(recommendations)

                # Save to cache
                loved_artists = engine.get_loved_artists()
                save_recommendations_cache(recommendations, loved_artists, config['rarity_preference'])

                # Save to run history
                save_run_history(config, len(recommendations))

                result_holder['success'] = True
                result_holder['data'] = {
                    'count': len(recommendations),
                    'preview': recommendations[:5],
                    'filtered_artists': len(artist_stats) if time_filter else None,
                    'time_filter': time_filter
                }

            except Exception as e:
                result_holder['success'] = False
                result_holder['error'] = str(e)
            finally:
                progress_queue.put(None)  # Signal completion

        # Start generation in background thread
        thread = threading.Thread(target=run_generation)
        thread.start()

        # Stream progress updates
        while True:
            try:
                progress = progress_queue.get(timeout=30)
                if progress is None:  # Completion signal
                    break
                yield f"data: {json.dumps(progress)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

        # Send final result
        if result_holder['success']:
            yield f"data: {json.dumps({'type': 'complete', 'data': result_holder['data']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'error': result_holder['error']})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/clear-cache', methods=['POST'])
def clear_cache():
    """Clear all caches"""
    cache_type = request.form.get('cache_type', 'all')

    try:
        if cache_type in ['all', 'lastfm']:
            lastfm_cache = CACHE_DIR / "lastfm_cache.json"
            if lastfm_cache.exists():
                lastfm_cache.unlink()

        if cache_type in ['all', 'recommendations']:
            recommendations_cache = CACHE_DIR / "recommendations_cache.json"
            if recommendations_cache.exists():
                recommendations_cache.unlink()

        if cache_type == 'rejected':
            if REJECTED_ARTISTS_FILE.exists():
                REJECTED_ARTISTS_FILE.unlink()

        return jsonify({'success': True, 'message': f'{cache_type.capitalize()} cache cleared'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/scan-library', methods=['POST'])
def scan_library():
    """Force re-scan of library"""
    try:
        library = get_library_parser()
        artist_stats = library.get_artist_stats(force_refresh=True)

        return jsonify({
            'success': True,
            'artist_count': len(artist_stats)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/get-results-markdown', methods=['GET'])
def get_results_markdown():
    """Get recommendations in markdown format"""
    config = get_current_config()

    try:
        # Load cached recommendations
        cached_recs = load_recommendations_cache(config['rarity_preference'])
        if not cached_recs:
            return jsonify({
                'success': False,
                'error': 'No recommendations found. Generate recommendations first.'
            })

        # Get library stats
        library = get_library_parser()
        artist_stats = library.get_artist_stats()
        library_stats = library.get_library_stats()

        # Build markdown
        from datetime import datetime
        markdown = []
        markdown.append("# BeatFinder Recommendations\n")
        markdown.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        markdown.append(f"**Settings:** Rarity {config['rarity_preference']}, {len(cached_recs)} recommendations\n")

        # Library statistics
        markdown.append("\n## Library Statistics\n")
        markdown.append(f"- **Total Artists:** {len(artist_stats)}\n")

        # Use RecommendationEngine for accurate counts
        lastfm = LastFmClient(LASTFM_API_KEY)
        engine = RecommendationEngine(artist_stats, lastfm)
        loved_artists = engine.get_loved_artists()

        loved_count = len(loved_artists)
        known_count = sum(1 for stats in artist_stats.values()
                         if stats['play_count'] >= config['known_artist_min_play_count']
                         or stats.get('track_count', 0) >= config['known_artist_min_tracks'])
        disliked_count = sum(1 for artist, stats in artist_stats.items()
                            if stats.get('disliked', False) and artist not in loved_artists)

        markdown.append(f"- **Loved Artists:** {loved_count}\n")
        markdown.append(f"- **Known Artists:** {known_count}\n")
        markdown.append(f"- **Disliked Artists:** {disliked_count}\n")

        if library_stats:
            markdown.append(f"- **Total Plays:** {library_stats.get('total_plays', 0):,}\n")
            if library_stats.get('skip_rate'):
                markdown.append(f"- **Skip Rate:** {library_stats['skip_rate'] * 100:.1f}%\n")
            if library_stats.get('oldest_play'):
                markdown.append(f"- **Listening History:** {library_stats['oldest_play']} to present ({library_stats.get('history_span_days', 0)} days)\n")

        # Recommendations
        markdown.append("\n## Recommended Artists\n")
        for i, rec in enumerate(cached_recs, 1):
            markdown.append(f"\n### {i}. {rec['name']}\n")
            markdown.append(f"**Score:** {rec['score']:.2f} | ")
            markdown.append(f"**Match:** {rec['match_score']:.2f} | ")
            markdown.append(f"**Listeners:** {rec['listeners']:,}\n")

            if rec.get('tags'):
                markdown.append(f"**Tags:** {', '.join(rec['tags'][:5])}\n")

            if rec.get('recommended_by'):
                markdown.append(f"**Recommended by:** {', '.join(rec['recommended_by'][:5])}")
                if len(rec['recommended_by']) > 5:
                    markdown.append(f" (+{len(rec['recommended_by']) - 5} more)")
                markdown.append("\n")

        return jsonify({
            'success': True,
            'markdown': ''.join(markdown),
            'count': len(cached_recs)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/get-visualisation', methods=['GET'])
def get_visualisation():
    """Get HTML visualisation if it exists"""
    viz_path = Path(__file__).parent.parent / 'recommendations_visualisation.html'

    if viz_path.exists():
        with open(viz_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return jsonify({
            'success': True,
            'html': html_content
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Visualisation not found. Enable HTML_VISUALISATION and regenerate recommendations.'
        })


@app.route('/export-settings', methods=['POST'])
def export_settings():
    """Export current settings as JSON"""
    config = get_current_config()
    return jsonify(config)


@app.route('/import-settings', methods=['POST'])
def import_settings():
    """Import settings from JSON"""
    try:
        settings = request.json

        # Update session with imported settings
        for key, value in settings.items():
            session[key] = value

        return jsonify({
            'success': True,
            'message': 'Settings imported successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/get-run-history', methods=['GET'])
def get_run_history():
    """Get all run history"""
    history = load_run_history()
    return jsonify({'success': True, 'runs': history[:10]})


@app.route('/load-run-settings/<int:run_id>', methods=['POST'])
def load_run_settings(run_id):
    """Load settings from a specific run"""
    try:
        history = load_run_history()
        run = next((r for r in history if r['id'] == run_id), None)

        if not run:
            return jsonify({'success': False, 'error': 'Run not found'})

        # Load settings into session
        settings = run['settings']
        session['rarity_preference'] = settings.get('rarity', RARITY_PREFERENCE)
        session['max_recommendations'] = settings.get('max_recommendations', MAX_RECOMMENDATIONS)
        session['enable_tag_similarity'] = settings.get('enable_tag_similarity', ENABLE_TAG_SIMILARITY)
        session['enable_play_frequency_weighting'] = settings.get('enable_play_frequency_weighting', ENABLE_PLAY_FREQUENCY_WEIGHTING)
        session['time_filter'] = settings.get('time_filter', '')

        return jsonify({
            'success': True,
            'message': 'Settings loaded from run history'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/reset-to-defaults', methods=['POST'])
def reset_to_defaults():
    """Clear session to reset all settings to .env defaults"""
    try:
        # Clear the entire session
        session.clear()
        return jsonify({
            'success': True,
            'message': 'Settings reset to defaults'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/save-tags-to-env', methods=['POST'])
def save_tags_to_env():
    """Save tag blacklist, ignore list, and top N setting to .env file"""
    try:
        REC_TAG_BLACKLIST = request.json.get('REC_TAG_BLACKLIST', [])
        tag_ignore_list = request.json.get('tag_ignore_list', [])
        tag_blacklist_top_n = request.json.get('tag_blacklist_top_n', '0')

        # Convert to "all" if 0
        top_n_value = 'all' if str(tag_blacklist_top_n) == '0' else str(tag_blacklist_top_n)

        # Find .env file
        env_path = Path(__file__).parent.parent / '.env'

        if not env_path.exists():
            return jsonify({
                'success': False,
                'error': '.env file not found. Please create one from .env.example'
            })

        # Read current .env contents
        with open(env_path, 'r') as f:
            lines = f.readlines()

        # Update the tag lines
        updated_lines = []
        blacklist_updated = False
        ignore_updated = False
        top_n_updated = False

        for line in lines:
            if line.startswith('REC_TAG_BLACKLIST='):
                updated_lines.append(f'REC_TAG_BLACKLIST={",".join(REC_TAG_BLACKLIST)}\n')
                blacklist_updated = True
            elif line.startswith('LIB_TAG_IGNORE_LIST='):
                updated_lines.append(f'LIB_TAG_IGNORE_LIST={",".join(tag_ignore_list)}\n')
                ignore_updated = True
            elif line.startswith('REC_TAG_BLACKLIST_TOP_N_TAGS='):
                updated_lines.append(f'REC_TAG_BLACKLIST_TOP_N_TAGS={top_n_value}\n')
                top_n_updated = True
            else:
                updated_lines.append(line)

        # If tags weren't found, append them
        if not blacklist_updated:
            updated_lines.append(f'\nTAG_BLACKLIST={",".join(REC_TAG_BLACKLIST)}\n')
        if not ignore_updated:
            updated_lines.append(f'LIB_TAG_IGNORE_LIST={",".join(tag_ignore_list)}\n')
        if not top_n_updated:
            updated_lines.append(f'REC_TAG_BLACKLIST_TOP_N_TAGS={top_n_value}\n')

        # Write back to .env
        with open(env_path, 'w') as f:
            f.writelines(updated_lines)

        return jsonify({
            'success': True,
            'message': 'Tags saved to .env file'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to save to .env: {str(e)}'
        })


if __name__ == '__main__':
    # Validate API key
    if not LASTFM_API_KEY or LASTFM_API_KEY == "your_api_key_here":
        print("Error: Last.fm API key not configured")
        print("1. Get an API key from: https://www.last.fm/api/account/create")
        print("2. Copy .env.example to .env")
        print("3. Add your API key to .env")
        sys.exit(1)

    app.run(debug=False, port=5001)
