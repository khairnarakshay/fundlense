/**
 * Helper to read Django's CSRF token cookie.
 * Angular does this automatically, but if you have vanilla JS elements, keep this.
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

/**
 * Checks if an API response indicates an expired token (HTTP 401).
 * If 401, it prompts the user and logs out.
 * @param {Response} res - The fetch API Response object.
 * @returns {boolean} True if token expired and logout occurred, false otherwise.
 */
window.handleTokenExpiry = function(res) {
    if (res.status === 401) {
        alert("Session expired. Please log in again.");
        window.logoutUser();
        return true;
    }
    return false;
};

/**
 * Helper to generate correct headers for API requests.
 * 🔑 Note: NO Authorization Bearer token needed anymore! The browser handles it via cookies.
 */
function getAuthHeaders() {
    return {
        'Content-Type': 'application/json',
        // Django checks this header against the cookie to verify it's a safe request
        'X-CSRFToken': getCookie('XSRF-TOKEN')
    };
}

/**
 * Global Auth Guard Function (Check before loading protected pages)
 * Uses a safe UI marker in sessionStorage instead of looking for raw tokens.
 */
function checkAuthOrRedirect() {
    // Look for the non-sensitive UI marker instead of a token string
    const isLoggedIn = sessionStorage.getItem("is_logged_in");

    if (!isLoggedIn) {
        console.warn("Auth Guard: No active session marker found. Redirecting to home.");
        sessionStorage.clear();
        window.location.href = "/";
    }
}






/**
 * Universal Secure Fetch API Wrapper
 * Handles credentials, headers, token validation checks, and JSON response parsing.
 *
 * @param {string} url - The target API endpoint URL.
 * @param {string} method - HTTP Verb (GET, POST, PUT, DELETE etc. Default is GET).
 * @param {object|null} bodyData - Optional request payload object.
 * @returns {Promise<any>} The parsed JSON data response from the server.
 */
async function secureFetch(url, method = 'GET', bodyData = null) {
    // 1. Build out the options profile dynamically
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('XSRF-TOKEN') // Attaches the CSRF safety token
        },
        credentials: 'include' // 🔑 CRITICAL: Automatically transmits HttpOnly cookies
    };

    if (bodyData && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase())) {
        options.body = JSON.stringify(bodyData);
    }

    try {
        // 2. Transmit the unified request to your server
        const res = await fetch(url, options);

        // 3. Centralized Token Expiration Guard Interrupt 🛡️
        if (res.status === 401) {
            alert("Session expired. Please log in again.");
            if (typeof window.logoutUser === 'function') {
                window.logoutUser();
            } else {
                sessionStorage.clear();
                window.location.href = "/";
            }
            return null;
        }

        // 4. Centralized Server Error Validation
        if (!res.ok) {
            throw new Error(`API error status received: ${res.status}`);
        }

        // 5. Natively extract and return the inner JSON data
        return await res.json();

    } catch (error) {
        console.error(`Secure fetch failure targeting ${url}:`, error);
        throw error; // Re-throw so individual UI services can handle custom layout visual warnings
    }
}
