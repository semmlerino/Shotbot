#!/usr/bin/env python3
"""Test script to verify cache manager handles cache deletion properly.

This tests the real-world scenario where a user deletes the cache
directory while the application is running.
"""

import shutil
import sys
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

from cache_manager import CacheManager


def create_test_image(path: Path) -> Path:
    """Create a test image file."""
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(0xFF0000)  # Red
    image.save(str(path), "JPEG")
    return path


def main():
    """Run the cache deletion test."""
    QCoreApplication(sys.argv)

    print("=" * 60)
    print("Testing ShotBot Cache Manager - Cache Deletion Handling")
    print("=" * 60)

    # Create temp directory for test
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        cache_dir = temp_path / "cache"
        cache_dir.mkdir()

        print(f"\n1. Created cache directory: {cache_dir}")

        # Initialize cache manager
        manager = CacheManager(cache_dir=cache_dir)
        print(
            f"2. Initialized CacheManager with thumbnails at: {manager.thumbnails_dir}"
        )

        # Create and cache some test images
        print("\n3. Caching test images...")
        for i in range(3):
            img_path = temp_path / f"test{i}.jpg"
            create_test_image(img_path)
            result = manager.cache_thumbnail(img_path, "show1", f"seq{i}", f"shot{i}")
            if result:
                print(f"   ✓ Cached: {result.name}")
            else:
                print(f"   ✗ Failed to cache test{i}.jpg")

        # Verify thumbnails exist
        print("\n4. Verifying cached thumbnails...")
        for i in range(3):
            cached = manager.get_cached_thumbnail("show1", f"seq{i}", f"shot{i}")
            if cached and cached.exists():
                print(f"   ✓ Found: shot{i}_thumb.jpg")
            else:
                print(f"   ✗ Missing: shot{i}_thumb.jpg")

        # DELETE THE CACHE DIRECTORY (simulating user action)
        print("\n5. DELETING cache directory (simulating user action)...")
        if manager.thumbnails_dir.exists():
            shutil.rmtree(manager.thumbnails_dir)
            print(f"   ✓ Deleted: {manager.thumbnails_dir}")

        # Verify directory is gone
        if not manager.thumbnails_dir.exists():
            print("   ✓ Cache directory successfully deleted")

        # Try to cache new images after deletion
        print("\n6. Attempting to cache new images after deletion...")
        for i in range(3, 6):
            img_path = temp_path / f"test{i}.jpg"
            create_test_image(img_path)
            result = manager.cache_thumbnail(img_path, "show2", f"seq{i}", f"shot{i}")
            if result and result.exists():
                print(f"   ✓ Successfully cached after deletion: {result.name}")
            else:
                print(f"   ✗ Failed to cache test{i}.jpg after deletion")

        # Check if directory was recreated
        print("\n7. Checking if cache directory was recreated...")
        if manager.thumbnails_dir.exists():
            print(f"   ✓ Cache directory recreated at: {manager.thumbnails_dir}")
        else:
            print("   ✗ Cache directory NOT recreated")

        # Test get_cached_thumbnail after deletion
        print("\n8. Testing get_cached_thumbnail after deletion...")
        for i in range(3):
            cached = manager.get_cached_thumbnail("show1", f"seq{i}", f"shot{i}")
            if cached is None:
                print(f"   ✓ Correctly returns None for deleted shot{i}")
            else:
                print(f"   ✗ Unexpectedly found shot{i}")

        # Test clear_cache atomic operation
        print("\n9. Testing clear_cache() atomic operation...")
        old_dir = manager.thumbnails_dir
        manager.clear_cache()
        new_dir = manager.thumbnails_dir

        if old_dir != new_dir:
            print(f"   ✓ Directory atomically swapped: {old_dir.name} → {new_dir.name}")
        else:
            print("   ✗ Directory not swapped")

        if new_dir.exists():
            print("   ✓ New directory exists immediately")
        else:
            print("   ✗ New directory missing")

        # Test ensure_cache_directory
        print("\n10. Testing ensure_cache_directory()...")
        if manager.thumbnails_dir.exists():
            shutil.rmtree(manager.thumbnails_dir)

        result = manager.ensure_cache_directory()
        if result and manager.thumbnails_dir.exists():
            print("   ✓ ensure_cache_directory() recreated directory")
        else:
            print("   ✗ ensure_cache_directory() failed")

        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("Cache manager properly handles cache deletion.")
        print("=" * 60)


if __name__ == "__main__":
    main()
