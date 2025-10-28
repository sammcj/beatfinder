#!/usr/bin/env python3
"""
Interactive filtering for BeatFinder recommendations
Allows users to review and reject recommendations before saving
"""

import json
from pathlib import Path
from typing import Dict, List, Set

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from config import CACHE_DIR

# Cache file for rejected artists
REJECTED_ARTISTS_CACHE = CACHE_DIR / "rejected_artists.json"


def load_rejected_artists() -> Set[str]:
    """Load the set of rejected artist names from cache"""
    if not REJECTED_ARTISTS_CACHE.exists():
        return set()

    try:
        with open(REJECTED_ARTISTS_CACHE, 'r') as f:
            data = json.load(f)
            return set(data.get('rejected_artists', []))
    except (json.JSONDecodeError, KeyError):
        return set()


def save_rejected_artists(rejected: Set[str]):
    """Save the set of rejected artist names to cache"""
    with open(REJECTED_ARTISTS_CACHE, 'w') as f:
        json.dump({
            'rejected_artists': sorted(list(rejected))
        }, f, indent=2)


def filter_rejected_from_recommendations(recommendations: List[Dict]) -> List[Dict]:
    """
    Filter out previously rejected artists from recommendations

    Args:
        recommendations: List of recommendation dicts with 'name' field

    Returns:
        Filtered list of recommendations
    """
    rejected = load_rejected_artists()
    if not rejected:
        return recommendations

    # Normalise artist names for case-insensitive matching
    rejected_lower = {name.lower() for name in rejected}
    filtered = [rec for rec in recommendations if rec['name'].lower() not in rejected_lower]

    removed_count = len(recommendations) - len(filtered)
    if removed_count > 0:
        print(f"Filtered out {removed_count} previously rejected artist(s)")

    return filtered


def show_interactive_filter(recommendations: List[Dict], limit: int) -> List[Dict]:
    """
    Show interactive TUI menu for selecting artists to keep or reject

    Args:
        recommendations: List of recommendation dicts
        limit: Maximum number of recommendations to show

    Returns:
        List of recommendations to keep (user-approved)
    """
    if not recommendations:
        return recommendations

    # Limit to specified number for display
    display_recommendations = recommendations[:limit]

    print("\n" + "="*60)
    print("Review Recommendations")
    print("="*60)
    print("Use SPACE to toggle selection, ENTER to confirm")
    print("Deselected artists will be permanently rejected")
    print("="*60 + "\n")

    # Build choices with all artists pre-selected
    choices = []
    for i, rec in enumerate(display_recommendations, 1):
        # Format the choice label with artist info
        score_str = f"{rec['score']:.2f}"
        listeners_str = f"{rec['listeners']:,}"
        tags = ', '.join(rec['tags'][:3]) if rec['tags'] else 'no tags'

        label = f"{i:2d}. {rec['name']:<30} | Score: {score_str:<6} | Listeners: {listeners_str:<10} | {tags}"

        # Create choice with artist name as value, pre-selected
        choices.append(Choice(value=rec['name'], name=label, enabled=True))

    # Show interactive checkbox menu
    selected_artists = inquirer.checkbox(
        message="Select artists to keep (deselected will be rejected):",
        choices=choices,
        transformer=lambda result: f"{len(result)}/{len(choices)} artists selected",
        instruction="(SPACE to toggle, ENTER to confirm, Ctrl+C to keep all)",
    ).execute()

    # Load existing rejected artists
    rejected = load_rejected_artists()

    # Track newly rejected artists
    newly_rejected = []
    all_artist_names = {rec['name'] for rec in display_recommendations}
    selected_set = set(selected_artists)

    for artist_name in all_artist_names:
        if artist_name not in selected_set:
            rejected.add(artist_name)
            newly_rejected.append(artist_name)

    # Save updated rejected list
    if newly_rejected:
        save_rejected_artists(rejected)
        print(f"\n{len(newly_rejected)} artist(s) rejected and cached:")
        for name in newly_rejected:
            print(f"  - {name}")

    # Filter recommendations to only include selected artists
    kept_recommendations = [rec for rec in recommendations if rec['name'] in selected_set]

    print(f"\n{len(kept_recommendations)} artist(s) kept for recommendations")

    return kept_recommendations
