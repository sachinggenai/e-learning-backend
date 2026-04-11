"""HTML security sanitizer for template extraction.

Sanitizes HTML using bleach library with allowlist-based filtering.
Provides context-aware sanitization for different use cases.
"""

import bleach
from typing import List


class HTMLSanitizer:
    """Sanitize HTML content with context-aware filtering."""
    
    # Safe tags for preview/template content
    PREVIEW_ALLOWED_TAGS = [
        'p', 'br', 'strong', 'em', 'u', 'i', 'b',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'blockquote', 'code', 'pre',
    ]
    
    # Extended tags for full content (includes layout/media)
    CONTENT_ALLOWED_TAGS = PREVIEW_ALLOWED_TAGS + [
        'div', 'span', 'section', 'article', 'nav', 'header', 'footer',
        'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
        'a', 'img',
        'form', 'input', 'button', 'label', 'select', 'option',
        'textarea',
    ]
    
    # Allowed attributes (very restrictive)
    ALLOWED_ATTRS = {
        'a': ['href', 'title'],
        'img': ['src', 'alt', 'width', 'height'],
        'input': ['type', 'name', 'value', 'placeholder'],
        'button': ['type'],
        'form': ['action', 'method'],
        'td': ['colspan', 'rowspan'],
        'th': ['colspan', 'rowspan'],
        '*': ['class', 'id'],  # Allow class/id on all tags
    }
    
    def sanitize_preview(
        self, html: str, max_length: int = 500
    ) -> str:
        """
        Sanitize HTML for preview display.
        Removes all scripts, styles, and interactive elements.
        
        Args:
            html: HTML content to sanitize
            max_length: Maximum length of output
            
        Returns:
            Sanitized HTML safe for preview display
        """
        safe_html = bleach.clean(
            html,
            tags=self.PREVIEW_ALLOWED_TAGS,
            attributes={},  # No attributes in preview
            strip=True
        )
        
        # Truncate if too long
        if len(safe_html) > max_length:
            truncated = safe_html[:max_length]
            last_close = truncated.rfind('>')
            if last_close > 0:
                truncated = truncated[:last_close + 1]
            safe_html = truncated + '...'
        
        return safe_html
    
    def sanitize_content(self, html: str) -> str:
        """
        Sanitize HTML for full content display.
        Allows layout tags and safe attributes but removes scripts.
        
        Args:
            html: HTML content to sanitize
            
        Returns:
            Sanitized HTML safe for content display
        """
        safe_html = bleach.clean(
            html,
            tags=self.CONTENT_ALLOWED_TAGS,
            attributes=self.ALLOWED_ATTRS,
            strip=True
        )
        
        return safe_html
    
    def sanitize_text_only(self, html: str) -> str:
        """
        Extract plain text from HTML (remove all markup).
        
        Args:
            html: HTML content
            
        Returns:
            Plain text content
        """
        return bleach.clean(html, tags=[], strip=True)
    
    def sanitize_url(self, url: str) -> str:
        """
        Sanitize URL to prevent javascript: and data: attacks.
        
        Args:
            url: URL to sanitize
            
        Returns:
            Sanitized URL or '#' if invalid
        """
        import re
        
        # Remove javascript: urls
        if re.match(r'^\s*javascript:', url, re.IGNORECASE):
            return '#'
        
        # Remove data: urls with base64 (potential payload delivery)
        if re.match(r'^\s*data:.*base64', url, re.IGNORECASE):
            return '#'
        
        # Allow only http/https/relative paths/data images
        if re.match(
            r'^\s*(?:https?:|data:image/|/|\.)',
            url, re.IGNORECASE
        ):
            return bleach.clean(url, tags=[], strip=True)
        
        return '#'
