# ScriptFalcon PHP employee gateway + React UI
# Build from the repo root:  docker build -f php/Dockerfile -t scriptfalcon-web .

# ---- Stage 1: build the React app into php/assets ----
FROM node:24-slim AS frontend
WORKDIR /build/frontend-react
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend-react/ ./
# vite.config.js writes to ../php/assets
RUN mkdir -p /build/php && npm run build

# ---- Stage 2: Apache + PHP ----
FROM php:8.3-apache

# Production PHP settings; hide version banners.
RUN mv "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini" \
    && { \
        echo 'expose_php = Off'; \
        echo 'max_execution_time = 150'; \
        echo 'session.cookie_httponly = 1'; \
        echo 'session.use_strict_mode = 1'; \
    } > "$PHP_INI_DIR/conf.d/scriptfalcon.ini" \
    && { \
        echo 'ServerTokens Prod'; \
        echo 'ServerSignature Off'; \
        echo 'Timeout 150'; \
    } > /etc/apache2/conf-available/scriptfalcon.conf \
    && a2enconf scriptfalcon

COPY php/index.php php/api-proxy.php php/auth-config.php /var/www/html/
COPY --from=frontend /build/php/assets /var/www/html/assets

# Block direct web access to the shared config include; keep web files read-only.
RUN printf '<Files "auth-config.php">\n  Require all denied\n</Files>\n' >> /etc/apache2/conf-available/scriptfalcon.conf \
    && chown -R root:root /var/www/html \
    && chmod -R a+rX,go-w /var/www/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS -o /dev/null http://127.0.0.1/ || exit 1
