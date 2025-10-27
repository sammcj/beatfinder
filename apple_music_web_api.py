#!/usr/bin/env python3
"""
Apple Music Web API integration using browser tokens.
Creates playlists directly in Apple Music using the web API.
"""

import json
import os
import urllib3
import threading
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed


load_dotenv()


class AppleMusicWebAPI:
    """
    Apple Music Web API client using browser-extracted tokens.

    Tokens can be extracted from browser when logged into https://music.apple.com:
    - Dev Token: Found in URL or network requests (Bearer token)
    - Media User Token: Found in browser cookies/storage
    """

    HOST = 'https://amp-api.music.apple.com'
    COUNTRY_CODE = 'au'  # Australia - adjust if needed

    def __init__(self):
        """Initialise with tokens from environment variables"""
        self.dev_token = os.getenv('APPLE_MUSIC_WEB_DEV_TOKEN')
        self.media_user_token = os.getenv('APPLE_MUSIC_WEB_MEDIA_USER_TOKEN')

        if not self.dev_token or not self.media_user_token:
            raise ValueError(
                "Missing Apple Music tokens. Please set APPLE_MUSIC_WEB_DEV_TOKEN "
                "and APPLE_MUSIC_WEB_MEDIA_USER_TOKEN in .env file"
            )

        self.headers = {
            'Media-User-Token': self.media_user_token,
            'Authorization': f'Bearer {self.dev_token}',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': '*/*',
            'Origin': 'https://music.apple.com',
            'Accept-Encoding': 'gzip, deflate',
            'Content-Type': 'application/json'
        }

        self.http = urllib3.PoolManager()
        self.stats_lock = threading.Lock()  # Thread-safe counters

    def get_all_playlists(self) -> List[Dict]:
        """
        Fetch all user playlists.

        Returns:
            List of playlist dicts with 'id', 'name', 'attributes'
        """
        try:
            response = self.http.request(
                'GET',
                f'{self.HOST}/v1/me/library/playlists',
                headers=self.headers
            )

            if response.status == 200:
                data = json.loads(response.data)
                return data.get('data', [])
            else:
                print(f"Warning: Could not fetch playlists (status {response.status})")
                return []
        except Exception as e:
            print(f"Error fetching playlists: {e}")
            return []

    def find_playlist_by_name(self, name: str) -> Optional[str]:
        """
        Find playlist ID by exact name match.

        Args:
            name: Playlist name to search for

        Returns:
            Playlist ID if found, None otherwise
        """
        playlists = self.get_all_playlists()
        for playlist in playlists:
            if playlist.get('attributes', {}).get('name') == name:
                return playlist.get('id')
        return None

    def check_songs_in_library(self, song_ids: List[str]) -> List[str]:
        """
        Check which songs from a list are already in the user's library.

        Args:
            song_ids: List of Apple Music catalogue song IDs

        Returns:
            List of song IDs that are NOT in the library (candidates to add)
        """
        if not song_ids:
            return []

        # The API accepts up to 100 IDs at once, so batch if needed
        batch_size = 100
        not_in_library = []

        for i in range(0, len(song_ids), batch_size):
            batch = song_ids[i:i + batch_size]
            ids_param = ','.join(batch)

            try:
                # Check library for these song IDs
                response = self.http.request(
                    'GET',
                    f'{self.HOST}/v1/me/library/songs?filter[equivalents]={ids_param}',
                    headers=self.headers
                )

                if response.status == 200:
                    data = json.loads(response.data)
                    library_songs = data.get('data', [])

                    # Extract IDs of songs found in library
                    library_equivalents = set()
                    for song in library_songs:
                        # Get the catalogue ID this library song maps to
                        playParams = song.get('attributes', {}).get('playParams', {})
                        catalogue_id = playParams.get('catalogId')
                        if catalogue_id:
                            library_equivalents.add(str(catalogue_id))

                    # Add songs NOT found in library
                    for song_id in batch:
                        if str(song_id) not in library_equivalents:
                            not_in_library.append(song_id)
                else:
                    # If check fails, assume none are in library (add all)
                    not_in_library.extend(batch)

            except Exception as e:
                print(f"Warning: Could not check library status: {e}")
                # On error, assume none are in library
                not_in_library.extend(batch)

        return not_in_library

    def delete_playlist(self, playlist_id: str) -> bool:
        """
        Delete a playlist.

        Args:
            playlist_id: ID of playlist to delete

        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.http.request(
                'DELETE',
                f'{self.HOST}/v1/me/library/playlists/{playlist_id}',
                headers=self.headers
            )

            return response.status in (200, 204)
        except Exception as e:
            print(f"Error deleting playlist: {e}")
            return False

    def create_playlist(self, name: str, description: str = "") -> Optional[str]:
        """
        Create a new playlist.

        Args:
            name: Playlist name
            description: Optional playlist description

        Returns:
            Playlist ID if successful, None otherwise
        """
        playlist_body = json.dumps({
            'attributes': {
                'name': name,
                'description': description
            }
        })

        try:
            response = self.http.request(
                'POST',
                f'{self.HOST}/v1/me/library/playlists',
                headers=self.headers,
                body=playlist_body
            )

            if response.status == 201:
                data = json.loads(response.data)
                return data['data'][0]['id']
            else:
                print(f"Error creating playlist: status {response.status}")
                print(f"Response: {response.data.decode('utf-8')}")
                return None
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return None

    def add_song_to_playlist(self, playlist_id: str, song_id: str, verbose: bool = False) -> bool:
        """
        Add a single song to a playlist.

        Args:
            playlist_id: Playlist ID
            song_id: Song ID (Apple Music catalogue ID)
            verbose: Print detailed error messages

        Returns:
            True if successful, False otherwise
        """
        body = json.dumps({
            'data': [{'id': str(song_id), 'type': 'songs'}]
        })

        try:
            response = self.http.request(
                'POST',
                f'{self.HOST}/v1/me/library/playlists/{playlist_id}/tracks',
                headers=self.headers,
                body=body
            )

            if response.status == 500:
                # Try to find equivalent song in user's region
                if verbose:
                    print(f"    Song {song_id}: trying regional equivalent...")
                return self._add_equivalent_song(playlist_id, song_id, verbose)

            if response.status not in (200, 204):
                if verbose:
                    print(f"    Song {song_id}: failed (status {response.status})")
                    print(f"    Response: {response.data.decode('utf-8')[:200]}")
                return False

            return True
        except Exception as e:
            if verbose:
                print(f"    Song {song_id}: error - {e}")
            return False

    def _add_equivalent_song(self, playlist_id: str, song_id: str, verbose: bool = False) -> bool:
        """
        Try to add an equivalent version of a song (for regional availability).

        Args:
            playlist_id: Playlist ID
            song_id: Original song ID
            verbose: Print detailed error messages

        Returns:
            True if equivalent found and added, False otherwise
        """
        try:
            # Fetch equivalent song ID for user's region
            equiv_response = self.http.request(
                'GET',
                f'{self.HOST}/v1/catalog/{self.COUNTRY_CODE}/songs?filter[equivalents]={song_id}',
                headers=self.headers
            )

            if equiv_response.status == 200:
                data = json.loads(equiv_response.data)
                if data.get('data') and len(data['data']) > 0:
                    equivalent_song_id = data['data'][0]['id']

                    # Add the equivalent song
                    body = json.dumps({
                        'data': [{'id': str(equivalent_song_id), 'type': 'songs'}]
                    })

                    response = self.http.request(
                        'POST',
                        f'{self.HOST}/v1/me/library/playlists/{playlist_id}/tracks',
                        headers=self.headers,
                        body=body
                    )

                    if response.status in (200, 204):
                        if verbose:
                            print(f"    Song {song_id}: ✓ added equivalent {equivalent_song_id}")
                        return True
                    else:
                        if verbose:
                            print(f"    Song {song_id}: equivalent failed (status {response.status})")
                        return False

            if verbose:
                print(f"    Song {song_id}: no equivalent found")
            return False
        except Exception as e:
            if verbose:
                print(f"    Song {song_id}: error finding equivalent - {e}")
            return False

    def create_or_replace_playlist(
        self,
        name: str,
        song_ids: List[str],
        description: str = ""
    ) -> Optional[str]:
        """
        Create a new playlist or replace an existing one with the same name.

        If a playlist with the given name exists, it will be deleted and recreated.

        Args:
            name: Playlist name
            song_ids: List of Apple Music song IDs
            description: Optional description

        Returns:
            Playlist ID if successful, None otherwise
        """
        # Check if playlist already exists
        existing_id = self.find_playlist_by_name(name)
        if existing_id:
            print(f"Found existing playlist '{name}' - deleting...")
            if not self.delete_playlist(existing_id):
                print(f"Warning: Could not delete existing playlist")

        # Create new playlist
        print(f"Creating playlist '{name}'...")
        playlist_id = self.create_playlist(name, description)

        if not playlist_id:
            print("Failed to create playlist")
            return None

        print(f"✓ Playlist created (ID: {playlist_id})")

        # Filter out songs already in library
        if song_ids:
            print(f"\nChecking which songs are already in your library...")
            songs_to_add = self.check_songs_in_library(song_ids)
            already_in_library = len(song_ids) - len(songs_to_add)

            if already_in_library > 0:
                print(f"✓ Found {already_in_library} songs already in your library (will skip)")

            if not songs_to_add:
                print("All songs are already in your library - nothing to add!")
                return playlist_id

            print(f"\nAdding {len(songs_to_add)} new songs to playlist in parallel...")
            print(f"Using 5 concurrent workers for faster processing\n")

            # Add songs in parallel
            successful, failed = self._add_songs_parallel(playlist_id, songs_to_add, max_workers=5)

            print(f"\n✓ Added {successful}/{len(songs_to_add)} songs successfully")
            if failed > 0:
                print(f"  {failed} songs could not be added (may not be available in your region)")
            if already_in_library > 0:
                print(f"  {already_in_library} songs skipped (already in library)")

        return playlist_id

    def _add_songs_parallel(
        self,
        playlist_id: str,
        song_ids: List[str],
        max_workers: int = 5
    ) -> Tuple[int, int]:
        """
        Add multiple songs to playlist in parallel.

        Args:
            playlist_id: Playlist ID
            song_ids: List of song IDs to add
            max_workers: Number of concurrent workers

        Returns:
            Tuple of (successful_count, failed_count)
        """
        successful = 0
        failed = 0
        completed = 0
        total = len(song_ids)

        def add_song_worker(song_id: str) -> bool:
            """Worker function to add a single song"""
            return self.add_song_to_playlist(playlist_id, song_id, verbose=False)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_song = {
                executor.submit(add_song_worker, song_id): song_id
                for song_id in song_ids
            }

            # Process results as they complete
            for future in as_completed(future_to_song):
                song_id = future_to_song[future]
                completed += 1

                try:
                    result = future.result()
                    with self.stats_lock:
                        if result:
                            successful += 1
                            print(f"  [{completed}/{total}] Song {song_id}: ✓")
                        else:
                            failed += 1
                            print(f"  [{completed}/{total}] Song {song_id}: ✗ failed")
                except Exception as e:
                    with self.stats_lock:
                        failed += 1
                        print(f"  [{completed}/{total}] Song {song_id}: ✗ error - {e}")

        return successful, failed


def create_beatfinder_playlist(artist_song_data: Dict[str, Dict]) -> Optional[str]:
    """
    Create a BeatFinder playlist with today's date.

    Args:
        artist_song_data: Dict mapping artist names to their song data
                         (output from apple_music_integration.scrape_artists_parallel)
                         Format: {'Artist Name': {'songs': [{'id': '123', 'title': '...'}, ...]}}

    Returns:
        Playlist ID if successful, None otherwise
    """
    # Generate playlist name with today's date
    today = datetime.now().strftime("%Y-%m-%d")
    playlist_name = f"BeatFinder - {today}"

    # Collect all song IDs
    song_ids = []
    for artist_name, data in artist_song_data.items():
        songs = data.get('songs', [])
        for song in songs:
            song_id = song.get('id')
            if song_id:
                song_ids.append(str(song_id))

    if not song_ids:
        print("No song IDs found to add to playlist")
        return None

    print(f"\n{'='*60}")
    print(f"Creating Apple Music playlist: '{playlist_name}'")
    print(f"{'='*60}\n")

    # Create playlist
    try:
        api = AppleMusicWebAPI()
        description = f"Artist recommendations generated by BeatFinder on {today}"
        playlist_id = api.create_or_replace_playlist(playlist_name, song_ids, description)

        if playlist_id:
            print(f"\n{'='*60}")
            print(f"✓ Playlist created successfully!")
            print(f"  View in Apple Music: https://music.apple.com/library/playlist/{playlist_id}")
            print(f"{'='*60}\n")

        return playlist_id
    except ValueError as e:
        print(f"\nError: {e}")
        print("Please ensure APPLE_MUSIC_WEB_DEV_TOKEN and APPLE_MUSIC_WEB_MEDIA_USER_TOKEN")
        print("are set in your .env file.\n")
        return None
    except Exception as e:
        print(f"\nUnexpected error creating playlist: {e}\n")
        return None
