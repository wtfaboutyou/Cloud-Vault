<?php /** @var \OCP\Defaults $theme */ ?>
<div id="otp-register-page" class="guest">
    <h1><?php p($l->t('Create your CloudVault account')); ?></h1>
    <p class="otp-hint"><?php p($l->t('We will email you a 6-digit verification code to confirm your address. After that, your account will be reviewed by an administrator.')); ?></p>

    <form id="otp-form" action="#">
        <input type="hidden" name="step" value="send">
        <label for="username"><?php p($l->t('Username')); ?></label>
        <input type="text" id="username" name="username" autocomplete="username" required minlength="3">
        <label for="email"><?php p($l->t('Email')); ?></label>
        <input type="email" id="email" name="email" autocomplete="email" required>
        <button id="otp-btn" type="submit" class="primary"><?php p($l->t('Send verification code')); ?></button>
    </form>

    <form id="otp-verify-form" action="#" hidden>
        <input type="hidden" name="step" value="verify">
        <input type="hidden" id="v-username" name="username">
        <input type="hidden" id="v-email" name="email">
        <label for="code"><?php p($l->t('Verification code')); ?></label>
        <input type="text" id="code" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="000000" required>
        <button id="otp-verify-btn" type="submit" class="primary"><?php p($l->t('Verify email')); ?></button>
    </form>

    <p id="otp-msg" role="alert"></p>
    <p class="otp-hint"><?php p($l->t('After verifying your email, an administrator must approve your account before you can log in.')); ?></p>
</div>
