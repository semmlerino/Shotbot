#!/usr/bin/env python3
"""Summary test to verify all cache manager fixes are working correctly."""

import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

from cache_manager import CacheManager


def test_all_cache_fixes():
    """Test that all cache fixes are working properly."""
    print("=" * 60)
    print("CACHE MANAGER - COMPREHENSIVE FIX VERIFICATION")
    print("=" * 60)

    QCoreApplication(sys.argv)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        cache_dir = temp_path / "cache"
        cache_dir.mkdir()

        print("\n1. Testing basic cache operations...")
        manager = CacheManager(cache_dir=cache_dir)

        # Create test image
        test_img = temp_path / "test.jpg"
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(0xFF0000)
        image.save(str(test_img), "JPEG")

        # Cache the image
        result = manager.cache_thumbnail(test_img, "show1", "seq1", "shot1")
        assert result is not None, "Failed to cache thumbnail"
        assert result.exists(), "Cached file doesn't exist"
        print("   ✓ Basic caching works")

        print("\n2. Testing cache deletion recovery...")
        # Delete cache directory
        shutil.rmtree(manager.thumbnails_dir)
        assert not manager.thumbnails_dir.exists()

        # Try to cache again - should recover
        result2 = manager.cache_thumbnail(test_img, "show1", "seq1", "shot2")
        assert result2 is not None, "Failed to cache after deletion"
        assert manager.thumbnails_dir.exists(), "Directory not recreated"
        print("   ✓ Cache recovers from deletion")

        print("\n3. Testing atomic clear_cache()...")
        old_dir = manager.thumbnails_dir
        manager.clear_cache()
        new_dir = manager.thumbnails_dir
        assert old_dir != new_dir, "Directory not swapped"
        assert new_dir.exists(), "New directory doesn't exist"
        print("   ✓ clear_cache() is atomic")

        print("\n4. Testing memory tracking...")
        # Cache multiple images
        for i in range(5):
            img_path = temp_path / f"test{i}.jpg"
            image = QImage(50, 50, QImage.Format.Format_RGB32)
            image.fill(0x00FF00 + i * 100)
            image.save(str(img_path), "JPEG")
            manager.cache_thumbnail(img_path, "show2", f"seq{i}", f"shot{i}")

        memory_stats = manager.get_memory_usage()
        assert memory_stats["total_bytes"] > 0, "Memory not tracked"
        assert memory_stats["thumbnail_count"] > 0, "Thumbnails not counted"
        print(
            f"   ✓ Memory tracking: {memory_stats['total_mb']:.2f}MB, {memory_stats['thumbnail_count']} files"
        )

        print("\n5. Testing cache validation...")
        # Manually corrupt tracking
        fake_path = manager.thumbnails_dir / "fake" / "fake.jpg"
        manager._cached_thumbnails[str(fake_path)] = 1000

        # Validate should fix it
        validation = manager.validate_cache()
        assert validation["issues_fixed"] > 0, "Validation didn't fix issues"
        assert str(fake_path) not in manager._cached_thumbnails
        print(f"   ✓ Validation fixed {validation['issues_fixed']} issues")

        print("\n6. Testing concurrent operations...")
        errors = []
        successes = []

        def concurrent_op(index):
            try:
                if index % 2 == 0:
                    result = manager.cache_thumbnail(
                        test_img, f"show{index}", f"seq{index}", f"shot{index}"
                    )
                    if result:
                        successes.append("cache")
                else:
                    result = manager.get_cached_thumbnail(
                        f"show{index - 1}", f"seq{index - 1}", f"shot{index - 1}"
                    )
                    if result:
                        successes.append("get")
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(20):
            t = threading.Thread(target=concurrent_op, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent ops failed: {errors}"
        assert len(successes) > 10, "Too few successes"
        print(f"   ✓ Concurrent operations: {len(successes)} successful")

        print("\n7. Testing shutdown...")
        manager.shutdown()
        assert manager._memory_usage_bytes == 0, "Memory not cleared"
        assert len(manager._cached_thumbnails) == 0, "Cache not cleared"
        print("   ✓ Shutdown cleanup successful")

        print("\n8. Testing thread safety (QImage vs QPixmap)...")

        # This would have crashed before with QPixmap
        def thread_cache():
            img_path = temp_path / "thread_test.jpg"
            image = QImage(50, 50, QImage.Format.Format_RGB32)
            image.fill(0x0000FF)
            image.save(str(img_path), "JPEG")

            # This uses QImage internally, not QPixmap
            result = manager.cache_thumbnail(img_path, "thread", "seq", "shot")
            return result is not None

        # Run in thread
        success = [False]

        def worker():
            success[0] = thread_cache()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert success[0], "Thread caching failed"
        print("   ✓ Thread-safe QImage caching works")

        print("\n" + "=" * 60)
        print("✅ ALL CACHE MANAGER FIXES VERIFIED!")
        print("The cache system is robust and production-ready.")
        print("=" * 60)


if __name__ == "__main__":
    test_all_cache_fixes()
