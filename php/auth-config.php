<?php
declare(strict_types=1);

/**
 * Shared PHP session, environment loader, and internal HS256 JWT signer
 * for the VG Digital Falcon ScriptFalcon gateway.
 */

function sf_load_env(): array
{
    static $cache = null;
    if ($cache !== null) {
        return $cache;
    }

    $vars = [];
    $envPath = dirname(__DIR__) . DIRECTORY_SEPARATOR . '.env';
    if (is_file($envPath) && is_readable($envPath)) {
        $lines = file($envPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if (is_array($lines)) {
            foreach ($lines as $line) {
                $trimmed = trim($line);
                if ($trimmed === '' || str_starts_with($trimmed, '#') || !str_contains($trimmed, '=')) {
                    continue;
                }
                [$k, $v] = explode('=', $trimmed, 2);
                $key = trim($k);
                $val = trim($v);
                if (
                    (str_starts_with($val, '"') && str_ends_with($val, '"'))
                    || (str_starts_with($val, "'") && str_ends_with($val, "'"))
                ) {
                    $val = substr($val, 1, -1);
                }
                $vars[$key] = $val;
            }
        }
    }
    $cache = $vars;
    return $cache;
}

function sf_env(string $key, string $default = ''): string
{
    $val = getenv($key);
    if ($val !== false && $val !== '') {
        return (string) $val;
    }
    $dotenv = sf_load_env();
    return isset($dotenv[$key]) && $dotenv[$key] !== '' ? (string) $dotenv[$key] : $default;
}

function sf_start_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $isHttps = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'httponly' => true,
        'samesite' => 'Lax',
        'secure' => $isHttps,
    ]);
    session_name('SCRIPTFALCON_SESSID');
    session_start();
    if (empty($_SESSION['sf_csrf'])) {
        $_SESSION['sf_csrf'] = bin2hex(random_bytes(24));
    }
}

function sf_base64url_encode(string $data): string
{
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}

function sf_sign_internal_jwt(array $user, int $ttlSeconds = 300): string
{
    $secret = sf_env('SUPABASE_JWT_SECRET', '');
    if ($secret === '') {
        $secret = sf_env('CRM_JWT_SECRET', 'vg-digital-falcon-dev-secret-change-in-prod');
    }

    $now = time();
    $header = sf_base64url_encode((string) json_encode(['alg' => 'HS256', 'typ' => 'JWT'], JSON_UNESCAPED_SLASHES));
    $payload = sf_base64url_encode(
        (string) json_encode(
            [
                'sub' => (string) ($user['user_id'] ?? 'studio_employee'),
                'role' => (string) ($user['role'] ?? 'employee'),
                'email' => (string) ($user['email'] ?? ''),
                'iat' => $now,
                'exp' => $now + $ttlSeconds,
            ],
            JSON_UNESCAPED_SLASHES
        )
    );
    $signature = sf_base64url_encode(hash_hmac('sha256', "$header.$payload", $secret, true));
    return "$header.$payload.$signature";
}

function sf_verify_employee_login(string $email, string $passcode): ?array
{
    $cleanEmail = strtolower(trim($email));
    if ($cleanEmail === '' || $passcode === '') {
        return null;
    }

    $usersJson = sf_env('SCRIPTFALCON_CRM_USERS_JSON', '');
    if ($usersJson !== '') {
        $records = json_decode($usersJson, true);
        if (is_array($records)) {
            foreach ($records as $entry) {
                if (!is_array($entry)) {
                    continue;
                }
                if (strtolower(trim((string) ($entry['email'] ?? ''))) !== $cleanEmail) {
                    continue;
                }
                $hash = (string) ($entry['password_hash'] ?? '');
                if ($hash !== '' && password_verify($passcode, $hash)) {
                    $role = strtolower((string) ($entry['role'] ?? 'employee'));
                    if (!in_array($role, ['employee', 'admin'], true)) {
                        return null;
                    }
                    return [
                        'user_id' => (string) ($entry['user_id'] ?? preg_replace('/[^a-z0-9_-]/', '_', $cleanEmail)),
                        'role' => $role,
                        'email' => $cleanEmail,
                        'display_name' => (string) ($entry['display_name'] ?? $cleanEmail),
                    ];
                }
            }
        }
        return null;
    }

    if (strtolower(sf_env('CRM_ENV', 'development')) === 'production') {
        return null;
    }

    $expectedPasscode = sf_env('SCRIPTFALCON_DEMO_PASSCODE', 'falcon-crm');
    if (!hash_equals($expectedPasscode, $passcode)) {
        return null;
    }

    $localDirectory = [
        'writer@vgdigitalfalcon.com' => ['user_id' => 'emp_writer_01', 'role' => 'employee', 'display_name' => 'Script Writer'],
        'admin@vgdigitalfalcon.com' => ['user_id' => 'admin_lead_01', 'role' => 'admin', 'display_name' => 'Agency Lead'],
    ];

    if (isset($localDirectory[$cleanEmail])) {
        return array_merge($localDirectory[$cleanEmail], ['email' => $cleanEmail]);
    }

    if (str_ends_with($cleanEmail, '@vgdigitalfalcon.com')) {
        $slug = preg_replace('/[^a-z0-9_-]/', '_', explode('@', $cleanEmail, 2)[0]);
        return [
            'user_id' => 'emp_' . ($slug !== '' ? $slug : 'teammate'),
            'role' => 'employee',
            'email' => $cleanEmail,
            'display_name' => ucfirst(str_replace('_', ' ', $slug ?: 'Teammate')),
        ];
    }

    return null;
}
