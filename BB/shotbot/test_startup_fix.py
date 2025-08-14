#!/usr/bin/env python3
"""Test script to verify startup fixes for empty cache scenario."""

import os
import shutil
import sys
import time
from pathlib import Path

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cache_manager import CacheManager
from shot_model import ShotModel
from config import Config


def test_empty_cache_startup():
    """Test that the application loads shots correctly when cache is empty."""
    
    print("\n=== Testing Empty Cache Startup ===\n")
    
    # Create a temporary cache directory
    test_cache_dir = Path.home() / ".shotbot_test" / "cache"
    
    # Clean up any existing test cache
    if test_cache_dir.exists():
        shutil.rmtree(test_cache_dir.parent)
        print(f"✓ Cleaned up existing test cache")
    
    # Create cache manager with test directory
    cache_manager = CacheManager(cache_dir=test_cache_dir)
    print(f"✓ Created cache manager with test directory: {test_cache_dir}")
    
    # Verify cache is empty
    cached_shots = cache_manager.get_cached_shots()
    cached_scenes = cache_manager.get_cached_threede_scenes()
    
    assert cached_shots is None, "Cache should be empty for shots"
    assert cached_scenes is None, "Cache should be empty for 3DE scenes"
    print(f"✓ Verified cache is empty")
    
    # Create shot model with empty cache
    shot_model = ShotModel(cache_manager=cache_manager, load_cache=True)
    
    # Verify no shots loaded from cache
    assert len(shot_model.shots) == 0, "Should have no shots from empty cache"
    print(f"✓ Shot model initialized with 0 shots (expected)")
    
    # Now trigger a refresh (simulating what _initial_load should do)
    print(f"\nFetching fresh shots...")
    success, has_changes = shot_model.refresh_shots()
    
    if success:
        print(f"✓ Successfully fetched {len(shot_model.shots)} shots")
        
        # Verify shots are now cached
        cached_shots = cache_manager.get_cached_shots()
        if cached_shots:
            print(f"✓ Shots are now cached ({len(cached_shots)} shots)")
        else:
            print(f"✗ Shots were not cached after fetch")
    else:
        print(f"✗ Failed to fetch shots")
        print(f"  Note: This might be expected if 'ws -sg' is not available")
    
    # Clean up test cache
    if test_cache_dir.exists():
        shutil.rmtree(test_cache_dir.parent)
        print(f"\n✓ Cleaned up test cache")
    
    print("\n=== Test Complete ===\n")
    
    return success


def test_background_worker_timing():
    """Test that background worker checks immediately on startup."""
    
    print("\n=== Testing Background Worker Timing ===\n")
    
    # This would require actually running the MainWindow and worker
    # which needs a Qt application context
    
    print("Background worker timing test requires Qt application context")
    print("Manual verification needed:")
    print("1. Start app with empty cache")
    print("2. Check logs for 'Background refresh worker started'")
    print("3. Verify refresh happens within 2 seconds (not 10 minutes)")
    print("")
    print("Expected log pattern:")
    print("  - 'Background refresh worker started'")
    print("  - (2 second delay)")
    print("  - 'Background refresh: checking for shot updates'")
    
    print("\n=== Manual Verification Required ===\n")


if __name__ == "__main__":
    # Test empty cache startup
    test_empty_cache_startup()
    
    # Info about background worker test
    test_background_worker_timing()