#!/usr/bin/env python3
"""
Last.fm API client and recommendation engine
"""

import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List

import requests

from config import (
    CACHE_DIR,
    CACHE_EXPIRY_DAYS,
    LIB_DISLIKED_MIN_TRACK_COUNT,
    ENABLE_PLAY_FREQUENCY_WEIGHTING,
    ENABLE_TAG_SIMILARITY,
    KNOWN_ARTIST_MIN_PLAY_COUNT,
    KNOWN_ARTIST_MIN_TRACKS,
    LAST_MONTHS_FILTER,
    LOVED_MIN_ARTIST_PLAYS,
    LOVED_MIN_TRACK_RATING,
    LOVED_PLAY_COUNT_THRESHOLD,
    MAX_CONCURRENT_REQUESTS,
    MAX_REQUESTS_PER_SECOND,
    REC_CACHE_EXPIRY_DAYS,
    SCORING_FREQUENCY_WEIGHT,
    SCORING_MATCH_WEIGHT,
    SCORING_RARITY_WEIGHT,
    SCORING_TAG_OVERLAP_WEIGHT,
    REC_TAG_BLACKLIST,
    REC_TAG_BLACKLIST_TOP_N_TAGS,
    LIB_TAG_IGNORE_LIST,
)


class RateLimiter:
    """Thread-safe rate limiter to ensure we don't exceed API limits"""

    def __init__(self, max_per_second: int):
        self.max_per_second = max_per_second
        self.min_interval = 1.0 / max_per_second
        self.last_request_time = 0
        self.lock = threading.Lock()

    def acquire(self):
        """Wait if necessary to respect rate limit"""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)

            self.last_request_time = time.time()


