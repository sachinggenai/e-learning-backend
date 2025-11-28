"""Sanitization utilities for SCORM content."""
from typing import Optional
import html
import re


def sanitize_text(text: str) -> str:
    """Sanitize plain text by HTML-escaping special characters."""
    return html.escape(text)


def sanitize_html(html_content: str) -> str:
    """Sanitize HTML content while preserving safe tags.
    
    This is a basic sanitizer. In production, use bleach or BeautifulSoup.
    """
    try:
        import bleach
        
        ALLOWED_TAGS = [
            'p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3',
            'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'a', 'span',
            'div', 'img', 'code', 'pre', 'blockquote'
        ]
        ALLOWED_ATTRS = {
            'a': ['href', 'title', 'target'],
            'img': ['src', 'alt', 'width', 'height'],
            'span': ['class'],
            'div': ['class'],
        }
        
        return bleach.clean(
            html_content,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            strip=True
        )
    except ImportError:
        # Fallback: escape everything if bleach not available
        return html.escape(html_content)


def sanitize_mcq_options(options: list) -> list:
    """Sanitize MCQ options while preserving structure.
    
    CRITICAL: Preserves isCorrect as boolean.
    """
    sanitized = []
    for opt in options:
        sanitized.append({
            'id': sanitize_text(str(opt.get('id', ''))),
            'text': sanitize_html(opt.get('text', '')),
            'isCorrect': bool(opt.get('isCorrect', False))
        })
    return sanitized


def sanitize_url(url: str) -> Optional[str]:
    """Validate and sanitize URLs."""
    if not url:
        return None
    
    # Basic URL validation
    if not re.match(r'^https?://', url):
        return None
    
    # Remove potential XSS vectors
    url = url.replace('javascript:', '').replace('data:', '')
    
    return url


def strip_script_tags(content: str) -> str:
    """Remove all script tags from content."""
    return re.sub(
        r'<script[^>]*>.*?</script>',
        '',
        content,
        flags=re.DOTALL | re.IGNORECASE
    )
