import re

from django.http import HttpResponse

_LOCALHOST_ORIGIN_RE = re.compile(r"^http://(?:localhost|127\.0\.0\.1)(?::\d+)?$")
_ALLOWED_ORIGINS = {
    "https://cultnova.ru",
    "https://www.cultnova.ru",
}


def _is_allowed_origin(origin: str) -> bool:
    if origin in _ALLOWED_ORIGINS:
        return True
    return bool(_LOCALHOST_ORIGIN_RE.match(origin))


def _append_vary(response, header: str):
    current = response.get("Vary")
    if not current:
        response["Vary"] = header
        return

    existing = {h.strip().lower() for h in current.split(",") if h.strip()}
    if header.lower() in existing:
        return

    response["Vary"] = f"{current}, {header}"


class CorsMiddleware:
    """
    Minimal CORS support for /api/* endpoints.

    Allowed origins:
    - https://cultnova.ru (+ www)
    - http://localhost[:port]
    - http://127.0.0.1[:port]
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method == "OPTIONS":
            response = HttpResponse(status=200)
            return self._add_cors_headers(request, response, is_preflight=True)

        response = self.get_response(request)
        if request.path.startswith("/api/"):
            return self._add_cors_headers(request, response, is_preflight=False)

        return response

    def _add_cors_headers(self, request, response, is_preflight: bool):
        origin = request.META.get("HTTP_ORIGIN")
        if not origin or not _is_allowed_origin(origin):
            return response

        response["Access-Control-Allow-Origin"] = origin
        _append_vary(response, "Origin")

        if is_preflight:
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            request_headers = request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS")
            if request_headers:
                response["Access-Control-Allow-Headers"] = request_headers
            else:
                response["Access-Control-Allow-Headers"] = "Content-Type"
            response["Access-Control-Max-Age"] = "86400"

        return response
