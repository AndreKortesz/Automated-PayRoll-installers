/**
 * Security utilities for Mos-GSM Salary Service
 * XSS protection and CSRF token management
 */

const Security = {
    /**
     * Escape HTML special characters to prevent XSS
     * @param {string} text - Raw text that may contain HTML
     * @returns {string} - Safely escaped text
     */
    escapeHtml: function(text) {
        if (text === null || text === undefined) return '';
        if (typeof text !== 'string') text = String(text);
        
        const htmlEntities = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;',
            '/': '&#x2F;',
            '`': '&#x60;',
            '=': '&#x3D;'
        };
        
        return text.replace(/[&<>"'`=\/]/g, char => htmlEntities[char]);
    },

    /**
     * Escape text for use in HTML attributes
     * @param {string} text - Raw text
     * @returns {string} - Safely escaped text for attributes
     */
    escapeAttr: function(text) {
        if (text === null || text === undefined) return '';
        if (typeof text !== 'string') text = String(text);
        
        return text
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#x27;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    /**
     * Escape text for use in JavaScript strings
     * @param {string} text - Raw text
     * @returns {string} - Safely escaped text for JS
     */
    escapeJs: function(text) {
        if (text === null || text === undefined) return '';
        if (typeof text !== 'string') text = String(text);
        
        return text
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/"/g, '\\"')
            .replace(/\n/g, '\\n')
            .replace(/\r/g, '\\r')
            .replace(/\t/g, '\\t');
    },

    /**
     * Create a text node (inherently safe from XSS)
     * @param {string} text - Raw text
     * @returns {Text} - DOM Text node
     */
    createTextNode: function(text) {
        return document.createTextNode(text || '');
    },

    /**
     * Safely set text content of an element
     * @param {HTMLElement} element - Target element
     * @param {string} text - Raw text
     */
    setText: function(element, text) {
        if (element) {
            element.textContent = text || '';
        }
    },

    /**
     * CSRF Token Management
     */
    csrf: {
        tokenName: 'X-CSRF-Token',
        cookieName: 'csrf_token',
        
        /**
         * Get CSRF token from cookie
         * @returns {string|null} - CSRF token or null
         */
        getToken: function() {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                const [name, value] = cookie.trim().split('=');
                if (name === Security.csrf.cookieName) {
                    return decodeURIComponent(value);
                }
            }
            // Fallback: get from meta tag
            const meta = document.querySelector('meta[name="csrf-token"]');
            return meta ? meta.getAttribute('content') : null;
        },

        /**
         * Add CSRF token to headers object
         * @param {Object} headers - Headers object
         * @returns {Object} - Headers with CSRF token
         */
        addToHeaders: function(headers = {}) {
            const token = Security.csrf.getToken();
            if (token) {
                headers[Security.csrf.tokenName] = token;
            }
            return headers;
        },

        /**
         * Add CSRF token to FormData
         * @param {FormData} formData - FormData object
         * @returns {FormData} - FormData with CSRF token
         */
        addToFormData: function(formData) {
            const token = Security.csrf.getToken();
            if (token) {
                formData.append('csrf_token', token);
            }
            return formData;
        }
    },

    /**
     * Safe fetch wrapper with CSRF protection
     * @param {string} url - Request URL
     * @param {Object} options - Fetch options
     * @returns {Promise<Response>} - Fetch response
     */
    fetch: async function(url, options = {}) {
        // Add CSRF token for state-changing methods
        const method = (options.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            options.headers = Security.csrf.addToHeaders(options.headers || {});
        }
        
        return fetch(url, options);
    },

    /**
     * Safe JSON fetch with CSRF protection
     * @param {string} url - Request URL
     * @param {Object} data - Data to send
     * @param {string} method - HTTP method
     * @returns {Promise<Object>} - Parsed JSON response
     */
    fetchJson: async function(url, data = null, method = 'GET') {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                ...Security.csrf.addToHeaders({})
            }
        };
        
        if (data && method !== 'GET') {
            options.body = JSON.stringify(data);
        }
        
        const response = await fetch(url, options);
        return response.json();
    },

    /**
     * Validate that a string looks like a safe period ID
     * @param {string} id - ID to validate
     * @returns {boolean} - True if safe
     */
    isValidId: function(id) {
        if (!id) return false;
        // Only allow numbers
        return /^\d+$/.test(String(id));
    },

    /**
     * Validate URL is relative (not open redirect)
     * @param {string} url - URL to validate
     * @returns {boolean} - True if safe relative URL
     */
    isRelativeUrl: function(url) {
        if (!url) return false;
        // Must start with / and not //
        return /^\/[^\/]/.test(url) || url === '/';
    },

    /**
     * Safe redirect (prevents open redirect)
     * @param {string} url - URL to redirect to
     */
    safeRedirect: function(url) {
        if (Security.isRelativeUrl(url)) {
            window.location.href = url;
        } else if (Security.isValidId(url)) {
            // Assume it's a period ID
            window.location.href = '/period/' + url;
        } else {
            console.error('Blocked unsafe redirect to:', url);
            window.location.href = '/';
        }
    }
};

// Shorthand aliases for convenience
const escapeHtml = Security.escapeHtml;
const escapeAttr = Security.escapeAttr;
const escapeJs = Security.escapeJs;
const secureFetch = Security.fetch;
const fetchJson = Security.fetchJson;

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Security;
}
