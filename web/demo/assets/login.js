(function () {
    'use strict';

    var DEMO_USER = 'demo';
    var DEMO_PASS = 'cloudvault';

    var form = document.getElementById('login-form');
    var msg = document.getElementById('msg');
    var btn = document.getElementById('submit-btn');

    function show(text, isError) {
        msg.textContent = text;
        msg.className = 'msg ' + (isError ? 'error' : 'success');
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();

        var username = document.getElementById('username').value.trim();
        var password = document.getElementById('password').value;

        if (!username || !password) {
            show('Please fill in both fields.', true);
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Signing in\u2026';
        show('');

        window.setTimeout(function () {
            btn.disabled = false;
            btn.textContent = 'Sign in';

            if (username === DEMO_USER && password === DEMO_PASS) {
                show('Welcome back, ' + username + '! This is a demo page.');
            } else {
                show('Invalid username or password.', true);
            }
        }, 600);
    });
})();