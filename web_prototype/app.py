"""
BeatFinder Web Prototype - Flask + HTMX
Frontend-only prototype with mock data
"""

from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime, timedelta

app = Flask(__name__)

# Real configuration defaults (from .env.example)
DEFAULT_CONFIG = {
    'max_recommendations': 60,
    'rarity_preference': 8,
    'known_artist_min_play_count': 2,
    'known_artist_min_tracks': 3,
    'loved_play_count_threshold': 20,
    'loved_min_track_rating': 4,  # 1-5 scale
    'loved_min_artist_plays': 10,
    'disliked_min_track_count': 2,
    'enable_tag_similarity': False,
    'enable_play_frequency_weighting': False,
    'last_months_filter': 0,
    'tag_similarity_ignore_list': ['pop', 'popular', 'christmas', 'instrumental', 'soundtrack', 'classical', 'live', 'acoustic', 'american', 'singer-songwriter', 'experimental', 'female vocalists', 'male vocalists', 'alternative', 'indie', 'indie rock', 'usa'],
    'tag_blacklist': ['pop', 'k-pop', 'kpop'],
    'artist_blacklist': [],  # Artists to never recommend
    'exclude_from_taste_profile': [],  # Artists in library to exclude from taste profile generation
    'create_apple_music_playlist': True,
    'generate_html_visualisation': True,
    'use_apple_export': False,
    'apple_export_dir': '$HOME/Downloads/Apple Media Services information Part 1 of 2/Apple_Media_Services/Apple Music Activity/',
}

# Mock library statistics
MOCK_LIBRARY_STATS = {
    'total_artists': 438,
    'loved_artists': 42,
    'known_artists': 315,
    'disliked_artists': 8,
    'total_plays': 12847,
    'skip_rate': 0.12,
    'oldest_play': '2018-03-15',
    'history_span_days': 2058,
}

# Mock top tags from loved artists
MOCK_TAG_PROFILE = {
    'electronic': 28,
    'ambient': 22,
    'experimental': 18,
    'techno': 15,
    'house': 12,
    'idm': 10,
    'minimal': 8,
    'downtempo': 7,
    'trip-hop': 6,
    'glitch': 5,
}

# All available tags (for tag bucket)
ALL_AVAILABLE_TAGS = [
    'electronic', 'ambient', 'techno', 'house', 'experimental', 'idm', 'minimal',
    'downtempo', 'trip-hop', 'glitch', 'drum and bass', 'dubstep', 'breaks',
    'pop', 'rock', 'indie', 'alternative', 'folk', 'country', 'jazz', 'blues',
    'hip-hop', 'rap', 'r&b', 'soul', 'funk', 'disco', 'reggae', 'ska',
    'metal', 'punk', 'hardcore', 'industrial', 'noise', 'drone', 'dark ambient',
    'classical', 'opera', 'soundtrack', 'score', 'world', 'latin', 'afrobeat',
    'k-pop', 'j-pop', 'christmas', 'holiday', 'instrumental', 'acoustic', 'live',
]

# Mock recommendation previews
MOCK_RECOMMENDATIONS = [
    {'name': 'Rival Consoles', 'score': 0.89, 'listeners': 45000, 'tags': ['electronic', 'ambient', 'idm']},
    {'name': 'Nils Frahm', 'score': 0.85, 'listeners': 280000, 'tags': ['ambient', 'modern classical', 'piano']},
    {'name': 'Kiasmos', 'score': 0.82, 'listeners': 120000, 'tags': ['electronic', 'ambient', 'minimal']},
    {'name': 'Ólafur Arnalds', 'score': 0.78, 'listeners': 340000, 'tags': ['ambient', 'neo-classical', 'electronic']},
    {'name': 'Jon Hopkins', 'score': 0.76, 'listeners': 410000, 'tags': ['electronic', 'ambient', 'techno']},
]

