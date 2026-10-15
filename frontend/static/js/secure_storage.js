
/**
 * Global Logout Handler: Cleans front-end state, notifies backend to drop cookies, and redirects.
 */
window.logoutUser = async function() {
    try {
        // 1. Tell the Django server to clear the HttpOnly cookies across the domain
        await fetch('https://fundlense.com', {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('XSRF-TOKEN') }
        });
    } catch (e) {
        console.error("Logout request to backend failed", e);
    } finally {
        // 2. Wipe clean the local non-sensitive session states
        sessionStorage.clear();

        // 3. Redirect to the home landing page
        window.location.href = "/";
    }
};

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

// Page Load Authentication Guard
document.addEventListener("DOMContentLoaded", function() {
    // Skip auth guard check if we are on the public home/landing page
    if (window.location.pathname === "/" || window.location.pathname === "/home/") {
        return;
    }

    // Initial check: Redirect if the login session marker is missing on protected pages
    checkAuthOrRedirect();
});



