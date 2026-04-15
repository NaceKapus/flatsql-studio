"""Snippet initialization utilities for shipping built-in SQL examples."""

from __future__ import annotations

import os
import shutil

from flatsql.config import SNIPPETS_DIR, BUILTIN_SNIPPETS_FOLDER_NAME, BUILTIN_SNIPPETS_SOURCE_DIR
from flatsql.core.logger import get_logger

logger = get_logger(__name__)


def _copy_builtin_snippets(source_dir: str, target_dir: str) -> None:
    """Copy built-in snippet files into the user directory without overwrite."""
    for current_root, _, file_names in os.walk(source_dir):
        relative_dir = os.path.relpath(current_root, source_dir)
        current_target_dir = target_dir

        if relative_dir != ".":
            current_target_dir = os.path.join(target_dir, relative_dir)

        os.makedirs(current_target_dir, exist_ok=True)

        for file_name in sorted(file_names):
            if not file_name.endswith(".sql"):
                continue

            source_path = os.path.join(current_root, file_name)
            target_path = os.path.join(current_target_dir, file_name)

            if os.path.exists(target_path):
                continue

            try:
                shutil.copy2(source_path, target_path)
            except OSError:
                logger.exception("Failed to copy built-in snippet: %s", source_path)


def ensure_snippets_initialized() -> None:
    """Ensure user snippet directory exists and seed built-in snippets once.

    Built-in snippets are copied from packaged templates into the user's
    snippets tree without overwriting user-modified files.
    """
    os.makedirs(SNIPPETS_DIR, exist_ok=True)

    if not os.path.isdir(BUILTIN_SNIPPETS_SOURCE_DIR):
        return

    target_dir = os.path.join(SNIPPETS_DIR, BUILTIN_SNIPPETS_FOLDER_NAME)

    os.makedirs(target_dir, exist_ok=True)

    _copy_builtin_snippets(BUILTIN_SNIPPETS_SOURCE_DIR, target_dir)
