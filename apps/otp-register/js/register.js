(function () {
    'use strict';
    var base = OC.generateUrl('/apps/otp-register');
    var form = document.getElementById('otp-form');
    var vform = document.getElementById('otp-verify-form');
    var msg = document.getElementById('otp-msg');

    function show(text, isError) {
        msg.textContent = text;
        msg.className = isError ? 'error' : 'success';
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var username = document.getElementById('username').value.trim();
        var email = document.getElementById('email').value.trim();
        show('Sending code\u2026');
        fetch(base + '/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'requesttoken': OC.requestToken},
            body: JSON.stringify({username: username, email: email})
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.error) { show(data.error, true); return; }
            document.getElementById('v-username').value = username;
            document.getElementById('v-email').value = email;
            form.hidden = true;
            vform.hidden = false;
            show('Code sent to ' + data.sent_to + '. Enter the 6-digit code below.');
        }).catch(function () { show('Network error, please retry.', true); });
    });

    vform.addEventListener('submit', function (e) {
        e.preventDefault();
        var username = document.getElementById('v-username').value;
        var email = document.getElementById('v-email').value;
        var code = document.getElementById('code').value.trim();
        show('Verifying\u2026');
        fetch(base + '/verify', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'requesttoken': OC.requestToken},
            body: JSON.stringify({username: username, email: email, code: code})
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.error) { show(data.error, true); return; }
            if (data.pending) {
                show('Email verified! Your account is now waiting for admin approval. You will be notified once your account is activated.');
            } else {
                show('Account activated! You can now log in.');
            }
            setTimeout(function () { window.location.href = OC.generateUrl('/login'); }, 1500);
        }).catch(function () { show('Network error, please retry.', true); });
    });
})();
