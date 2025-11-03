#!/usr/bin/env python3
"""Test shot parsing logic to ensure consistency between ws -sg and finders."""


def test_shot_extraction() -> None:
    """Test that shot extraction logic works correctly."""

    test_cases = [
        # (sequence, shot_dir, expected_shot)
        ("012_DC", "012_DC_1000", "1000"),
        ("012_DC", "012_DC_1070", "1070"),
        ("DB_271", "DB_271_1760", "1760"),
        ("FF_278", "FF_278_4380", "4380"),
        ("BRX_166", "BRX_166_0010", "0010"),
        ("BRX_170", "BRX_170_0100", "0100"),
        ("999_xx", "999_xx_999", "999"),
        # Edge cases
        ("SEQ", "SEQ_001", "001"),
        ("A", "A_100", "100"),
        ("TEST_01", "TEST_01_0050", "0050"),
        # Fallback cases
        ("SEQ", "DIFFERENT_100", "100"),  # Doesn't start with sequence
        ("SEQ", "NOUNDERSCORES", "NOUNDERSCORES"),  # No underscores
    ]

    for sequence, shot_dir, expected_shot in test_cases:
        # This is the logic used in all three finders
        if shot_dir.startswith(f"{sequence}_"):
            # Remove the sequence prefix to get the shot number
            shot = shot_dir[len(sequence) + 1 :]  # +1 for the underscore
        else:
            # Fallback: use the last part after underscore
            shot_parts = shot_dir.rsplit("_", 1)
            shot = shot_parts[1] if len(shot_parts) == 2 else shot_dir

        if shot != expected_shot:
            print(f"❌ FAILED: sequence={sequence}, shot_dir={shot_dir}")
            print(f"   Expected: {expected_shot}, Got: {shot}")
        else:
            print(f"✅ PASSED: {shot_dir} -> {shot}")

    # Test that full_name reconstruction works
    print("\n--- Testing full_name reconstruction ---")
    for sequence, shot_dir, _expected_shot in test_cases[:7]:  # Test main cases
        if shot_dir.startswith(f"{sequence}_"):
            shot = shot_dir[len(sequence) + 1 :]
            full_name = f"{sequence}_{shot}"
            if full_name == shot_dir:
                print(f"✅ full_name matches: {full_name} == {shot_dir}")
            else:
                print(f"❌ full_name mismatch: {full_name} != {shot_dir}")


if __name__ == "__main__":
    test_shot_extraction()
