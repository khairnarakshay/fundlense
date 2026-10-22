
/**
 * Global Logout Handler: Cleans front-end state, notifies backend to drop cookies, and redirects.
 */
window.logoutUser = async function() {
    try {
        // 1. Tell Django to delete the HttpOnly cookies across the shared domain network
        // Note: secureFetch automatically appends the correct credentials and CSRF safety tokens!
        await secureFetch('/accounts/v1/auth/logout/', 'POST');
    } catch (e) {
        console.error("Backend cookie cleanup failed:", e);
    } finally {
        // 2. Wipe clear any safe frontend UI state variables (like username)
        sessionStorage.clear();

        // 3. Send the guest back to the root landing screen
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



