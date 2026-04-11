"""CSS security sanitizer for template extraction.

Sanitizes CSS for security risks including:
- javascript: URLs in url()
- External URLs (data exfiltration)
- @import with external sources
- Dangerous properties (behavior, binding)
"""

import re
from typing import List, Tuple
from bs4 import BeautifulSoup


class CSSSecuritySanitizer:
    """Sanitize CSS for security risks."""
    
    DANGEROUS_PROPERTIES = [
        'behavior',  # IE-specific, can execute scripts
        'binding',   # XBL binding (Firefox)
        '-moz-binding',
    ]
    
    DANGEROUS_FUNCTIONS = [
        # javascript: in url()
        r'url\s*\(\s*["\']?\s*javascript:',
        # IE CSS expressions
        r'expression\s*\(',
        # javascript: in @import
        r'@import\s+["\']?\s*javascript:',
    ]
    
    def sanitize_css(self, css_content: str) -> Tuple[str, List[str]]:
        """
        Sanitize CSS content.
        
        Args:
            css_content: CSS source code to sanitize
            
        Returns:
            (sanitized_css, list_of_warnings)
        """
        warnings = []
        sanitized = css_content
        
        # Remove dangerous properties
        for prop in self.DANGEROUS_PROPERTIES:
            pattern = rf'{prop}\s*:[^;]+;'
            if re.search(pattern, sanitized, re.IGNORECASE):
                warnings.append(f"Removed dangerous CSS property: {prop}")
                sanitized = re.sub(
                    pattern, '', sanitized, flags=re.IGNORECASE
                )
        
        # Remove dangerous functions
        for func_pattern in self.DANGEROUS_FUNCTIONS:
            if re.search(func_pattern, sanitized, re.IGNORECASE):
                warnings.append(
                    f"Removed dangerous CSS function: {func_pattern}"
                )
                sanitized = re.sub(
                    func_pattern, '/* REMOVED */',
                    sanitized, flags=re.IGNORECASE
                )
        
        # Remove external URLs (data exfiltration risk)
        pattern = (
            r'url\s*\(\s*["\']?\s*https?://'
            r'(?!localhost|127\.0\.0\.1)[^)]+\)'
        )
        external_urls = re.findall(pattern, sanitized, re.IGNORECASE)
        if external_urls:
            warnings.append(
                f"Removed {len(external_urls)} external URLs from CSS"
            )
            sanitized = re.sub(
                pattern, 'url(#)', sanitized, flags=re.IGNORECASE
            )
        
        # Remove @import with external URLs
        import_pattern = r'@import\s+["\']?\s*https?://[^;"\']+["\']?;?'
        if re.search(import_pattern, sanitized, re.IGNORECASE):
            warnings.append("Removed external @import statements")
            sanitized = re.sub(
                import_pattern, '', sanitized, flags=re.IGNORECASE
            )
        
        return sanitized, warnings
    
    def extract_and_sanitize_inline_styles(
        self, html: str
    ) -> Tuple[str, List[str]]:
        """
        Sanitize inline style attributes in HTML.
        
        Args:
            html: HTML source code
            
        Returns:
            (sanitized_html, list_of_warnings)
        """
        soup = BeautifulSoup(html, 'html.parser')
        warnings = []
        
        for tag in soup.find_all(style=True):
            original_style = tag['style']
            sanitized_style, style_warnings = self.sanitize_css(
                original_style
            )
            
            if style_warnings:
                warnings.extend([
                    f"In {tag.name}: {w}" for w in style_warnings
                ])
            
            tag['style'] = sanitized_style
        
        return str(soup), warnings
