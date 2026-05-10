// SCORM 1.2 API WRAPPER - Production with Mock API Fallback
var SCORM = {
    version: "1.2",
    initialized: false,
    sessionData: {
        answers: {}, 
        visitedSlides: [], // Track visited slides locally
        startTime: null
    },

    initialize: function() {
        if (this.initialized) return true; // Prevent double initialization
        
        try {
            var API = this.getAPI();
            if (!API) {
                console.log('No LMS API found, using Mock API for testing');
                this.mockMode = true;
                this.mockStorage = this.getMockStorage();
                this.sessionData.startTime = new Date();
                this.initialized = true;
                console.log('✓ Mock SCORM initialized');
                return true;
            }

            var r = API.LMSInitialize("");
            if (r !== "true") return false;
            
            // CRITICAL FIX: Only set to 'incomplete' if no status exists yet
            var currentStatus = API.LMSGetValue("cmi.core.lesson_status");
            if (!currentStatus || currentStatus === "" || currentStatus === "not attempted") {
                API.LMSSetValue("cmi.core.lesson_status", "incomplete");
                console.log('✓ SCORM initialized - status set to incomplete');
            } else {
                console.log('✓ SCORM initialized - preserving existing status:', currentStatus);
            }

            // RESTORE SESSION DATA (Quiz Answers & Visited Slides) from suspend_data
            var suspendData = API.LMSGetValue("cmi.suspend_data");
            if (suspendData && suspendData !== "") {
                try {
                    var parsed = JSON.parse(suspendData);
                    if (parsed) {
                        if (parsed.answers) this.sessionData.answers = parsed.answers;
                        if (parsed.visitedSlides) this.sessionData.visitedSlides = parsed.visitedSlides;
                        console.log('✓ Restored session data. Visited:', this.sessionData.visitedSlides.length);
                    }
                } catch (e) {
                    console.warn('Failed to parse suspend_data:', e);
                }
            }
            
            this.sessionData.startTime = new Date();
            this.initialized = true;
            return true;
        } catch (e) {
            console.error('SCORM init:', e);
            return false;
        }
    },

    getAPI: function() {
        var win = window;
        var maxRetries = 10;
        var retryDelay = 100;  // 100ms delay between retries
        
        for (var attempt = 0; attempt < maxRetries; attempt++) {
            // Check current window
            if (win.API != null) return win.API;
            
            // Check parent windows
            while (win.API == null && win.parent != win) {
                win = win.parent;
                if (win.API != null) return win.API;
            }
            
            // Check opener window
            if (win.API == null && win.opener) {
                win = win.opener;
                if (win.API != null) return win.API;
            }
            
            // Wait before retrying
            if (attempt < maxRetries - 1) {
                var start = Date.now();
                while (Date.now() - start < retryDelay) {
                    // Busy wait for delay
                }
            }
        }
        
        return null;
    },

    getMockStorage: function() {
        try {
            var stored = localStorage.getItem('scorm_mock_data');
            return stored ? JSON.parse(stored) : {
                'cmi.core.lesson_status': 'incomplete',
                'cmi.core.score.raw': '0',
                'cmi.core.score.max': '100',
                'cmi.core.lesson_location': '0'
            };
        } catch (e) {
            console.warn('localStorage not available, using memory storage');
            return {
                'cmi.core.lesson_status': 'incomplete',
                'cmi.core.score.raw': '0',
                'cmi.core.score.max': '100',
                'cmi.core.lesson_location': '0'
            };
        }
    },

    saveMockData: function() {
        if (this.mockStorage && typeof localStorage !== 'undefined') {
            try {
                localStorage.setItem('scorm_mock_data', JSON.stringify(this.mockStorage));
            } catch (e) {
                console.warn('Failed to save mock data:', e);
            }
        }
    },

    setValue: function(p, v) {
        try {
            console.log('SCORM setValue:', p, '=', v);
            if (this.mockMode) {
                if (this.mockStorage) {
                    this.mockStorage[p] = v;
                    this.saveMockData();
                }
                console.log('Mock setValue success');
                return true;
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM setValue failed: API not found');
                return false;
            }
            var result = API.LMSSetValue(p, v);
            console.log('SCORM LMSSetValue result:', result);
            if (result !== "true") {
                var err = API.LMSGetLastError();
                var errString = API.LMSGetErrorString(err);
                var diagnostic = API.LMSGetDiagnostic(err);
                console.error('SCORM setValue error:', err, errString, diagnostic);
            }
            return result === "true";
        } catch (e) {
            console.error('setValue exception:', e);
            return false;
        }
    },

    getValue: function(p) {
        try {
            console.log('SCORM getValue:', p);
            if (this.mockMode) {
                var value = this.mockStorage ? this.mockStorage[p] : "";
                console.log('Mock getValue result:', value);
                return value || "";
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM getValue failed: API not found');
                return "";
            }
            var value = API.LMSGetValue(p);
            console.log('SCORM LMSGetValue result:', value);
            var err = API.LMSGetLastError();
            if (err !== "0") {
                 var errString = API.LMSGetErrorString(err);
                 console.error('SCORM getValue error:', err, errString);
            }
            return value || "";
        } catch (e) {
            console.error('getValue exception:', e);
            return "";
        }
    },

    commit: function() {
        try {
            console.log('SCORM commit called');
            if (this.mockMode) {
                this.saveMockData();
                console.log('Mock commit success');
                return true;
            }

            var API = this.getAPI();
            if (!API) {
                console.error('SCORM commit failed: API not found');
                return false;
            }
            var result = API.LMSCommit("");
            console.log('SCORM LMSCommit result:', result);
            if (result !== "true") {
                var err = API.LMSGetLastError();
                console.error('SCORM commit error:', err, API.LMSGetErrorString(err));
            }
            return result === "true";
        } catch (e) {
            console.error('commit exception:', e);
            return false;
        }
    },

    recordAnswer: function(qId, selIdx, correct) {
        this.sessionData.answers[qId] = {selected: selIdx, correct: correct};
        if (this.initialized) {
            this.setValue('cmi.interactions.0.id', qId);
            this.setValue('cmi.interactions.0.type', 'choice');
            this.setValue('cmi.interactions.0.student_response', selIdx);
            this.commit();
        }
    },

    // FIX: Add missing SCORM methods for LMS compatibility
    markSlideComplete: function(slideIdx, totalSlides) {
        if (this.initialized) {
            // 1. Update Local State
            if (this.sessionData.visitedSlides.indexOf(slideIdx) === -1) {
                this.sessionData.visitedSlides.push(slideIdx);
                this.saveSessionData(); // Persist immediately
                console.log('Marked slide', slideIdx, 'visited. Total visited:', this.sessionData.visitedSlides.length);
            }

            // 2. Try to update LMS Objectives (Best Effort)
            // We do this for LMSs that support it, but we don't rely on it for logic
            var objId = 'obj_' + slideIdx;
            this.setValue('cmi.objectives.' + slideIdx + '.id', objId);
            this.setValue('cmi.objectives.' + slideIdx + '.status', 'completed');
            this.setValue('cmi.objectives.' + slideIdx + '.score.raw', '100');
            this.setValue('cmi.objectives.' + slideIdx + '.score.max', '100');
            
            // 3. Check Completion based on LOCAL state
            if (totalSlides) {
                this.checkCourseCompletion(totalSlides);
            }
            
            this.commit();
        }
    },

    checkCourseCompletion: function(totalSlides) {
        if (!this.initialized) return;
        
        console.log('Checking completion. Visited:', this.sessionData.visitedSlides.length, '/', totalSlides);
        
        // ROBUST CHECK: Use local visitedSlides count
        if (this.sessionData.visitedSlides.length >= totalSlides) {
            console.log('All slides visited (local check) - marking course complete');
            this.setCourseComplete();
        } else {
            console.log('Course not yet complete. Missing slides.');
        }
    },

    recordQuizAnswer: function(qId, selIdx, correct, options) {
        if (this.initialized) {
            // Get next interaction index (track in session)
            if (!this.sessionData.interactionCount) {
                this.sessionData.interactionCount = 0;
            }
            var interactionIdx = this.sessionData.interactionCount++;
            
            // Record interaction details with correct index
            var prefix = 'cmi.interactions.' + interactionIdx;
            this.setValue(prefix + '.id', qId);
            this.setValue(prefix + '.type', 'choice');
            this.setValue(prefix + '.student_response', selIdx.toString());
            this.setValue(prefix + '.result', correct ? 'correct' : 'wrong');
            this.setValue(prefix + '.weighting', '1');
            // REMOVED: latency is NOT required in SCORM 1.2, causes errors
            
            // Set correct responses - use index 0 for correct answer pattern
            if (options && options.length > 0) {
                for (var i = 0; i < options.length; i++) {
                    if (options[i] && options[i].isCorrect) {
                        // Use .0. not .3. for the first correct response
                        this.setValue(prefix + '.correct_responses.0.pattern', i.toString());
                        break; // Only need first correct answer
                    }
                }
            }
            
            this.commit();
            
            // Also store in sessionData for score calculation
            this.sessionData.answers[qId] = {selected: selIdx, correct: correct};
            this.saveSessionData(); // Persist to suspend_data
            
            console.log('Recorded quiz answer:', qId, 'idx:', interactionIdx, 'selected:', selIdx, 'correct:', correct);
            
            // Update score immediately
            this.submitScore();
        }
    },

    calculateScore: function() {
        var correct = 0, total = 0;
        
        // Count quiz answers from sessionData (recorded during quiz interactions)
        for (var qId in this.sessionData.answers) {
            total++;
            if (this.sessionData.answers[qId].correct) correct++;
        }
        
        // If no answers in sessionData, try to get from SCORM API
        if (total === 0 && this.initialized) {
            // Try to get quiz results from SCORM interactions
            // SCORM 1.2 doesn't have a direct way to query all interactions,
            // so we'll rely on the sessionData that's populated during quiz interactions
            console.log('No quiz answers found in sessionData for scoring');
        }
        
        var score = total === 0 ? 0 : Math.round((correct / total) * 100);
        console.log('Score calculation: correct=' + correct + ', total=' + total + ', score=' + score + '%');
        return score;
    },

    submitScore: function() {
        var score = this.calculateScore();
        if (this.initialized) {
            this.setValue('cmi.core.score.raw', score);
            this.setValue('cmi.core.score.min', '0');
            this.setValue('cmi.core.score.max', '100');
            this.commit();
            console.log('Score submitted:', score);
        }
        return score;
    },

    saveProgress: function(slideIdx) {
        if (this.initialized) {
            this.setValue('cmi.core.lesson_location', slideIdx);
            this.commit();
        }
    },

    restoreProgress: function(totalSlides) {
        if (!this.initialized) return 0;
        
        var saved = this.getValue('cmi.core.lesson_location');
        var slideIndex = saved && !isNaN(saved) ? parseInt(saved) : 0;
        
        console.log('Restoring progress: saved slide index =', slideIndex, 'total slides =', totalSlides);
        
        // Mark all slides up to the saved position as completed
        // This ensures that on revisit, previously viewed slides show as completed
        if (totalSlides && totalSlides > 0) {
            for (var i = 0; i <= slideIndex && i < totalSlides; i++) {
                this.markSlideComplete(i, totalSlides);
                console.log('Marked previously viewed slide', i, 'as completed');
            }
        }
        
        return slideIndex;
    },

    setCourseComplete: function() {
        console.log('setCourseComplete called');
        if (this.initialized) {
            this.submitScore();
            // Mark all objectives as completed before setting course complete
            // Only update objectives that actually exist (have IDs)
            for (var i = 0; i < 10; i++) {
                var objId = this.getValue('cmi.objectives.' + i + '.id');
                if (objId && objId !== '') {
                    console.log('Forcing completion for objective', i, 'id:', objId);
                    this.setValue('cmi.objectives.' + i + '.status', 'completed');
                    this.setValue('cmi.objectives.' + i + '.score.raw', '100');
                    this.setValue('cmi.objectives.' + i + '.score.max', '100');
                    // REMOVED: score.scaled is NOT valid in SCORM 1.2
                } else {
                    break; // No more objectives
                }
            }
            console.log('Setting cmi.core.lesson_status to completed');
            this.setValue('cmi.core.lesson_status', 'completed');
            this.setValue('cmi.core.score.min', '0'); // Ensure min score is set
            var commitResult = this.commit();
            console.log('setCourseComplete commit result:', commitResult);
        } else {
            console.warn('setCourseComplete called but SCORM not initialized');
        }
    },

    // Helper to format time as HHHH:MM:SS.SS for SCORM 1.2
    formatTime: function(ms) {
        var h = Math.floor(ms / 3600000);
        var m = Math.floor((ms % 3600000) / 60000);
        var s = Math.floor(((ms % 3600000) % 60000) / 1000);
        var cs = Math.floor((((ms % 3600000) % 60000) % 1000) / 10);
        
        if (h < 10) h = "0" + h;
        if (m < 10) m = "0" + m;
        if (s < 10) s = "0" + s;
        if (cs < 10) cs = "0" + cs;
        
        return h + ":" + m + ":" + s + "." + cs;
    },

    terminate: function() {
        try {
            // SCORM 1.2 Requirement: Set session time and exit status before finishing
            if (this.initialized && this.sessionData.startTime) {
                var endTime = new Date();
                var totalTime = endTime - this.sessionData.startTime;
                this.setValue("cmi.core.session_time", this.formatTime(totalTime));
                
                // Set exit to 'suspend' to ensure lesson_location (bookmarking) is preserved
                this.setValue("cmi.core.exit", "suspend");
            }

            if (this.mockMode) {
                this.saveMockData();
                console.log('Mock SCORM terminated');
            } else {
                var API = this.getAPI();
                if (API) API.LMSFinish("");
            }
            this.initialized = false;
        } catch (e) {
            console.error('terminate error:', e);
        }
    },

    // Enhanced debugging methods
    getDebugInfo: function() {
        return {
            initialized: this.initialized,
            mockMode: this.mockMode,
            sessionData: this.sessionData,
            mockStorage: this.mockStorage,
            apiAvailable: !!this.getAPI()
        };
    },

    // DEBUG: Check current objective status
    getObjectiveStatus: function(slideIdx) {
        if (!this.initialized) return 'not_initialized';
        
        var objId = 'obj_' + slideIdx;
        var status = this.getValue('cmi.objectives.' + slideIdx + '.status');
        var id = this.getValue('cmi.objectives.' + slideIdx + '.id');
        
        console.log('DEBUG: Objective', slideIdx, '- ID:', id, 'Status:', status);
        return {id: id, status: status, expectedId: objId};
    },

    // DEBUG: Check all objectives status
    getAllObjectivesStatus: function(totalSlides) {
        if (!this.initialized) return [];
        
        var objectives = [];
        for (var i = 0; i < totalSlides; i++) {
            objectives.push(this.getObjectiveStatus(i));
        }
        return objectives;
    },

    // DEBUG: Force refresh of objective data (for testing)
    refreshObjectives: function(totalSlides) {
        if (!this.initialized) return false;
        
        console.log('DEBUG: Refreshing objectives for', totalSlides, 'slides');
        for (var i = 0; i < totalSlides; i++) {
            var objId = 'obj_' + i;
            var currentId = this.getValue('cmi.objectives.' + i + '.id');
            var currentStatus = this.getValue('cmi.objectives.' + i + '.status');
            
            console.log('DEBUG: Slide', i, '- Current ID:', currentId, 'Expected ID:', objId, 'Status:', currentStatus);
            
            // Re-set the objective data if needed
            if (currentId !== objId) {
                console.log('DEBUG: Re-setting objective ID for slide', i);
                this.setValue('cmi.objectives.' + i + '.id', objId);
            }
            
            // Ensure status is set
            if (currentStatus !== 'completed') {
                console.log('DEBUG: Re-setting objective status for slide', i, 'to completed');
                this.setValue('cmi.objectives.' + i + '.status', 'completed');
                this.setValue('cmi.objectives.' + i + '.score.raw', '100');
                this.setValue('cmi.objectives.' + i + '.score.max', '100');
            }
        }
        
        this.commit();
        console.log('DEBUG: Objectives refreshed and committed');
        return true;
    },

    // Helper to persist session data
    saveSessionData: function() {
        if (this.initialized) {
            try {
                var dataStr = JSON.stringify({
                    answers: this.sessionData.answers,
                    visitedSlides: this.sessionData.visitedSlides
                });
                this.setValue("cmi.suspend_data", dataStr);
            } catch (e) {
                console.error('Failed to save session data:', e);
            }
        }
    },
};
window.addEventListener('load', () => SCORM.initialize());
window.addEventListener('unload', () => SCORM.terminate());
console.log('✓ SCORM wrapper with Mock API loaded');
