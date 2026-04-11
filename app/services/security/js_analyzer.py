"""JavaScript security analyzer for template extraction.

Analyzes JavaScript code for security risks including:
- Network calls (fetch, XMLHttpRequest, AJAX)
- Cookie/storage access
- Code execution (eval, Function)
- DOM manipulation vulnerabilities
- External resource loading
"""

import re
from typing import Dict, List


class JavaScriptSecurityAnalyzer:
    """Analyze JavaScript for malicious patterns and security risks."""
    
    # Dangerous patterns that should NEVER be in templates
    BLACKLIST_PATTERNS = [
        r'fetch\s*\(',                    # Network calls
        r'XMLHttpRequest',                # AJAX
        r'\.ajax\(',                      # jQuery AJAX
        r'document\.cookie',              # Cookie access
        r'localStorage',                  # Storage access
        r'sessionStorage',
        r'eval\s*\(',                     # Code execution
        r'Function\s*\(',                 # Dynamic function creation
        # setTimeout with string (code execution)
        r'setTimeout\s*\([^,]*[\'"]',
        r'setInterval\s*\([^,]*[\'"]',
        r'innerHTML\s*=',                 # DOM manipulation (XSS vector)
        r'outerHTML\s*=',
        r'document\.write',               # Direct DOM write
        r'window\.location\s*=',          # Navigation hijacking
        r'window\.open\s*\(',             # Popup attacks
        r'import\s*\(',                   # Dynamic imports
        r'require\s*\(',                  # CommonJS imports
    ]
    
    # Allowed operations (safe DOM manipulation)
    WHITELIST_OPERATIONS = {
        'querySelector', 'querySelectorAll',
        'getElementById', 'getElementsByClassName', 'getElementsByTagName',
        'addEventListener', 'removeEventListener',
        'classList.add', 'classList.remove', 'classList.toggle',
        'textContent', 'innerText',
        'getAttribute', 'setAttribute', 'removeAttribute',
        'console.log', 'console.error', 'console.warn',
        'Math.', 'parseInt', 'parseFloat', 'isNaN',
        'Array.', 'String.', 'Object.', 'Number.',
    }
    
    def analyze_script(self, js_code: str) -> Dict:
        """
        Analyze JavaScript code for security risks.
        
        Args:
            js_code: JavaScript source code to analyze
            
        Returns:
            {
                "is_safe": bool,
                "violations": List[str],
                "safe_functions": List[str],
                "risk_score": int (0-100),
                "recommended_action": "ALLOW" | "SANITIZE" | "REJECT"
            }
        """
        violations = []
        risk_score = 0
        
        # Check for blacklisted patterns
        for pattern in self.BLACKLIST_PATTERNS:
            matches = re.findall(pattern, js_code, re.IGNORECASE)
            if matches:
                violations.append(f"Blacklisted pattern found: {pattern}")
                risk_score += 20
        
        # Check for external URLs
        url_pattern = r'https?://(?!localhost|127\.0\.0\.1)[^\s\'"]+'  # noqa
        external_urls = re.findall(url_pattern, js_code)
        if external_urls:
            violations.append(
                f"External URLs found: {len(external_urls)} URL(s)"
            )
            risk_score += 30
        
        # Check for Base64 encoded content (obfuscation attempt)
        if re.search(r'atob\s*\(|btoa\s*\(', js_code):
            violations.append(
                "Base64 encoding/decoding detected (possible obfuscation)"
            )
            risk_score += 25
        
        # Extract function names
        func_pattern = r'function\s+(\w+)\s*\('
        functions = re.findall(func_pattern, js_code)
        
        # Check if functions use only whitelisted operations
        safe_functions = []
        for func_name in functions:
            # Extract function body
            pattern = (
                rf'function\s+{re.escape(func_name)}\s*\([^)]*\)'
                r'\s*{{([^}}]+)}}'
            )
            func_body_match = re.search(pattern, js_code, re.DOTALL)
            if func_body_match:
                func_body = func_body_match.group(1)
                if self._check_function_safety(func_body):
                    safe_functions.append(func_name)
        
        # Determine recommended action
        if risk_score > 75:
            recommended_action = "REJECT"
        elif risk_score > 25:
            recommended_action = "SANITIZE"
        else:
            recommended_action = "ALLOW"
        
        return {
            "is_safe": risk_score == 0,
            "violations": violations,
            "safe_functions": safe_functions,
            "risk_score": min(risk_score, 100),
            "recommended_action": recommended_action
        }
    
    def _check_function_safety(self, func_body: str) -> bool:
        """
        Check if function body only uses whitelisted operations.
        
        Args:
            func_body: Function body source code
            
        Returns:
            True if function is safe, False otherwise
        """
        # Remove comments and strings to avoid false positives
        cleaned = re.sub(
            r'//.*?$|/\*.*?\*/', '', func_body,
            flags=re.MULTILINE | re.DOTALL
        )
        cleaned = re.sub(r'"[^"]*"|\'[^\']*\'|`[^`]*`', '', cleaned)
        
        # Check for any blacklisted patterns
        for pattern in self.BLACKLIST_PATTERNS:
            if re.search(pattern, cleaned, re.IGNORECASE):
                return False
        
        return True
    
    def sanitize_js(self, js_code: str) -> str:
        """
        Sanitize JavaScript by removing dangerous operations.
        Only keeps safe DOM manipulation and event handling.
        
        Args:
            js_code: JavaScript source code to sanitize
            
        Returns:
            Sanitized JavaScript code
        """
        analysis = self.analyze_script(js_code)
        
        if analysis["risk_score"] > 75:
            # Too dangerous - strip everything except safe functions
            safe_code = []
            for func_name in analysis["safe_functions"]:
                func_match = re.search(
                    rf'function\s+{re.escape(func_name)}\s*\([^)]*\)\s*{{[^}}]+}}',
                    js_code,
                    re.DOTALL
                )
                if func_match:
                    safe_code.append(func_match.group(0))
            
            if not safe_code:
                return '// [REMOVED: High-risk JavaScript code]'
            
            return '\n\n'.join(safe_code)
        
        elif analysis["risk_score"] > 0:
            # Medium risk - remove specific violations
            sanitized = js_code
            
            # Remove fetch calls
            sanitized = re.sub(
                r'fetch\s*\([^)]+\)[^;]*;?',
                '// [REMOVED: network call]',
                sanitized
            )
            
            # Remove XMLHttpRequest usage
            sanitized = re.sub(
                r'new\s+XMLHttpRequest\s*\([^)]*\)[^;]*;?',
                '// [REMOVED: XMLHttpRequest]',
                sanitized
            )
            
            # Remove cookie access
            sanitized = re.sub(
                r'document\.cookie[^;]*;?',
                '// [REMOVED: cookie access]',
                sanitized
            )
            
            # Remove storage access
            sanitized = re.sub(
                r'(?:local|session)Storage\.[^;]*;?',
                '// [REMOVED: storage access]',
                sanitized
            )
            
            # Remove eval/Function
            sanitized = re.sub(r'eval\s*\([^)]+\)', '/* REMOVED: eval */', sanitized)
            sanitized = re.sub(r'Function\s*\([^)]+\)', '/* REMOVED: Function */', sanitized)
            
            # Remove innerHTML assignments
            sanitized = re.sub(
                r'\.innerHTML\s*=\s*[^;]+;?',
                '.textContent = /* [SANITIZED] */;',
                sanitized
            )
            
            return sanitized
        
        return js_code