# Mock previous runs
MOCK_PREVIOUS_RUNS = [
    {
        'id': 'run_001',
        'timestamp': (datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S'),
        'settings': {
            'rarity': 8,
            'max_recs': 60,
            'tag_similarity': False,
        },
        'recommendations_count': 60,
        'status': 'completed',
    },
    {
        'id': 'run_002',
        'timestamp': (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
        'settings': {
            'rarity': 10,
            'max_recs': 50,
            'tag_similarity': True,
        },
        'recommendations_count': 50,
        'status': 'completed',
    },
    {
        'id': 'run_003',
        'timestamp': (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S'),
        'settings': {
            'rarity': 5,
            'max_recs': 30,
            'tag_similarity': False,
        },
        'recommendations_count': 30,
        'status': 'completed',
    },
]


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


@app.route('/')
def index():
    """Main configuration page"""
    weights = calculate_scoring_weights(DEFAULT_CONFIG['rarity_preference'])
    return render_template('index.html',
                         config=DEFAULT_CONFIG,
                         weights=weights,
                         library_stats=MOCK_LIBRARY_STATS,
                         tag_profile=MOCK_TAG_PROFILE,
                         all_tags=sorted(ALL_AVAILABLE_TAGS),
                         previous_runs=MOCK_PREVIOUS_RUNS)


@app.route('/update-weights', methods=['POST'])
def update_weights():
    """Update scoring weights based on rarity preference"""
    rarity = int(request.form.get('rarity', 8))
    weights = calculate_scoring_weights(rarity)
    return render_template('partials/weight_chart.html', weights=weights, rarity=rarity)


@app.route('/update-artist-stats', methods=['POST'])
def update_artist_stats():
    """Update artist classification statistics based on threshold changes"""
    known_play_count = int(request.form.get('known_play_count', 2))
    loved_play_count = int(request.form.get('loved_play_count', 20))

    # Mock calculation: adjust counts based on thresholds
    # Lower thresholds = more artists in category
    loved_artists = max(15, 55 - (loved_play_count - 20) // 2)
    known_artists = max(200, 350 - (known_play_count - 2) * 15)

    stats = {
        'loved_artists': loved_artists,
        'known_artists': known_artists,
        'disliked_artists': MOCK_LIBRARY_STATS['disliked_artists'],
    }

    return render_template('partials/artist_stats.html', stats=stats)


@app.route('/update-tag-profile', methods=['POST'])
def update_tag_profile():
    """Update tag profile visualisation"""
    enable_tags = request.form.get('enable_tag_similarity') == 'true'
    ignore_list_str = request.form.get('tag_ignore_list', '')
    blacklist_str = request.form.get('tag_blacklist', '')

    # Parse tag lists
    ignore_list = [t.strip() for t in ignore_list_str.split(',') if t.strip()] if ignore_list_str else []
    blacklist = [t.strip() for t in blacklist_str.split(',') if t.strip()] if blacklist_str else []

    # Filter tag profile based on ignore list
    filtered_tags = {
        tag: count for tag, count in MOCK_TAG_PROFILE.items()
        if tag not in ignore_list
    }

    return render_template('partials/tag_cloud.html',
                         tag_profile=filtered_tags,
                         blacklisted_tags=blacklist,
                         enabled=enable_tags)


@app.route('/preview-recommendations', methods=['POST'])
def preview_recommendations():
    """Generate preview of recommendations with current settings"""
    rarity = int(request.form.get('rarity', 8))
    max_recs = int(request.form.get('max_recommendations', 60))

    # Mock: adjust recommendation scores/ordering based on rarity
    recs = sorted(MOCK_RECOMMENDATIONS,
                  key=lambda x: x['score'] - (x['listeners'] / 1000000) * (rarity / 15),
                  reverse=True)[:min(5, max_recs)]

    return render_template('partials/preview_results.html', recommendations=recs)


@app.route('/update-impact-meter', methods=['POST'])
def update_impact_meter():
    """Calculate recommendation scope impact"""
    blacklist_str = request.form.get('tag_blacklist', '')
    blacklist_count = len([t for t in blacklist_str.split(',') if t.strip()]) if blacklist_str else 0
    time_filter = int(request.form.get('last_months_filter', 0))
    loved_threshold = int(request.form.get('loved_play_count', 20))

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


@app.route('/run-details/<run_id>')
def run_details(run_id):
    """Get details for a specific previous run"""
    # Find the run
    run = next((r for r in MOCK_PREVIOUS_RUNS if r['id'] == run_id), None)
    if not run:
        return "Run not found", 404

    # Mock full recommendations for this run
    mock_full_recs = [
        {'name': 'Artist ' + str(i), 'score': 0.9 - i * 0.05, 'listeners': 50000 * (10 - i), 'tags': ['electronic', 'ambient']}
        for i in range(10)
    ]

    return render_template('partials/run_details.html', run=run, recommendations=mock_full_recs)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
