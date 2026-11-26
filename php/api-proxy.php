<?php
declare(strict_types=1);

require_once __DIR__ . '/auth-config.php';
sf_start_session();
header('Content-Type: application/json; charset=utf-8');

function sf_json_error(int $statusCode, string $detail): void
{
    http_response_code($statusCode);
    echo json_encode(['detail' => $detail], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

$user = $_SESSION['sf_user'] ?? null;
if (!is_array($user) || empty($user['user_id'])) {
    sf_json_error(401, 'Employee session expired. Please sign in again.');
}

$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
if (!in_array($method, ['GET', 'POST'], true)) {
    sf_json_error(405, 'Method not allowed.');
}

if ($method === 'POST') {
    $csrfHeader = (string) ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
    if (!hash_equals((string) ($_SESSION['sf_csrf'] ?? ''), $csrfHeader)) {
        sf_json_error(403, 'Invalid or missing CSRF security token.');
    }
}

$endpoint = (string) ($_GET['endpoint'] ?? '');
$allowedPattern = '#^/api/(?:v1/health|v1/scripts/recent(?:\?limit=\d+)?|v1/scripts/recent/[A-Za-z0-9_.-]+|v2/scripts/(?:generate|regenerate)|v1/script-falcon/(?:generate|regenerate-hook|regenerate-cta|send-to-clipfalcon|admin/grant-bonus-runs)|v1/script-falcon/history/[A-Za-z0-9_-]+(?:\?limit=\d+)?)$#';
if ($endpoint === '' || preg_match($allowedPattern, $endpoint) !== 1) {
    sf_json_error(400, 'Invalid or disallowed API endpoint path.');
}

if (!function_exists('curl_init')) {
    sf_json_error(500, 'PHP cURL extension is required to reach ScriptFalcon FastAPI.');
}

$backendBase = rtrim(sf_env('SCRIPTFALCON_API_URL', 'http://127.0.0.1:8000'), '/');
$targetUrl = $backendBase . $endpoint;
$signedJwt = sf_sign_internal_jwt($user, 300);

$headers = [
    'Accept: application/json',
    'Authorization: Bearer ' . $signedJwt,
];

$ch = curl_init($targetUrl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
curl_setopt($ch, CURLOPT_TIMEOUT, 120);
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);

if ($method === 'POST') {
    $rawBody = file_get_contents('php://input');
    $headers[] = 'Content-Type: application/json';
    curl_setopt($ch, CURLOPT_POSTFIELDS, $rawBody !== false ? $rawBody : '{}');
}

curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
$respBody = curl_exec($ch);
$curlErr = curl_error($ch);
$httpStatus = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($respBody === false || $httpStatus === 0) {
    sf_json_error(502, 'FastAPI backend unavailable: ' . ($curlErr ?: 'connection failed'));
}

http_response_code($httpStatus);
echo $respBody;
