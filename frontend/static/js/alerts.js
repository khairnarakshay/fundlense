// static/js/alerts.js
(function () {
    // --- style map ---
    const STYLES = {
        error:   'bg-rose-500/20 text-rose-200 border-rose-500/40',
        success: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/40',
        info:    'bg-cyan-500/20 text-cyan-200 border-cyan-500/40',
        warning: 'bg-amber-500/20 text-amber-200 border-amber-500/40',
    };

    // --- ensure the floating container exists ---
    function ensureToastContainer() {
        let container = document.getElementById('globalAlertContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'globalAlertContainer';
            container.className = 'fixed top-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm';
            document.body.appendChild(container);
        }
        return container;
    }

    /**
     * Global alert helper.
     * @param {string} message
     * @param {boolean|string} isError - true/false OR 'error'|'success'|'info'|'warning'
     * @param {string|null} targetId - optional element ID for inline rendering (e.g. 'authAlertBox')
     */
    function showAlert(message, isError = true, targetId = null) {
        // Normalize the type
        let type = 'error';
        if (typeof isError === 'boolean') {
            type = isError ? 'error' : 'success';
        } else if (typeof isError === 'string' && STYLES[isError]) {
            type = isError;
        }
        const styleClass = STYLES[type];

        // ---------- INLINE MODE (for auth modal etc.) ----------
        if (targetId) {
            const box = document.getElementById(targetId);
            if (box) {
                box.textContent = message;
                box.className = `mb-4 p-3 rounded-xl text-xs font-semibold border ${styleClass}`;
                return;
            }
        }

        // ---------- FLOATING TOAST MODE ----------
        const container = ensureToastContainer();
        const toast = document.createElement('div');
        toast.className = `px-4 py-3 rounded-xl border text-sm font-semibold shadow-lg backdrop-blur-md ${styleClass}`;
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-8px)';
        toast.style.transition = 'opacity .2s ease, transform .2s ease';
        toast.textContent = message;
        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        // Auto-dismiss
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-8px)';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // Expose globally
    window.showAlert = showAlert;
    window.showToast = showAlert; // alias, if you prefer
    window.hideAlert = function (targetId = null) {
        if (targetId) {
            const box = document.getElementById(targetId);
            if (box) box.className = 'hidden';
            return;
        }
        const container = document.getElementById('globalAlertContainer');
        if (container) container.innerHTML = '';
    };
})();