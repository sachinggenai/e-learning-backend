"""Player HTML builder."""
from typing import Dict, Any
from jinja2 import Template
from .base import BaseBuilder


class PlayerBuilder(BaseBuilder):
    """Builds index.html containing the SCORM player."""

    PLAYER_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="player-container">
        <div id="header">
            <h1 id="course-title">{{ title }}</h1>
            <div id="progress-bar">
                <div id="progress-fill"></div>
            </div>
        </div>
        
        <div id="slide-container">
            <div id="slide-content"></div>
        </div>
        
        <div id="navigation">
            <button id="prev-btn">Previous</button>
            <span id="slide-counter"></span>
            <button id="next-btn">Next</button>
        </div>
    </div>

    <script defer src="scorm_wrapper.js"></script>
    <script defer src="course_data.js"></script>
    <script defer>
        // Player logic
        class Player {
            constructor() {
                this.currentSlide = 0;
                this.courseData = null;
                this.completedSlides = new Set();
            }

            async waitForCourseData(timeout = 5000) {
                const start = Date.now();
                while (!window.courseData && Date.now() - start < timeout) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                if (!window.courseData) {
                    throw new Error('Course data failed to load');
                }
                this.courseData = window.courseData;
            }

            async init() {
                await this.waitForCourseData();
                
                // Initialize SCORM
                if (window.scormWrapper) {
                    window.scormWrapper.initialize();
                    window.scormWrapper.setValue('cmi.core.lesson_status', 'incomplete');
                    window.scormWrapper.commit();
                }

                this.loadSlide(0);
                this.setupEventListeners();
            }

            loadSlide(index) {
                if (!this.courseData || !this.courseData.templates[index]) {
                    return;
                }

                this.currentSlide = index;
                const template = this.courseData.templates[index];
                const content = document.getElementById('slide-content');

                // Render based on template type
                switch(template.type) {
                    case 'welcome':
                    case 'summary':
                        content.innerHTML = `
                            <div class="template-welcome">
                                <h2>${template.title}</h2>
                                <p>${template.data.content}</p>
                            </div>
                        `;
                        break;

                    case 'content-text':
                        content.innerHTML = `
                            <div class="template-text">
                                <h2>${template.title}</h2>
                                <div class="content">${template.data.content}</div>
                            </div>
                        `;
                        break;

                    case 'content-video':
                        content.innerHTML = `
                            <div class="template-video">
                                <h2>${template.title}</h2>
                                <video controls src="${template.data.videoUrl}"></video>
                                <p>${template.data.content}</p>
                            </div>
                        `;
                        break;

                    case 'mcq':
                        this.renderMCQ(template);
                        break;

                    default:
                        content.innerHTML = `
                            <div class="template-unknown">
                                <h2>${template.title}</h2>
                                <p>Unknown template type: ${template.type}</p>
                            </div>
                        `;
                }

                this.updateNavigation();
                this.updateProgress();
                this.trackSlideView(index);
            }

            renderMCQ(template) {
                const content = document.getElementById('slide-content');
                const questions = template.data.questions || [];

                let html = `<div class="template-mcq">
                    <h2>${template.title}</h2>
                    <p>${template.data.content}</p>`;

                questions.forEach((q, qIndex) => {
                    html += `<div class="question" data-question-index="${qIndex}">
                        <h3>${q.question}</h3>
                        <div class="options">`;

                    q.options.forEach((opt, optIndex) => {
                        html += `<label class="option">
                            <input type="radio" 
                                   name="question_${qIndex}" 
                                   value="${optIndex}"
                                   data-correct="${opt.isCorrect}">
                            <span>${opt.text}</span>
                        </label>`;
                    });

                    html += `</div></div>`;
                });

                html += `<button id="submit-mcq">Submit Answers</button></div>`;
                content.innerHTML = html;

                // Attach submit handler
                document.getElementById('submit-mcq').addEventListener('click', () => {
                    this.checkMCQAnswers(template, questions);
                });
            }

            checkMCQAnswers(template, questions) {
                let allCorrect = true;

                questions.forEach((q, qIndex) => {
                    const selected = document.querySelector(
                        `input[name="question_${qIndex}"]:checked`
                    );
                    
                    if (!selected || selected.dataset.correct !== 'true') {
                        allCorrect = false;
                    }
                });

                if (allCorrect) {
                    this.markSlideComplete(this.currentSlide);
                    alert('Correct! Well done.');
                } else {
                    alert('Some answers are incorrect. Please try again.');
                }
            }

            markSlideComplete(index) {
                this.completedSlides.add(index);
                
                // Update SCORM
                if (window.scormWrapper) {
                    const objId = `obj_${index}`;
                    window.scormWrapper.setValue(
                        `cmi.objectives.${index}.id`, objId
                    );
                    window.scormWrapper.setValue(
                        `cmi.objectives.${index}.status`, 'completed'
                    );
                    window.scormWrapper.commit();
                }

                // Check if course complete
                if (this.completedSlides.size === this.courseData.templates.length) {
                    this.markCourseComplete();
                }
            }

            markCourseComplete() {
                if (window.scormWrapper) {
                    window.scormWrapper.setValue('cmi.core.lesson_status', 'completed');
                    window.scormWrapper.setValue('cmi.core.score.raw', '100');
                    window.scormWrapper.commit();
                }
            }

            trackSlideView(index) {
                if (window.scormWrapper) {
                    window.scormWrapper.setValue('cmi.core.lesson_location', String(index));
                    window.scormWrapper.commit();
                }
            }

            setupEventListeners() {
                document.getElementById('prev-btn').addEventListener('click', () => {
                    if (this.currentSlide > 0) {
                        this.loadSlide(this.currentSlide - 1);
                    }
                });

                document.getElementById('next-btn').addEventListener('click', () => {
                    if (this.currentSlide < this.courseData.templates.length - 1) {
                        this.loadSlide(this.currentSlide + 1);
                    }
                });

                window.addEventListener('beforeunload', () => {
                    if (window.scormWrapper) {
                        window.scormWrapper.terminate();
                    }
                });
            }

            updateNavigation() {
                const prevBtn = document.getElementById('prev-btn');
                const nextBtn = document.getElementById('next-btn');
                const counter = document.getElementById('slide-counter');

                prevBtn.disabled = this.currentSlide === 0;
                nextBtn.disabled = this.currentSlide >= this.courseData.templates.length - 1;
                counter.textContent = `${this.currentSlide + 1} / ${this.courseData.templates.length}`;
            }

            updateProgress() {
                const progress = ((this.currentSlide + 1) / this.courseData.templates.length) * 100;
                document.getElementById('progress-fill').style.width = progress + '%';
            }
        }

        // Initialize player when DOM is ready
        document.addEventListener('DOMContentLoaded', async () => {
            const player = new Player();
            try {
                await player.init();
            } catch (error) {
                console.error('Failed to initialize player:', error);
                document.getElementById('slide-content').innerHTML = 
                    '<div class="error">Failed to load course. Please refresh.</div>';
            }
        });
    </script>
</body>
</html>'''

    async def build(self, context: Dict[str, Any]) -> str:
        """Build the player HTML."""
        template = Template(self.PLAYER_TEMPLATE)
        return template.render(**context)
