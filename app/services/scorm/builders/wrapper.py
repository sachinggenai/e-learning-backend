"""SCORM API wrapper builder."""
from typing import Dict, Any
from .base import BaseBuilder


class WrapperBuilder(BaseBuilder):
    """Builds scorm_wrapper.js for LMS communication."""

    WRAPPER_TEMPLATE = '''// SCORM 1.2 API Wrapper
// Handles communication with LMS

class SCORMWrapper {
    constructor() {
        this.apiHandle = null;
        this.findAttempts = 0;
        this.maxFindAttempts = 500;
    }

    findAPI(win) {
        while (win.API == null && win.parent != null && 
               win.parent != win && this.findAttempts <= this.maxFindAttempts) {
            this.findAttempts++;
            win = win.parent;
        }
        return win.API;
    }

    getAPI() {
        if (this.apiHandle == null) {
            this.apiHandle = this.findAPI(window);
        }
        return this.apiHandle;
    }

    initialize() {
        const API = this.getAPI();
        if (API) {
            const result = API.LMSInitialize("");
            return result === "true";
        }
        return false;
    }

    terminate() {
        const API = this.getAPI();
        if (API) {
            const result = API.LMSFinish("");
            return result === "true";
        }
        return false;
    }

    getValue(element) {
        const API = this.getAPI();
        if (API) {
            return API.LMSGetValue(element);
        }
        return "";
    }

    setValue(element, value) {
        const API = this.getAPI();
        if (API) {
            const result = API.LMSSetValue(element, value);
            return result === "true";
        }
        return false;
    }

    commit() {
        const API = this.getAPI();
        if (API) {
            const result = API.LMSCommit("");
            return result === "true";
        }
        return false;
    }

    getLastError() {
        const API = this.getAPI();
        if (API) {
            return API.LMSGetLastError();
        }
        return "";
    }
}

// Create global instance
const scormWrapper = new SCORMWrapper();
window.scormWrapper = scormWrapper;
'''

    async def build(self, context: Dict[str, Any]) -> str:
        """Build the SCORM wrapper JavaScript."""
        return self.WRAPPER_TEMPLATE
