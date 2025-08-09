"""Configuration and fixtures for integration tests."""

import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "performance: mark test as a performance benchmark"
    )
    config.addinivalue_line("markers", "stress: mark test as a stress test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to handle custom markers."""
    # Add integration marker to all tests in this directory
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def integration_temp_dir():
    """Session-scoped temporary directory for integration tests."""
    with tempfile.TemporaryDirectory(prefix="shotbot_integration_") as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_shows_structure(integration_temp_dir):
    """Create a realistic shows directory structure for integration tests."""
    shows_root = integration_temp_dir / "shows"

    # Create multiple shows
    show_configs = [
        ("testshow", ["101_ABC", "102_DEF"], ["0010", "0020", "0030"]),
        ("prodshow", ["001_TST", "002_VFX"], ["0001", "0002", "0003", "0004"]),
        ("demoshow", ["SEQ001", "SEQ002"], ["shot_001", "shot_002"]),
    ]

    created_shots = []

    for show_name, sequences, shots in show_configs:
        for seq_name in sequences:
            for shot_name in shots:
                full_shot_name = f"{seq_name}_{shot_name}"
                shot_path = shows_root / show_name / "shots" / seq_name / full_shot_name

                # Create standard directory structure
                dirs_to_create = [
                    "editorial/ref",
                    "sourceimages/plates/FG01/v001/exr/2048x1152",
                    "sourceimages/plates/BG01/v001/exr/2048x1152",
                    "user/alice/mm/3de/mm-default/scenes/scene/FG01/v001",
                    "user/bob/mm/3de/mm-default/scenes/scene/BG01/v001",
                ]

                for dir_path in dirs_to_create:
                    full_dir = shot_path / dir_path
                    full_dir.mkdir(parents=True, exist_ok=True)

                # Create files
                # Thumbnail
                (shot_path / "editorial/ref/ref.jpg").touch()

                # Raw plates
                for plate_name in ["FG01", "BG01"]:
                    plate_dir = (
                        shot_path
                        / "sourceimages/plates"
                        / plate_name
                        / "v001/exr/2048x1152"
                    )
                    for frame in [1001, 1002]:
                        plate_file = (
                            plate_dir
                            / f"{full_shot_name}_turnover-plate_{plate_name}_aces_v001.{frame}.exr"
                        )
                        plate_file.touch()

                # 3DE scenes
                (
                    shot_path
                    / "user/alice/mm/3de/mm-default/scenes/scene/FG01/v001/alice_scene.3de"
                ).touch()
                (
                    shot_path
                    / "user/bob/mm/3de/mm-default/scenes/scene/BG01/v001/bob_scene.3de"
                ).touch()

                # Create shot object
                from shot_model import Shot

                shot = Shot(show_name, seq_name, shot_name, str(shot_path))
                created_shots.append(shot)

    return {
        "shows_root": shows_root,
        "shots": created_shots,
        "show_configs": show_configs,
    }


@pytest.fixture
def performance_dataset(integration_temp_dir):
    """Create a large dataset for performance testing."""
    perf_root = integration_temp_dir / "performance"
    shots = []

    # Create a large but manageable dataset
    for show_idx in range(3):
        for seq_idx in range(5):
            for shot_idx in range(10):  # 3×5×10 = 150 shots
                show_name = f"perfshow{show_idx}"
                seq_name = f"PERF{seq_idx:02d}"
                shot_name = f"shot_{shot_idx:03d}"
                full_shot_name = f"{seq_name}_{shot_name}"

                shot_path = perf_root / show_name / "shots" / seq_name / full_shot_name

                # Minimal structure for performance testing
                thumb_dir = shot_path / "editorial/ref"
                thumb_dir.mkdir(parents=True)
                (thumb_dir / "ref.jpg").touch()

                # Raw plate
                plate_dir = shot_path / "sourceimages/plates/FG01/v001/exr/4096x2304"
                plate_dir.mkdir(parents=True)
                (
                    plate_dir
                    / f"{full_shot_name}_turnover-plate_FG01_aces_v001.1001.exr"
                ).touch()

                from shot_model import Shot

                shot = Shot(show_name, seq_name, shot_name, str(shot_path))
                shots.append(shot)

    return {"root": perf_root, "shots": shots, "count": len(shots)}


@pytest.fixture
def isolated_cache_dir():
    """Create an isolated cache directory for each test."""
    with tempfile.TemporaryDirectory(prefix="shotbot_cache_") as cache_dir:
        yield Path(cache_dir)


@pytest.fixture
def vfx_production_environment(integration_temp_dir):
    """Create realistic VFX production environment for comprehensive testing."""
    shows_root = integration_temp_dir / "vfx_production"

    # Production shows with realistic structure
    production_config = {
        "feature_film": {
            "sequences": ["SEQ_001_FOREST", "SEQ_002_CASTLE", "SEQ_003_BATTLE"],
            "shots_per_seq": 25,
            "artists": [
                "comp_lead",
                "comp_artist_1",
                "comp_artist_2",
                "track_lead",
                "track_junior",
            ],
            "plates": ["BG01", "FG01", "CHAR01", "ENV01", "FX01"],
            "departments": ["comp", "track", "paint", "roto"],
        },
        "episodic_tv": {
            "sequences": ["EP101", "EP102", "EP103"],
            "shots_per_seq": 15,
            "artists": ["senior_comp", "mid_comp", "junior_comp", "track_artist"],
            "plates": ["BG01", "FG01", "CHAR01"],
            "departments": ["comp", "track"],
        },
        "commercial": {
            "sequences": ["MAIN", "ALT_VERSION"],
            "shots_per_seq": 8,
            "artists": ["lead_artist", "generalist"],
            "plates": ["BG01", "FG01"],
            "departments": ["comp"],
        },
    }

    created_shots = []
    created_3de_scenes = []
    created_thumbnails = []
    created_plates = []

    for show_name, config in production_config.items():
        for seq_name in config["sequences"]:
            for shot_idx in range(1, config["shots_per_seq"] + 1):
                shot_name = f"{seq_name}_{shot_idx:04d}"
                shot_path = shows_root / show_name / "shots" / seq_name / shot_name

                # Create comprehensive directory structure
                directories = [
                    "publish/editorial/cutref/v001/jpg/1920x1080",
                    "publish/editorial/cutref/v001/jpg/4096x2304",
                    "publish/turnover/plate/input_plate",
                    "work/comp/nuke/scenes",
                    "work/comp/nuke/scripts",
                    "work/comp/nuke/renders",
                    "mm/nuke/comp/scenes",
                    "mm/nuke/comp/scripts",
                    "mm/nuke/undistortion",
                    "mm/3de/mm-default/scenes/scene",
                    "sourceimages/reference",
                    "sourceimages/plates",
                    "render/comp/beauty/exr",
                    "render/comp/passes/exr",
                ]

                for directory in directories:
                    dir_path = shot_path / directory
                    dir_path.mkdir(parents=True, exist_ok=True)

                # Create thumbnails with different resolutions
                for resolution in ["1920x1080", "4096x2304"]:
                    thumb_path = (
                        shot_path / "publish/editorial/cutref/v001/jpg" / resolution
                    )
                    thumb_file = thumb_path / f"{shot_name}_cutref_v001.jpg"
                    thumb_file.write_bytes(
                        b"\\xff\\xd8\\xff\\xe0\\x00\\x10JFIF" + b"\\x00" * 200
                    )  # Minimal JPEG
                    created_thumbnails.append(thumb_file)

                # Create 3DE scenes for different artists and plates
                for artist in config["artists"]:
                    if (
                        "comp" in artist or "track" in artist
                    ):  # Only comp/track artists use 3DE
                        for plate in config["plates"][:2]:  # Only BG01 and FG01 for 3DE
                            for version in ["v001", "v002", "v003"]:
                                scene_dir = (
                                    shot_path
                                    / "user"
                                    / artist
                                    / "mm"
                                    / "3de"
                                    / "mm-default"
                                    / "scenes"
                                    / "scene"
                                    / plate
                                    / version
                                )
                                scene_dir.mkdir(parents=True, exist_ok=True)

                                scene_file = (
                                    scene_dir
                                    / f"{shot_name}_{artist}_{plate}_{version}.3de"
                                )
                                scene_file.write_bytes(
                                    b"3DE_SCENE_DATA" * 50
                                )  # Realistic file size

                                # Set realistic modification times
                                import time

                                base_time = time.time() - (
                                    30 * 24 * 3600
                                )  # 30 days ago
                                version_offset = (
                                    int(version[1:]) * 86400
                                )  # Days between versions
                                artist_offset = (
                                    hash(artist) % 3600
                                )  # Spread artists across hours
                                mtime = base_time + version_offset + artist_offset
                                os.utime(scene_file, (mtime, mtime))

                                created_3de_scenes.append(
                                    {
                                        "file": scene_file,
                                        "show": show_name,
                                        "sequence": seq_name,
                                        "shot": shot_name,
                                        "artist": artist,
                                        "plate": plate,
                                        "version": version,
                                        "mtime": mtime,
                                    }
                                )

                # Create shot object
                from shot_model import Shot

                shot = Shot(
                    show_name, seq_name, shot_name.split("_")[-1], str(shot_path)
                )
                created_shots.append(shot)

    # Create workspace output
    workspace_lines = [f"workspace {shot.workspace_path}" for shot in created_shots]
    ws_output = "\\n".join(workspace_lines)

    return {
        "shows_root": shows_root,
        "shots": created_shots,
        "3de_scenes": created_3de_scenes,
        "thumbnails": created_thumbnails,
        "plates": created_plates,
        "workspace_output": ws_output,
        "production_config": production_config,
        "total_shots": len(created_shots),
        "total_3de_scenes": len(created_3de_scenes),
        "total_thumbnails": len(created_thumbnails),
        "total_plates": len(created_plates),
    }
