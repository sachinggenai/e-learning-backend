"""Styles builder for SCORM player."""
from typing import Dict, Any
from .base import BaseBuilder


class StylesBuilder(BaseBuilder):
    """Builds styles.css for the SCORM player."""

    STYLES_TEMPLATE = '''* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: Arial, sans-serif;
    background: #f5f5f5;
}

#player-container {
    max-width: 900px;
    margin: 20px auto;
    background: white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    border-radius: 8px;
    overflow: hidden;
}

#header {
    background: #2c3e50;
    color: white;
    padding: 20px;
}

#course-title {
    font-size: 24px;
    margin-bottom: 10px;
}

#progress-bar {
    width: 100%;
    height: 8px;
    background: #34495e;
    border-radius: 4px;
    overflow: hidden;
}

#progress-fill {
    height: 100%;
    background: #3498db;
    width: 0%;
    transition: width 0.3s ease;
}

#slide-container {
    padding: 40px;
    min-height: 400px;
}

#navigation {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px;
    background: #ecf0f1;
    border-top: 1px solid #bdc3c7;
}

button {
    padding: 10px 20px;
    background: #3498db;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
}

button:hover:not(:disabled) {
    background: #2980b9;
}

button:disabled {
    background: #95a5a6;
    cursor: not-allowed;
}

#slide-counter {
    font-weight: bold;
    color: #2c3e50;
}

.template-mcq .question {
    margin: 30px 0;
    padding: 20px;
    background: #f8f9fa;
    border-radius: 4px;
}

.template-mcq .question h3 {
    margin-bottom: 15px;
    color: #2c3e50;
}

.template-mcq .options {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.template-mcq .option {
    display: flex;
    align-items: center;
    padding: 12px;
    background: white;
    border: 2px solid #ddd;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
}

.template-mcq .option:hover {
    border-color: #3498db;
    background: #ecf0f1;
}

.template-mcq .option input {
    margin-right: 10px;
}

#submit-mcq {
    margin-top: 20px;
    background: #27ae60;
}

#submit-mcq:hover {
    background: #229954;
}

.template-video video {
    width: 100%;
    max-width: 640px;
    margin: 20px 0;
}

.template-welcome, .template-text {
    line-height: 1.6;
}

.error {
    padding: 20px;
    background: #e74c3c;
    color: white;
    border-radius: 4px;
}
'''

    async def build(self, context: Dict[str, Any]) -> str:
        """Build the styles CSS."""
        return self.STYLES_TEMPLATE
