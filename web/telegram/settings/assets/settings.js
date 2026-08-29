(function () {
    'use strict';

    var API_BASE = '';

    function getUserId() {
        var params = new URLSearchParams(window.location.search);
        var uid = params.get('user_id');
        if (uid) {
            localStorage.setItem('cv_user_id', uid);
            return uid;
        }
        return localStorage.getItem('cv_user_id') || '';
    }

    function setUserId(uid) {
        localStorage.setItem('cv_user_id', uid);
    }

    var EVENT_LABELS = {
        'UPLOAD_COMPLETED': 'Upload completed',
        'UPLOAD_FAILED': 'Upload failed',
        'BACKUP_COMPLETED': 'Backup completed',
        'BACKUP_FAILED': 'Backup failed',
        'SECURITY_ALERT': 'Security alerts',
        'HEALTH_ALERT': 'Health alerts',
        'BACKGROUND_JOB_FAILED': 'Background job failures',
        'STORAGE_WARNING': 'Storage warnings',
        'STORAGE_CRITICAL': 'Storage critical'
    };

    var userId = getUserId();

    // DOM refs
    var sections = {
        auth: document.getElementById('auth-section'),
        loading: document.getElementById('loading'),
        error: document.getElementById('error-section'),
        disconnected: document.getElementById('disconnected-section'),
        pending: document.getElementById('pending-section'),
        connected: document.getElementById('connected-section')
    };

    var els = {
        errorMsg: document.getElementById('error-msg'),
        userIdInput: document.getElementById('user-id-input'),
        authBtn: document.getElementById('auth-btn'),
        connectBtn: document.getElementById('connect-btn'),
        refreshBtn: document.getElementById('refresh-status-btn'),
        disconnectBtn: document.getElementById('disconnect-btn'),
        deepLink: document.getElementById('deep-link'),
        countdown: document.getElementById('countdown'),
        tgId: document.getElementById('tg-id'),
        connectedAt: document.getElementById('connected-at'),
        prefsList: document.getElementById('prefs-list'),
        msg: document.getElementById('msg'),
        changeUserBtn: document.getElementById('change-user-btn'),
        changeUserBtn2: document.getElementById('change-user-btn-2')
    };

    // State
    function showSection(name) {
        Object.keys(sections).forEach(function (k) {
            sections[k].classList.add('hidden');
        });
        if (sections[name]) sections[name].classList.remove('hidden');
    }

    function showError(text) {
        els.errorMsg.textContent = text;
        showSection('error');
    }

    var toastTimer = null;
    function showToast(text, isError) {
        clearTimeout(toastTimer);
        els.msg.textContent = text;
        els.msg.className = 'toast ' + (isError ? 'error' : 'success');
        toastTimer = setTimeout(function () {
            els.msg.classList.add('hidden');
        }, 4000);
    }

    function apiGet(path, cb) {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', API_BASE + path, true);
        xhr.setRequestHeader('X-User-Id', userId);
        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) {
                try { cb(null, JSON.parse(xhr.responseText), xhr.status); }
                catch (e) { cb('Invalid JSON', null, xhr.status); }
            }
        };
        xhr.send();
    }

    function apiPost(path, body, cb) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + path, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.setRequestHeader('X-User-Id', userId);
        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) {
                try { cb(null, JSON.parse(xhr.responseText), xhr.status); }
                catch (e) { cb('Invalid JSON', null, xhr.status); }
            }
        };
        xhr.send(JSON.stringify(body));
    }

    // Auth flow
    function showAuth() {
        showSection('auth');
    }

    function loadStatus() {
        showSection('loading');
        apiGet('/api/telegram/status', function (err, data, status) {
            if (err || status >= 500) {
                showError('Unable to connect to CloudVault service. Is Watchtower running?');
                return;
            }
            if (status === 401 || status === 403) {
                showSection('auth');
                showToast('Please enter your CloudVault username.', true);
                return;
            }
            if (data.connected) {
                showConnected(data.connection);
            } else {
                showDisconnected();
            }
        });
    }

    function showDisconnected() {
        showSection('disconnected');
    }

    function showPending(url) {
        els.deepLink.href = url;
        startCountdown(600);
        showSection('pending');
    }

    function showConnected(conn) {
        els.tgId.textContent = conn.telegram_user_id;
        var d = new Date(conn.connected_at);
        els.connectedAt.textContent = d.toLocaleDateString() + ' ' + d.toLocaleTimeString();
        showSection('connected');
        loadPrefs();
    }

    // Countdown
    var countdownTimer = null;
    var countdownRemaining = 0;

    function startCountdown(seconds) {
        countdownRemaining = seconds;
        clearInterval(countdownTimer);
        updateCountdown();
        countdownTimer = setInterval(function () {
            countdownRemaining--;
            updateCountdown();
            if (countdownRemaining <= 0) {
                clearInterval(countdownTimer);
                els.countdown.textContent = 'Token expired — generate a new one.';
            }
        }, 1000);
    }

    function updateCountdown() {
        var m = Math.floor(countdownRemaining / 60);
        var s = countdownRemaining % 60;
        els.countdown.textContent = 'Expires in ' + m + ':' + (s < 10 ? '0' : '') + s;
    }

    // Button loading state
    function setBtnLoading(btn, loading) {
        var textEl = btn.querySelector('.btn-text');
        var loadEl = btn.querySelector('.btn-loading');
        if (loading) {
            btn.disabled = true;
            if (textEl) textEl.classList.add('hidden');
            if (loadEl) loadEl.classList.remove('hidden');
        } else {
            btn.disabled = false;
            if (textEl) textEl.classList.remove('hidden');
            if (loadEl) loadEl.classList.add('hidden');
        }
    }

    // Generate token
    function generateToken() {
        setBtnLoading(els.connectBtn, true);
        apiPost('/api/telegram/link/generate', {}, function (err, data, status) {
            setBtnLoading(els.connectBtn, false);
            if (err || status >= 500) {
                showError('Failed to generate linking token. Please try again.');
                return;
            }
            if (data.error === 'active_token_exists') {
                showToast('A linking token is already active. Check your Telegram.', true);
                return;
            }
            if (data.deep_link) {
                showPending(data.deep_link);
            } else {
                showError('Unexpected response from server.');
            }
        });
    }

    // Disconnect
    function disconnect() {
        if (!confirm('Disconnect Telegram? You will stop receiving notifications.')) return;
        setBtnLoading(els.disconnectBtn, true);
        apiPost('/api/telegram/disconnect', {}, function (err, data, status) {
            setBtnLoading(els.disconnectBtn, false);
            if (err || status >= 500) {
                showToast('Disconnect failed. Try again.', true);
                return;
            }
            showToast('Telegram disconnected.');
            showDisconnected();
        });
    }

    // Preferences
    function loadPrefs() {
        apiGet('/api/telegram/prefs', function (err, data) {
            if (err || !data.preferences) return;
            renderPrefs(data.preferences);
        });
    }

    function renderPrefs(prefs) {
        els.prefsList.innerHTML = '';
        Object.keys(EVENT_LABELS).forEach(function (key) {
            var item = document.createElement('div');
            item.className = 'pref-item';

            var label = document.createElement('span');
            label.className = 'pref-label';
            label.textContent = EVENT_LABELS[key] || key;

            var toggle = document.createElement('input');
            toggle.type = 'checkbox';
            toggle.className = 'pref-toggle';
            toggle.checked = prefs[key] === 'true';
            toggle.addEventListener('change', function () {
                savePref(key, this.checked ? 'true' : 'false');
            });

            item.appendChild(label);
            item.appendChild(toggle);
            els.prefsList.appendChild(item);
        });
    }

    function savePref(key, value) {
        apiPost('/api/telegram/prefs', { key: key, value: value }, function (err, data) {
            if (err || (data && data.error)) {
                showToast('Failed to save preference.', true);
            }
        });
    }

    // Event bindings
    els.authBtn.addEventListener('click', function () {
        var input = els.userIdInput.value.trim();
        if (!input) {
            showToast('Please enter your username.', true);
            return;
        }
        userId = input;
        setUserId(userId);
        loadStatus();
    });

    els.userIdInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') els.authBtn.click();
    });

    els.connectBtn.addEventListener('click', generateToken);
    els.refreshBtn.addEventListener('click', loadStatus);
    els.disconnectBtn.addEventListener('click', disconnect);

    // Change user — clear saved username and return to auth
    function goToAuth() {
        localStorage.removeItem('cv_user_id');
        userId = '';
        els.userIdInput.value = '';
        showAuth();
    }
    if (els.changeUserBtn) els.changeUserBtn.addEventListener('click', goToAuth);
    if (els.changeUserBtn2) els.changeUserBtn2.addEventListener('click', goToAuth);

    // Auto-poll when pending
    setInterval(function () {
        if (!sections.pending.classList.contains('hidden')) {
            apiGet('/api/telegram/status', function (err, data) {
                if (!err && data && data.connected) {
                    clearInterval(countdownTimer);
                    showConnected(data.connection);
                    showToast('Telegram connected successfully!');
                }
            });
        }
    }, 5000);

    // Init
    if (!userId) {
        showAuth();
    } else {
        loadStatus();
    }
})();
