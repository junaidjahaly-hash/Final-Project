/* Appearance preferences are saved in this browser. */
function renderWelcome() {
    const template = document.getElementById('welcomeTemplate');
    const container = document.getElementById('chatMessages');
    if (template && container) {
        container.replaceChildren(template.content.cloneNode(true));
        container.scrollTop = 0;
    }
}

(() => {
    const storageKey = 'workspaceAppearance';
    const themes = ['skyline', 'aurora', 'midnight'];
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const mobileLayout = window.matchMedia('(max-width: 760px)');
    let preferences = { wallpaper: 'skyline', motion: true };
    try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
        if (themes.includes(saved.wallpaper)) preferences.wallpaper = saved.wallpaper;
        if (typeof saved.motion === 'boolean') preferences.motion = saved.motion;
    } catch { /* Use defaults if saved preferences are unavailable. */ }

    const panel = document.getElementById('appearancePanel');
    const triggers = document.querySelectorAll('[data-appearance-open]');
    const motionToggle = document.getElementById('motionToggle');
    let lastTrigger = null;

    function applyPreferences() {
        document.body.dataset.wallpaper = preferences.wallpaper;
        const motion = preferences.motion && !reducedMotion.matches;
        document.body.dataset.motion = motion ? 'on' : 'off';
        motionToggle.checked = motion;
        motionToggle.disabled = reducedMotion.matches;
        document.getElementById('motionHint').textContent = reducedMotion.matches
            ? 'Reduced motion is enabled in your device settings'
            : 'Moving sky light, flowing ribbons and gliding trails';
        panel.querySelectorAll('[data-wallpaper]').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.wallpaper === preferences.wallpaper));
        });
        document.querySelector('.wallpaper-caption').textContent =
            `${preferences.wallpaper.toUpperCase()} COLLECTION / 0${themes.indexOf(preferences.wallpaper) + 1}`;
    }

    function savePreferences() {
        try { localStorage.setItem(storageKey, JSON.stringify(preferences)); } catch { /* Keep the preference for this session. */ }
    }

    function closeAppearance(restoreFocus = false) {
        panel.hidden = true;
        triggers.forEach(button => button.setAttribute('aria-expanded', 'false'));
        if (restoreFocus) lastTrigger?.focus();
    }

    triggers.forEach(button => button.addEventListener('click', () => {
        if (!panel.hidden) { closeAppearance(true); return; }
        lastTrigger = button;
        panel.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        panel.querySelector('[aria-pressed="true"]').focus();
    }));
    document.getElementById('appearanceClose').addEventListener('click', () => closeAppearance(true));
    panel.querySelectorAll('[data-wallpaper]').forEach(button => button.addEventListener('click', () => {
        preferences.wallpaper = button.dataset.wallpaper;
        applyPreferences();
        savePreferences();
    }));
    motionToggle.addEventListener('change', () => {
        preferences.motion = motionToggle.checked;
        applyPreferences();
        savePreferences();
    });
    document.addEventListener('click', event => {
        if (!panel.hidden && !panel.contains(event.target) && !event.target.closest('[data-appearance-open]')) closeAppearance();
    });
    document.addEventListener('focusin', event => {
        if (!panel.hidden && !panel.contains(event.target) && !event.target.closest('[data-appearance-open]')) closeAppearance();
    });
    reducedMotion.addEventListener('change', applyPreferences);
    const updateVisibility = () => { document.body.dataset.pageHidden = String(document.hidden); };
    document.addEventListener('visibilitychange', updateVisibility);

    const sidebarButton = document.getElementById('sidebarToggle');
    const scrim = document.getElementById('sidebarScrim');
    const sidebar = document.getElementById('workspaceSidebar');
    function setSidebar(open, restoreFocus = false) {
        document.body.dataset.sidebarOpen = String(open);
        sidebarButton.setAttribute('aria-expanded', String(open));
        sidebarButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
        scrim.hidden = !open;
        if (restoreFocus) sidebarButton.focus();
    }
    sidebarButton.addEventListener('click', () => setSidebar(document.body.dataset.sidebarOpen !== 'true'));
    scrim.addEventListener('click', () => setSidebar(false, true));
    sidebar.addEventListener('click', event => {
        if (mobileLayout.matches && event.target.closest('.nav-btn, .new-chat-btn, .chat-history-item')) setSidebar(false, true);
    });
    mobileLayout.addEventListener('change', () => setSidebar(false));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            if (!panel.hidden) closeAppearance(true);
            else if (document.body.dataset.sidebarOpen === 'true') setSidebar(false, true);
        }
    });

    applyPreferences();
    updateVisibility();
    renderWelcome();
})();
