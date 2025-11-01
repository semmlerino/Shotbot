#!/usr/bin/env python3
"""Command-line version of Transfer.py for automated base64 encoding of directories.

This script provides the core encoding functionality from Transfer.py without the GUI,
suitable for use in automated workflows and git hooks.
"""

import argparse
import base64
import io
import json
import os
import sys
import tarfile
from datetime import datetime
from typing import List, Tuple


class FolderEncoder:
    """Handles folder encoding to base64 with optional chunking."""

    def __init__(self, chunk_size_kb: int = 0, verbose: bool = False):
        """Initialize the encoder.

        Args:
            chunk_size_kb: Size of each chunk in KB (0 for no chunking)
            verbose: Enable verbose output
        """
        self.chunk_size_kb = chunk_size_kb
        self.verbose = verbose

    def encode_folder(self, folder_path: str) -> Tuple[str, List[str]]:
        """Encode a folder to base64.

        Args:
            folder_path: Path to the folder to encode

        Returns:
            Tuple of (full encoded string, list of chunks if chunking enabled)
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        if not os.path.isdir(folder_path):
            raise ValueError(f"Path is not a directory: {folder_path}")

        if self.verbose:
            print(f"Encoding folder: {folder_path}", file=sys.stderr)

        # Create tar archive in memory
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            tar.add(folder_path, arcname=os.path.basename(folder_path))

        # Encode to base64
        tar_buffer.seek(0)
        tar_bytes = tar_buffer.read()
        encoded = base64.b64encode(tar_bytes).decode("utf-8")

        if self.verbose:
            print(f"Encoded size: {len(encoded)} bytes", file=sys.stderr)

        # Handle chunking if requested
        chunks = []
        if self.chunk_size_kb > 0:
            chunks = self._split_into_chunks(encoded, folder_path)

        return encoded, chunks

    def _split_into_chunks(self, encoded: str, folder_path: str) -> List[str]:
        """Split encoded data into chunks.

        Args:
            encoded: The base64 encoded string
            folder_path: Original folder path for metadata

        Returns:
            List of chunk strings with headers
        """
        chunk_size_chars = self.chunk_size_kb * 1024
        total_chunks = (len(encoded) + chunk_size_chars - 1) // chunk_size_chars

        if self.verbose:
            print(
                f"Creating {total_chunks} chunks of {self.chunk_size_kb}KB each",
                file=sys.stderr,
            )

        chunks = []
        folder_name = os.path.basename(folder_path)

        for i in range(total_chunks):
            start = i * chunk_size_chars
            end = min((i + 1) * chunk_size_chars, len(encoded))
            chunk_data = encoded[start:end]

            # Add header with chunk info (compatible with Transfer.py format)
            chunk_with_header = (
                f"FOLDER_TRANSFER_V1|{i + 1}|{total_chunks}|{folder_name}\n{chunk_data}"
            )
            chunks.append(chunk_with_header)

        return chunks


def get_folder_size(folder_path: str) -> int:
    """Calculate total size of a folder in bytes.

    Args:
        folder_path: Path to the folder

    Returns:
        Total size in bytes
    """
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
    return total_size


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Encode a folder to base64 format (compatible with Transfer.py)"
    )
    parser.add_argument("folder", help="Path to the folder to encode")
    parser.add_argument(
        "-o", "--output", help="Output file (default: stdout)", default=None
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=0,
        help="Chunk size in KB (0 for no chunking, default: 0)",
    )
    parser.add_argument(
        "--chunk-dir", help="Directory to save individual chunk files", default=None
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--metadata", action="store_true", help="Include metadata JSON with output"
    )
    parser.add_argument(
        "--single-file",
        action="store_true",
        help="When chunking, combine all chunks into a single file",
    )

    args = parser.parse_args()

    # Validate folder path
    folder_path = os.path.abspath(args.folder)
    if not os.path.exists(folder_path):
        print(f"Error: Folder not found: {folder_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(folder_path):
        print(f"Error: Path is not a directory: {folder_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # Calculate folder size
        folder_size = get_folder_size(folder_path)
        if args.verbose:
            size_mb = folder_size / (1024 * 1024)
            print(f"Folder size: {size_mb:.2f} MB", file=sys.stderr)

        # Create encoder
        encoder = FolderEncoder(chunk_size_kb=args.chunk_size, verbose=args.verbose)

        # Encode folder
        encoded, chunks = encoder.encode_folder(folder_path)

        # Prepare metadata if requested
        metadata = None
        if args.metadata:
            metadata = {
                "timestamp": datetime.now().isoformat(),
                "folder_name": os.path.basename(folder_path),
                "folder_path": folder_path,
                "original_size_bytes": folder_size,
                "encoded_size_bytes": len(encoded),
                "chunk_size_kb": args.chunk_size,
                "total_chunks": len(chunks) if chunks else 1,
                "compression_ratio": folder_size / len(encoded)
                if len(encoded) > 0
                else 0,
            }

        # Handle output
        if chunks and args.chunk_dir:
            # Save chunks to individual files
            os.makedirs(args.chunk_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = os.path.basename(folder_path)

            for i, chunk in enumerate(chunks, 1):
                chunk_file = os.path.join(
                    args.chunk_dir,
                    f"{folder_name}_{timestamp}_chunk_{i:03d}_of_{len(chunks):03d}.txt",
                )
                with open(chunk_file, "w") as f:
                    f.write(chunk)
                if args.verbose:
                    print(
                        f"Saved chunk {i}/{len(chunks)}: {chunk_file}", file=sys.stderr
                    )

            # Save metadata file if requested
            if metadata:
                metadata_file = os.path.join(
                    args.chunk_dir, f"{folder_name}_{timestamp}_metadata.json"
                )
                with open(metadata_file, "w") as f:
                    json.dump(metadata, f, indent=2)
                if args.verbose:
                    print(f"Saved metadata: {metadata_file}", file=sys.stderr)

        elif chunks and args.single_file:
            # Combine all chunks into a single file with separators
            output_content = ""
            if metadata:
                output_content += (
                    f"METADATA_START\n{json.dumps(metadata, indent=2)}\nMETADATA_END\n"
                )

            for i, chunk in enumerate(chunks, 1):
                if i > 1:
                    output_content += "\n---CHUNK_SEPARATOR---\n"
                output_content += chunk

            if args.output:
                with open(args.output, "w") as f:
                    f.write(output_content)
                if args.verbose:
                    print(f"Saved combined chunks to: {args.output}", file=sys.stderr)
            else:
                print(output_content)

        else:
            # Output single encoded string (no chunking or single chunk)
            output_content = ""
            if metadata:
                output_content += (
                    f"METADATA_START\n{json.dumps(metadata, indent=2)}\nMETADATA_END\n"
                )

            if chunks:
                # Use first chunk if chunking was done but no special output requested
                output_content += chunks[0]
            else:
                # Add header for compatibility with Transfer.py
                folder_name = os.path.basename(folder_path)
                output_content += f"FOLDER_TRANSFER_V1|1|1|{folder_name}\n{encoded}"

            if args.output:
                with open(args.output, "w") as f:
                    f.write(output_content)
                if args.verbose:
                    print(f"Saved to: {args.output}", file=sys.stderr)
            else:
                print(output_content)

        if args.verbose:
            print("Encoding completed successfully", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
