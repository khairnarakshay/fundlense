// static/js/loader.js
(function () {
    function ensureLoaderContainer() {
        let overlay = document.getElementById('globalLoaderOverlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'globalLoaderOverlay';
            overlay.className = 'fixed inset-0 z-[10000] flex items-center justify-center bg-slate-950/80 backdrop-blur-md hidden';
            overlay.innerHTML = `
                <div class="glass-panel p-6 rounded-3xl border border-cyan-500/30 shadow-2xl flex flex-col items-center max-w-xs mx-4 text-center bg-slate-900/90">
                    <div class="relative w-14 h-14 mb-3">
                        <div class="absolute inset-0 rounded-full border-4 border-cyan-500/20"></div>
                        <div class="absolute inset-0 rounded-full border-4 border-cyan-400 border-t-transparent animate-spin"></div>
                    </div>
                    <p id="globalLoaderText" class="text-sm font-bold text-white tracking-wide">Processing...</p>
                </div>
            `;
            document.body.appendChild(overlay);
        }
        return overlay;
    }

    window.showLoader = function (message = 'Processing...') {
        const overlay = ensureLoaderContainer();
        const textEl = document.getElementById('globalLoaderText');
        if (textEl) textEl.textContent = message;
        overlay.classList.remove('hidden');
    };

    window.hideLoader = function () {
        const overlay = document.getElementById('globalLoaderOverlay');
        if (overlay) {
            overlay.classList.add('hidden');
        }
    };

    window.setButtonLoading = function (buttonEl, isLoading, loadingText = 'Please wait...') {
        if (!buttonEl) return;
        if (isLoading) {
            buttonEl.dataset.originalHtml = buttonEl.innerHTML;
            buttonEl.disabled = true;
            buttonEl.innerHTML = `
                <span class="inline-flex items-center justify-center gap-2">
                    <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    ${loadingText}
                </span>
            `;
            buttonEl.classList.add('opacity-75', 'cursor-not-allowed');
        } else {
            buttonEl.disabled = false;
            buttonEl.innerHTML = buttonEl.dataset.originalHtml || 'Submit';
            buttonEl.classList.remove('opacity-75', 'cursor-not-allowed');
        }
    };
})();