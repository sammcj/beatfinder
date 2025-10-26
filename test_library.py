#!/usr/bin/env python3
"""
Test script to verify Apple Music library access
"""

import subprocess
import sys
from collections import defaultdict

def test_music_access():
    """Test if we can access Music.app"""
    print("Testing Music.app access...")
    try:
        result = subprocess.run(
            ['osascript', '-e', 'tell application "Music" to get name'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("✓ Music.app is accessible")
            return True
        else:
            print("✗ Cannot access Music.app")
            print(f"  Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_library_scan():
    """Test extracting artist data"""
    print("\nScanning library (this may take a minute)...")

    script = '''
tell application "Music"
    set output to ""
    set trackList to every track of library playlist 1
    repeat with theTrack in trackList
        try
            set artistName to artist of theTrack
            if artistName is not "" then
                set playCount to played count of theTrack
                set trackRating to rating of theTrack
                set isLoved to loved of theTrack
                set output to output & artistName & "|" & playCount & "|" & trackRating & "|" & isLoved & linefeed
            end if
        end try
    end repeat
    return output
end tell
'''

    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            print(f"✗ AppleScript error: {result.stderr}")
            return False

        # Parse results
        artist_stats = defaultdict(lambda: {
            "play_count": 0,
            "loved": False,
            "rating": 0,
            "track_count": 0
        })

        for line in result.stdout.split('\n'):
            if not line.strip():
                continue

            try:
                parts = line.split('|')
                if len(parts) != 4:
                    continue

                artist_name = parts[0].strip()
                play_count = int(parts[1])
                rating = int(parts[2])
                loved = parts[3].lower() == 'true'

                artist_stats[artist_name]["play_count"] += play_count
                artist_stats[artist_name]["track_count"] += 1

                if loved or rating >= 80:
                    artist_stats[artist_name]["loved"] = True

                artist_stats[artist_name]["rating"] = max(
                    artist_stats[artist_name]["rating"],
                    rating
                )
            except (ValueError, IndexError):
                continue

        print(f"✓ Found {len(artist_stats)} artists")

        # Show sample
        loved_artists = [a for a, s in artist_stats.items() if s["loved"]]
        print(f"✓ {len(loved_artists)} loved/highly rated artists")

        if loved_artists:
            print("\nSample loved artists:")
            for artist in sorted(loved_artists, key=lambda a: artist_stats[a]["play_count"], reverse=True)[:5]:
                stats = artist_stats[artist]
                print(f"  - {artist} (played {stats['play_count']} times)")

        return True

    except subprocess.TimeoutExpired:
        print("✗ Scan timed out (library too large?)")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    print("BeatFinder Library Test\n")
    print("This will test if BeatFinder can read your Apple Music library.")
    print("You may be prompted to grant permission.\n")

    if not test_music_access():
        print("\n❌ Music.app access test failed")
        print("\nTroubleshooting:")
        print("1. Make sure Music.app is installed")
        print("2. Try opening Music.app manually")
        print("3. Check System Settings > Privacy & Security > Automation")
        sys.exit(1)

    if not test_library_scan():
        print("\n❌ Library scan test failed")
        sys.exit(1)

    print("\n✅ All tests passed!")
    print("\nYou're ready to use BeatFinder.")
    print("Next: Get a Last.fm API key and run: python3 beatfinder.py")

if __name__ == "__main__":
    main()