class LastFmClient:
    """Last.fm API client with caching"""

    BASE_URL = "http://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: str):
        if not api_key or api_key == "your_api_key_here":
            print("\nError: Last.fm API key not configured!")
            print("\nPlease set up your API key:")
            print("1. Get a free API key at: https://www.last.fm/api/account/create")
            print("2. Copy .env.example to .env")
            print("3. Edit .env and add your API key to LASTFM_API_KEY")
            sys.exit(1)

        self.api_key = api_key
        self.session = requests.Session()
        self.cache_file = CACHE_DIR / "lastfm_cache.json"
        self.cache_lock = threading.Lock()
        self.rate_limiter = RateLimiter(MAX_REQUESTS_PER_SECOND)
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """Load cached API responses"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                    cache_time = datetime.fromisoformat(cache.get("timestamp", "2000-01-01"))
                    if datetime.now() - cache_time < timedelta(days=CACHE_EXPIRY_DAYS):
                        return cache
            except Exception:
                pass
        return {"timestamp": datetime.now().isoformat(), "data": {}}

    def _save_cache(self):
        """Save cache to disk (thread-safe)"""
        with self.cache_lock:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)

    def _make_request(self, params: Dict) -> Dict:
        """Make API request with global rate limiting"""
        params["api_key"] = self.api_key
        params["format"] = "json"

        try:
            self.rate_limiter.acquire()
            response = self.session.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
        except json.JSONDecodeError as e:
            print(f"\nError: Failed to parse Last.fm API response as JSON")
            print(f"Response content: {response.text[:200]}")
            print(f"\nThis usually means your Last.fm API key is missing or invalid.")
            print(f"Please check your .env file and ensure LASTFM_API_KEY is set correctly.")
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"API request failed: {e}")
            return {}

    def get_similar_artists(self, artist_name: str, limit: int = 20) -> List[Dict]:
        """Get similar artists from Last.fm (thread-safe)"""
        cache_key = f"similar_{artist_name.lower()}"

        with self.cache_lock:
            if cache_key in self.cache["data"]:
                return self.cache["data"][cache_key]

        params = {
            "method": "artist.getsimilar",
            "artist": artist_name,
            "limit": limit
        }

        data = self._make_request(params)
        similar = []

        if "similarartists" in data and "artist" in data["similarartists"]:
            for artist in data["similarartists"]["artist"]:
                similar.append({
                    "name": artist.get("name", ""),
                    "match": float(artist.get("match", 0)),
                    "listeners": int(artist.get("listeners", 0)) if "listeners" in artist else 0,
                })

        for artist in similar:
            artist["tags"] = self.get_artist_tags(artist["name"])

        with self.cache_lock:
            self.cache["data"][cache_key] = similar
        self._save_cache()

        return similar

    def get_artist_tags(self, artist_name: str, limit: int = 10) -> List[str]:
        """Get top tags for an artist (thread-safe)"""
        cache_key = f"tags_{artist_name.lower()}"

        with self.cache_lock:
            if cache_key in self.cache["data"]:
                return self.cache["data"][cache_key]

        params = {
            "method": "artist.gettoptags",
            "artist": artist_name,
            "limit": limit
        }

        data = self._make_request(params)
        tags = []

        if "toptags" in data and "tag" in data["toptags"]:
            tags = [tag["name"] for tag in data["toptags"]["tag"] if "name" in tag]

        with self.cache_lock:
            self.cache["data"][cache_key] = tags
        self._save_cache()

        return tags

    def get_artist_info(self, artist_name: str) -> Dict:
        """Get detailed artist information (thread-safe)"""
        cache_key = f"info_{artist_name.lower()}"

        with self.cache_lock:
            if cache_key in self.cache["data"]:
                return self.cache["data"][cache_key]

        params = {
            "method": "artist.getinfo",
            "artist": artist_name
        }

        data = self._make_request(params)
        info = {}

        if "artist" in data:
            artist = data["artist"]
            info = {
                "listeners": int(artist.get("stats", {}).get("listeners", 0)),
                "playcount": int(artist.get("stats", {}).get("playcount", 0)),
                "tags": [tag["name"] for tag in artist.get("tags", {}).get("tag", [])[:10]]
            }

        with self.cache_lock:
            self.cache["data"][cache_key] = info
        self._save_cache()

        return info


class RecommendationEngine:
    """Generate artist recommendations"""

    def __init__(self, library_stats: Dict, lastfm_client: LastFmClient):
        self.library_stats = library_stats
        self.lastfm = lastfm_client
        self.known_artists = set(
            self._normalise_artist_name(artist)
            for artist, stats in library_stats.items()
            if (stats["play_count"] >= KNOWN_ARTIST_MIN_PLAY_COUNT or
                stats["track_count"] >= KNOWN_ARTIST_MIN_TRACKS)
        )
        self.disliked_artists = set(
            self._normalise_artist_name(artist)
            for artist, stats in library_stats.items()
            if (stats.get("disliked_track_count", 0) >= LIB_DISLIKED_MIN_TRACK_COUNT and
                stats.get("loved_track_count", 0) == 0)
        )

    @staticmethod
    def _normalise_artist_name(name: str) -> str:
        """Normalise artist name for matching by removing punctuation variations"""
        normalised = name.lower()
        normalised = normalised.replace('"', '').replace("'", '').replace(''', '').replace(''', '')
        normalised = ' '.join(normalised.split())
        return normalised

    def _contains_known_artist(self, artist_name: str) -> bool:
        """
        Check if an artist name contains any known artist as a substring.
        This helps filter collaboration artists like "Nas & Damian Marley"
        when "Nas" is already in your library.

        Args:
            artist_name: Artist name to check (will be normalised)

        Returns:
            True if artist_name contains any known artist name, False otherwise
        """
        normalised = self._normalise_artist_name(artist_name)

        # Split on common collaboration separators
        # e.g., "Nas & Damian Marley" -> ["nas", "damian marley"]
        # e.g., "Nas, Cordae & Freddie Gibbs" -> ["nas", "cordae", "freddie gibbs"]
        separators = [' & ', ', ', ' feat. ', ' ft. ', ' featuring ']
        parts = [normalised]

        for sep in separators:
            new_parts = []
            for part in parts:
                new_parts.extend(part.split(sep))
            parts = new_parts

        # Clean up each part (trim whitespace)
        parts = [part.strip() for part in parts if part.strip()]

        # Check if any part matches a known artist
        for part in parts:
            if part in self.known_artists:
                return True

        return False

    def get_loved_artists(self) -> List[str]:
        """Get list of loved or frequently played artists for building taste profile"""
        loved = []
        cutoff_date = None

        if LAST_MONTHS_FILTER > 0:
            cutoff_date = datetime.now() - timedelta(days=LAST_MONTHS_FILTER * 30)

        for artist, stats in self.library_stats.items():
            is_loved = False

            # Skip disliked artists from being used as recommendation sources
            if (stats.get("disliked_track_count", 0) >= LIB_DISLIKED_MIN_TRACK_COUNT and
                stats.get("loved_track_count", 0) == 0):
                continue

            if stats["loved"]:
                is_loved = True
            elif stats["play_count"] >= LOVED_PLAY_COUNT_THRESHOLD:
                is_loved = True
            elif stats["rating"] >= (LOVED_MIN_TRACK_RATING * 20) and stats["play_count"] >= LOVED_MIN_ARTIST_PLAYS:
                is_loved = True

            if is_loved:
                if cutoff_date and stats.get("last_played"):
                    if stats["last_played"] < cutoff_date:
                        continue
                loved.append(artist)

        return loved

    def build_tag_profile(self, loved_artists: List[str]) -> Dict[str, float]:
        """Build a tag profile from loved artists for similarity matching (concurrent)"""
        if not ENABLE_TAG_SIMILARITY:
            return {}

        print("Building music taste profile from your loved artists...")

        tag_counts = defaultdict(float)
        total_tags = 0

        def fetch_tags(artist: str) -> tuple:
            tags = self.lastfm.get_artist_tags(artist, limit=10)
            play_count = self.library_stats.get(artist, {}).get("play_count", 1)
            return artist, tags, play_count

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            futures = {executor.submit(fetch_tags, artist): artist for artist in loved_artists}

            completed = 0
            failed = 0

            for future in as_completed(futures):
                try:
                    artist, tags, play_count = future.result()
                    completed += 1

                    weight = play_count if ENABLE_PLAY_FREQUENCY_WEIGHTING else 1

                    for tag in tags:
                        tag_lower = tag.lower()
                        if tag_lower in LIB_TAG_IGNORE_LIST:
                            continue
                        tag_counts[tag_lower] += weight
                        total_tags += weight

                    if completed % 50 == 0 or completed == len(loved_artists):
                        status = f"  Progress: {completed}/{len(loved_artists)} artists analysed"
                        if failed > 0:
                            status += f" ({failed} failed)"
                        print(status + "...")

                except Exception:
                    failed += 1
                    continue

        tag_profile = {}
        for tag, count in tag_counts.items():
            tag_profile[tag] = count / total_tags if total_tags > 0 else 0

        top_tags = sorted(tag_profile.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"✓ Your top music tags: {', '.join([tag for tag, _ in top_tags])}\n")

        return tag_profile

    def calculate_tag_similarity(self, artist_tags: List[str], tag_profile: Dict[str, float]) -> float:
        """Calculate how well an artist's tags match the user's tag profile"""
        if not tag_profile or not artist_tags:
            return 0.0

        similarity = 0.0
        valid_tag_count = 0
        for tag in artist_tags:
            tag_lower = tag.lower()
            if tag_lower in LIB_TAG_IGNORE_LIST:
                continue
            similarity += tag_profile.get(tag_lower, 0)
            valid_tag_count += 1

        return similarity / valid_tag_count if valid_tag_count > 0 else 0.0

    def generate_recommendations(self, rarity_pref: int = 7) -> List[Dict]:
        """Generate artist recommendations"""
        loved_artists = self.get_loved_artists()
        print(f"Analysing {len(loved_artists)} loved/frequently played artists...")
        if self.disliked_artists:
            print(f"Filtering {len(self.disliked_artists)} disliked artists from recommendations")

        tag_profile = self.build_tag_profile(loved_artists)

        recommendations = defaultdict(lambda: {
            "recommended_by": [],
            "recommender_weights": [],
            "listeners": 0,
            "tags": set(),
            "match_scores": []
        })

        def fetch_similar(artist: str) -> tuple:
            similar = self.lastfm.get_similar_artists(artist)
            return artist, similar

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
            futures = {executor.submit(fetch_similar, artist): artist for artist in loved_artists}

            completed = 0
            failed = 0
            for future in as_completed(futures):
                try:
                    artist, similar = future.result()
                    completed += 1

                    if completed % 50 == 0 or completed == len(loved_artists):
                        status = f"  Progress: {completed}/{len(loved_artists)} artists processed"
                        if failed > 0:
                            status += f" ({failed} failed)"
                        print(status + "...")

                    for sim_artist in similar:
                        name = sim_artist["name"]
                        normalised_name = self._normalise_artist_name(name)

                        if normalised_name in self.known_artists:
                            continue

                        # Filter out collaboration artists containing known artists
                        # e.g., "Nas & Damian Marley" when "Nas" is in library
                        if self._contains_known_artist(name):
                            continue

                        if normalised_name in self.disliked_artists:
                            continue

                        if name in self.library_stats:
                            stats = self.library_stats[name]
                            if (stats["play_count"] >= KNOWN_ARTIST_MIN_PLAY_COUNT or
                                stats["track_count"] >= KNOWN_ARTIST_MIN_TRACKS):
                                continue

                        recommendations[name]["recommended_by"].append(artist)
                        recommendations[name]["match_scores"].append(sim_artist["match"])
                        recommendations[name]["listeners"] = sim_artist.get("listeners", 0)
                        recommendations[name]["tags"].update(sim_artist.get("tags", []))

                        if ENABLE_PLAY_FREQUENCY_WEIGHTING:
                            recommender_play_count = self.library_stats.get(artist, {}).get("play_count", 1)
                            recommendations[name]["recommender_weights"].append(recommender_play_count)
                except Exception as e:
                    failed += 1
                    continue

        print(f"\nFound {len(recommendations)} potential recommendations")

        # Filter out artists with blacklisted tags
        if REC_TAG_BLACKLIST:
            filtered_recommendations = {}
            filtered_count = 0
            for name, data in recommendations.items():
                # Get tags to check (all tags or top N only)
                tags_to_check = data["tags"]
                if REC_TAG_BLACKLIST_TOP_N_TAGS > 0:
                    tags_to_check = tags_to_check[:REC_TAG_BLACKLIST_TOP_N_TAGS]

                artist_tags_lower = {tag.lower() for tag in tags_to_check}
                # Check if any artist tag matches blacklist
                if REC_TAG_BLACKLIST & artist_tags_lower:
                    filtered_count += 1
                    continue
                filtered_recommendations[name] = data

            if filtered_count > 0:
                top_n_desc = f" in top {REC_TAG_BLACKLIST_TOP_N_TAGS} tags" if REC_TAG_BLACKLIST_TOP_N_TAGS > 0 else ""
                print(f"Filtered {filtered_count} artist(s) with blacklisted tags{top_n_desc}: {', '.join(sorted(REC_TAG_BLACKLIST))}")

            recommendations = filtered_recommendations

        scored_recommendations = []
        for name, data in recommendations.items():
            frequency_score = len(data["recommended_by"])

            if ENABLE_PLAY_FREQUENCY_WEIGHTING and data["recommender_weights"]:
                weighted_frequency = sum(data["recommender_weights"]) / len(data["recommender_weights"])
                frequency_score = weighted_frequency / 100

            avg_match = sum(data["match_scores"]) / len(data["match_scores"])

            listeners = data["listeners"] or 1
            rarity_score = 1 / (1 + listeners / 1000000)

            tag_similarity = 0.0
            if ENABLE_TAG_SIMILARITY and tag_profile:
                tag_similarity = self.calculate_tag_similarity(list(data["tags"]), tag_profile)

            if ENABLE_TAG_SIMILARITY or ENABLE_PLAY_FREQUENCY_WEIGHTING:
                score = (
                    (frequency_score * SCORING_FREQUENCY_WEIGHT) +
                    (tag_similarity * SCORING_TAG_OVERLAP_WEIGHT) +
                    (avg_match * SCORING_MATCH_WEIGHT) +
                    (rarity_score * SCORING_RARITY_WEIGHT)
                )
            else:
                # Extended rarity scale: 1-15
                # At 1: rarity=0.1, frequency=0.5, match=0.4 (popular)
                # At 7: rarity=0.227, frequency=0.443, match=0.330 (balanced)
                # At 10: rarity=0.325, frequency=0.410, match=0.265 (obscure)
                # At 15: rarity=0.5, frequency=0.350, match=0.150 (very obscure)
                rarity_weight = 0.1 + (rarity_pref - 1) * 0.4 / 14
                frequency_weight = 0.5 - (rarity_pref - 1) * 0.15 / 14
                match_weight = 1.0 - rarity_weight - frequency_weight
                score = (frequency_score * frequency_weight) + (avg_match * match_weight) + (rarity_score * rarity_weight)

            scored_recommendations.append({
                "name": name,
                "score": score,
                "frequency": len(data["recommended_by"]),
                "avg_match": avg_match,
                "recommended_by": data["recommended_by"],
                "listeners": listeners,
                "tags": list(data["tags"])[:10],
                "rarity_score": rarity_score,
                "tag_similarity": tag_similarity,
                "rarity_pref": rarity_pref
            })

        scored_recommendations.sort(key=lambda x: x["score"], reverse=True)

        print(f"Fetching detailed info for top {min(100, len(scored_recommendations))} recommendations...")
        for rec in scored_recommendations[:100]:
            artist_info = self.lastfm.get_artist_info(rec["name"])
            if artist_info and artist_info.get("listeners", 0) > 0:
                rec["listeners"] = artist_info["listeners"]
                rec["rarity_score"] = 1 / (1 + rec["listeners"] / 1000000)

                if ENABLE_TAG_SIMILARITY or ENABLE_PLAY_FREQUENCY_WEIGHTING:
                    freq_score = rec["frequency"]
                    rec["score"] = (
                        (freq_score * SCORING_FREQUENCY_WEIGHT) +
                        (rec["tag_similarity"] * SCORING_TAG_OVERLAP_WEIGHT) +
                        (rec["avg_match"] * SCORING_MATCH_WEIGHT) +
                        (rec["rarity_score"] * SCORING_RARITY_WEIGHT)
                    )
                else:
                    pref = rec["rarity_pref"]
                    # Extended rarity scale: 1-15
                    rarity_weight = 0.1 + (pref - 1) * 0.4 / 14
                    frequency_weight = 0.5 - (pref - 1) * 0.15 / 14
                    match_weight = 1.0 - rarity_weight - frequency_weight
                    rec["score"] = (rec["frequency"] * frequency_weight) + (rec["avg_match"] * match_weight) + (rec["rarity_score"] * rarity_weight)

        scored_recommendations.sort(key=lambda x: x["score"], reverse=True)

        return scored_recommendations


def save_recommendations_cache(recommendations: List[Dict], loved_artists: List[str], rarity_pref: int) -> None:
    """Save recommendations to cache with metadata"""
    cache_file = CACHE_DIR / "recommendations_cache.json"
    cache_data = {
        "timestamp": datetime.now().isoformat(),
        "rarity_preference": rarity_pref,
        "loved_artists_count": len(loved_artists),
        "recommendations": recommendations
    }

    with open(cache_file, 'w') as f:
        json.dump(cache_data, f, indent=2)

    print(f"✓ Cached {len(recommendations)} recommendations")


def load_recommendations_cache(rarity_pref: int) -> List[Dict] | None:
    """Load recommendations from cache if valid"""
    cache_file = CACHE_DIR / "recommendations_cache.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)

        cache_time = datetime.fromisoformat(cache_data["timestamp"])
        age_days = (datetime.now() - cache_time).days

        if age_days > REC_CACHE_EXPIRY_DAYS:
            print(f"Recommendations cache expired ({age_days} days old, limit: {REC_CACHE_EXPIRY_DAYS} days)")
            return None

        if cache_data.get("rarity_preference") != rarity_pref:
            print(f"Recommendations cache invalid (rarity preference changed: {cache_data.get('rarity_preference')} → {rarity_pref})")
            return None

        recommendations = cache_data["recommendations"]
        print(f"✓ Loaded {len(recommendations)} recommendations from cache ({age_days} days old)")
        return recommendations

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Warning: Failed to load recommendations cache: {e}")
        return None
