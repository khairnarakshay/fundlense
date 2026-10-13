// Helper to read Django's CSRF token cookie
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

// frontend/static/js/secure_storage.js
const SECRET_KEY = "FundlenseAI_SecureKey_2026!";

const SecureStorage = {
    encrypt(text) {
        try {
            return btoa(encodeURIComponent(text + "___" + SECRET_KEY));
        } catch (e) {
            return text;
        }
    },
    decrypt(encoded) {
        try {
            let raw = decodeURIComponent(atob(encoded));
            if (raw.endsWith("___" + SECRET_KEY)) {
                return raw.replace("___" + SECRET_KEY, "");
            }
            return null;
        } catch (e) {
            return null;
        }
    },
    setItem(key, value) {
        const encrypted = this.encrypt(value);
        localStorage.setItem(key, encrypted);
        document.cookie = `${key}=${encrypted}; path=/; max-age=86400; SameSite=Lax`;
    },
    getItem(key) {
        const encrypted = localStorage.getItem(key);
        if (!encrypted) return null;
        return this.decrypt(encrypted);
    },
    removeItem(key) {
        localStorage.removeItem(key);
        document.cookie = `${key}=; path=/; max-age=0;`;
    }
};

// Global Auth Guard Function (Check before loading protected pages)
function checkAuthOrRedirect() {
    const token = SecureStorage.getItem("access_token");
    if (!token) {
        SecureStorage.removeItem("access_token");
        SecureStorage.removeItem("refresh_token");
        window.location.href = "/"; // Redirect to landing page / login
    }
}