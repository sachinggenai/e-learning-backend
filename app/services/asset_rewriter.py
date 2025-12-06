"""
Asset Rewriter for normalizing file paths and rewriting URLs in content.

Handles HTML content rewriting, CSS URL rewriting, and path normalization.
"""

import re
import logging
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    BEAUTIFULSOUP_AVAILABLE = True
except ImportError:
    BEAUTIFULSOUP_AVAILABLE = False
    logger.warning("BeautifulSoup not available; using regex fallback for HTML rewriting")


class AmbiguousAssetError(Exception):
    """Raised when an asset reference is ambiguous."""
    pass


class AssetRewriter:
    """Rewrites asset references in content to use API URLs."""

    def __init__(self, base_url: str = "/api/v1/media"):
        """
        Initialize asset rewriter.

        Args:
            base_url: Base URL for media endpoint (e.g., /api/v1/media)
        """
        self.base_url = base_url.rstrip("/")

    def build_file_map(self, zip_contents: Dict[str, bytes]) -> Dict[str, List[str]]:
        """
        Build a map of filenames to their paths in the ZIP.

        Args:
            zip_contents: Dict of {file_path: file_content} from ZIP

        Returns:
            Dict of {filename: [list of full paths]}
        """
        file_map: Dict[str, List[str]] = {}

        for file_path in zip_contents.keys():
            filename = Path(file_path).name

            # Skip common non-asset files
            if self._is_asset(filename):
                if filename not in file_map:
                    file_map[filename] = []
                file_map[filename].append(file_path)

        return file_map

    def detect_ambiguous_assets(self, file_map: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Detect ambiguous assets (duplicates with different paths).

        Args:
            file_map: File map from build_file_map()

        Returns:
            Dict of {filename: [list of paths]} for ambiguous files
        """
        ambiguous = {}
        for filename, paths in file_map.items():
            if len(paths) > 1:
                ambiguous[filename] = paths

        return ambiguous

    def rewrite_html_content(
        self,
        html_content: str,
        file_map: Dict[str, List[str]],
        course_id: str,
        ambiguous_assets: Optional[Dict[str, List[str]]] = None
    ) -> Tuple[str, List[str]]:
        """
        Rewrite HTML content to point assets to API URLs.

        Args:
            html_content: HTML string containing asset references
            file_map: File map from build_file_map()
            course_id: Course ID for URL generation
            ambiguous_assets: Set of ambiguous filenames to skip

        Returns:
            Tuple of (rewritten_html, list_of_warnings)
        """
        if ambiguous_assets is None:
            ambiguous_assets = {}

        warnings = []

        if BEAUTIFULSOUP_AVAILABLE:
            try:
                soup = BeautifulSoup(html_content, "html.parser")

                # Rewrite img src
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    if src:
                        new_src, warning = self._resolve_asset_path(
                            src, file_map, course_id, ambiguous_assets
                        )
                        if warning:
                            warnings.append(warning)
                        elif new_src:
                            img["src"] = new_src

                # Rewrite a href
                for link in soup.find_all("a"):
                    href = link.get("href", "")
                    if href and not href.startswith("#") and not href.startswith("http"):
                        new_href, warning = self._resolve_asset_path(
                            href, file_map, course_id, ambiguous_assets
                        )
                        if warning:
                            warnings.append(warning)
                        elif new_href:
                            link["href"] = new_href

                # Rewrite style attributes with url()
                for elem in soup.find_all(style=True):
                    style = elem.get("style", "")
                    new_style, style_warnings = self._rewrite_css_urls(
                        style, file_map, course_id, ambiguous_assets
                    )
                    if style_warnings:
                        warnings.extend(style_warnings)
                    if new_style:
                        elem["style"] = new_style

                return str(soup), warnings

            except Exception as e:
                logger.warning(f"BeautifulSoup parsing failed: {e}, using regex fallback")
                # Fall through to regex approach

        # Regex fallback
        return self._rewrite_html_regex(
            html_content, file_map, course_id, ambiguous_assets
        )

    def rewrite_css_content(
        self,
        css_content: str,
        file_map: Dict[str, List[str]],
        course_id: str,
        ambiguous_assets: Optional[Dict[str, List[str]]] = None
    ) -> Tuple[str, List[str]]:
        """
        Rewrite CSS content to point assets to API URLs.

        Args:
            css_content: CSS string containing url() references
            file_map: File map from build_file_map()
            course_id: Course ID for URL generation
            ambiguous_assets: Set of ambiguous filenames

        Returns:
            Tuple of (rewritten_css, list_of_warnings)
        """
        return self._rewrite_css_urls(
            css_content, file_map, course_id, ambiguous_assets or {}
        )

    def _resolve_asset_path(
        self,
        relative_path: str,
        file_map: Dict[str, List[str]],
        course_id: str,
        ambiguous_assets: Dict[str, List[str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve a relative asset path to an API URL.

        Returns:
            Tuple of (new_url, warning_message)
        """
        if not relative_path or relative_path.startswith(("http://", "https://")):
            return None, None

        # Normalize path (remove ../)
        normalized = Path(relative_path).name  # Just get filename

        if normalized in ambiguous_assets:
            warning = f"Ambiguous asset '{normalized}': {len(ambiguous_assets[normalized])} paths found, skipping rewrite"
            return None, warning

        if normalized in file_map:
            paths = file_map[normalized]
            if len(paths) == 1:
                # Generate API URL
                uuid_part = self._generate_asset_id(paths[0])
                api_url = f"{self.base_url}/{course_id}/{uuid_part}"
                return api_url, None
            else:
                return None, f"Ambiguous asset: {len(paths)} paths found for {normalized}"

        return None, f"Asset not found: {relative_path}"

    def _rewrite_css_urls(
        self,
        css_content: str,
        file_map: Dict[str, List[str]],
        course_id: str,
        ambiguous_assets: Dict[str, List[str]]
    ) -> Tuple[str, List[str]]:
        """Rewrite url() references in CSS."""
        warnings = []

        # Pattern: url('path') or url("path") or url(path)
        pattern = r"url\(['\"]?([^'\")]+)['\"]?\)"

        def replacer(match):
            old_url = match.group(1)
            new_url, warning = self._resolve_asset_path(
                old_url, file_map, course_id, ambiguous_assets
            )
            if warning:
                warnings.append(warning)
            if new_url:
                return f"url('{new_url}')"
            return match.group(0)

        rewritten = re.sub(pattern, replacer, css_content)
        return rewritten, warnings

    def _rewrite_html_regex(
        self,
        html_content: str,
        file_map: Dict[str, List[str]],
        course_id: str,
        ambiguous_assets: Dict[str, List[str]]
    ) -> Tuple[str, List[str]]:
        """Fallback HTML rewriting using regex."""
        warnings = []

        # Rewrite src attributes
        def src_replacer(match):
            old_src = match.group(1)
            new_src, warning = self._resolve_asset_path(
                old_src, file_map, course_id, ambiguous_assets
            )
            if warning:
                warnings.append(warning)
            if new_src:
                return f'src="{new_src}"'
            return match.group(0)

        html_content = re.sub(r'src=["\']([^"\']+)["\']', src_replacer, html_content)

        # Rewrite href attributes
        def href_replacer(match):
            old_href = match.group(1)
            if not old_href.startswith("#") and not old_href.startswith("http"):
                new_href, warning = self._resolve_asset_path(
                    old_href, file_map, course_id, ambiguous_assets
                )
                if warning:
                    warnings.append(warning)
                if new_href:
                    return f'href="{new_href}"'
            return match.group(0)

        html_content = re.sub(r'href=["\']([^"\']+)["\']', href_replacer, html_content)

        return html_content, warnings

    def _is_asset(self, filename: str) -> bool:
        """Check if filename looks like an asset."""
        asset_extensions = {
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
            ".mp3", ".mp4", ".webm", ".wav", ".ogg",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx"
        }
        return any(filename.lower().endswith(ext) for ext in asset_extensions)

    def _generate_asset_id(self, file_path: str) -> str:
        """Generate a unique ID for an asset based on its path."""
        import hashlib
        return hashlib.md5(file_path.encode()).hexdigest()[:12]
