<?php
declare(strict_types=1);

/**
 * Route /apps/otp-register/          -> registration page (template)
 * Route /apps/otp-register/send      -> POST, sends OTP to an email
 * Route /apps/otp-register/verify    -> POST, validates code and marks request
 *                                       pending admin approval (account NOT enabled)
 *
 * Manual approval is done by an admin via occ:
 *   occ otp-register:pending          list pending requests
 *   occ otp-register:approve <user>   enable the account
 *   occ otp-register:reject <user>    remove the account
 */
return [
    'routes' => [
        ['name' => 'Otp#registerPage', 'url' => '/',              'verb' => 'GET'],
        ['name' => 'Otp#send',         'url' => '/send',          'verb' => 'POST'],
        ['name' => 'Otp#verify',       'url' => '/verify',        'verb' => 'POST'],
    ],
];