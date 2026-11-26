<?php
declare(strict_types=1);

require_once __DIR__ . '/auth-config.php';
sf_start_session();

$action = (string) ($_GET['action'] ?? '');
if ($action === 'logout') {
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $params = session_get_cookie_params();
        setcookie(session_name(), '', time() - 42000, $params['path'], $params['domain'] ?? '', (bool) $params['secure'], (bool) $params['httponly']);
    }
    session_destroy();
    header('Location: index.php');
    exit;
}

$loginError = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && $action === 'login') {
    $csrf = (string) ($_POST['csrf_token'] ?? '');
    if (!hash_equals((string) ($_SESSION['sf_csrf'] ?? ''), $csrf)) {
        $loginError = 'Session security token expired. Please reload and try again.';
    } else {
        $email = (string) ($_POST['email'] ?? '');
        $passcode = (string) ($_POST['passcode'] ?? '');
        $verified = sf_verify_employee_login($email, $passcode);
        if ($verified !== null) {
            session_regenerate_id(true);
            $_SESSION['sf_user'] = $verified;
            $_SESSION['sf_csrf'] = bin2hex(random_bytes(24));
            header('Location: index.php');
            exit;
        }
        $loginError = 'Access restricted to VG Digital Falcon employees. Check your email or passcode.';
    }
}

$user = $_SESSION['sf_user'] ?? null;
if (!is_array($user)) {
    $csrfTokenEsc = htmlspecialchars((string) $_SESSION['sf_csrf'], ENT_QUOTES, 'UTF-8');
    $errEsc = htmlspecialchars($loginError, ENT_QUOTES, 'UTF-8');
    ?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ScriptFalcon Sign In | VG Digital Falcon</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="assets/app.css" />
</head>
<body>
  <main style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;">
    <div class="surface-card" style="width:100%;max-width:420px;padding:28px;">
      <div class="brand" style="margin-bottom:6px;">
        <span class="brand-name">ScriptFalcon</span>
        <span class="brand-sub">VG Digital Falcon CRM</span>
      </div>
      <p class="muted-copy" style="margin-bottom:18px;">
        Sign in with your VG Digital Falcon employee account to access Standalone &amp; CRM Studio.
      </p>
      <?php if ($errEsc !== ''): ?>
        <div class="alert-banner" role="alert"><?= $errEsc ?></div>
      <?php endif; ?>
      <form method="post" action="index.php?action=login" class="side-group">
        <input type="hidden" name="csrf_token" value="<?= $csrfTokenEsc ?>" />
        <label class="field-label" for="email">Employee Email</label>
        <input id="email" name="email" type="email" class="input" required placeholder="writer@vgdigitalfalcon.com" autocomplete="username" />
        <label class="field-label" for="passcode">Passcode</label>
        <input id="passcode" name="passcode" type="password" class="input" required placeholder="Enter employee passcode" autocomplete="current-password" />
        <button type="submit" class="btn-primary" style="margin-top:12px;">Sign In to Studio</button>
      </form>
      <p class="helper-text" style="margin-top:14px;">
        Internal auth session is verified server-side; API keys and FastAPI ports remain hidden behind PHP.
      </p>
    </div>
  </main>
</body>
</html>
    <?php
    exit;
}

$rawClient = (string) ($_GET['client_id'] ?? 'vg_demo_clinic');
$safeClient = preg_match('/^[A-Za-z0-9][A-Za-z0-9_-]{1,99}$/', $rawClient) ? $rawClient : 'vg_demo_clinic';
$defaultMode = ((string) ($_GET['mode'] ?? '') === 'crm') ? 'crm' : 'standalone';

$bootstrapJson = json_encode(
    [
        'authenticated' => true,
        'viaPhp' => true,
        'apiBase' => 'api-proxy.php',
        'csrfToken' => (string) $_SESSION['sf_csrf'],
        'user' => [
            'user_id' => (string) $user['user_id'],
            'role' => (string) $user['role'],
            'email' => (string) ($user['email'] ?? ''),
            'display_name' => (string) ($user['display_name'] ?? $user['user_id']),
        ],
        'defaultClientId' => $safeClient,
        'defaultMode' => $defaultMode,
    ],
    JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_UNESCAPED_SLASHES
);
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ScriptFalcon | VG Digital Falcon</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans+Tamil:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20,500,0,0" rel="stylesheet" />
  <link rel="stylesheet" href="assets/app.css" />
</head>
<body>
  <div id="root"></div>
  <script id="sf-bootstrap" type="application/json"><?= $bootstrapJson ?></script>
  <script type="module" src="assets/app.js"></script>
</body>
</html>
