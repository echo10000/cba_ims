from django.conf import settings
from django.shortcuts import redirect
import re

class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = getattr(settings, 'LOGIN_URL', '/login/')
        self.exempt_urls = [re.compile(self.login_url.lstrip('/'))]
        if hasattr(settings, 'LOGIN_EXEMPT_URLS'):
            self.exempt_urls += [re.compile(url) for url in settings.LOGIN_EXEMPT_URLS]
        
        self.static_url = getattr(settings, 'STATIC_URL', '/static/')
        self.media_url = getattr(settings, 'MEDIA_URL', '/media/')

    def __call__(self, request):
        path = request.path_info.lstrip('/')
        
        # Always allow static and media requests
        if path.startswith(self.static_url.lstrip('/')) or \
           path.startswith(self.media_url.lstrip('/')):
            return self.get_response(request)
            
        if not request.user.is_authenticated:
            if not any(m.match(path) for m in self.exempt_urls):
                return redirect(f"{self.login_url}?next={request.path}")
                
        return self.get_response(request)


class NoCachePrivateMiddleware:
    """
    Adds Cache-Control: private, no-store headers to authenticated HTML responses.
    This prevents browsers and service workers from caching personalized pages.
    Static assets are NOT affected (they are identified by their /static/ prefix).
    """
    PRIVATE_PATHS = [
        '/dashboard/', '/assignments/', '/borrowing/', '/maintenance/',
        '/reports/', '/audit/', '/organizations/employees/', '/transfers/',
        '/supplies/', '/disposals/', '/accounts/users/', '/inventory/physical-verification/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Only apply to authenticated HTML GET responses
        if (
            getattr(request, 'user', None)
            and request.user.is_authenticated
            and request.method == 'GET'
            and not request.path.startswith('/static/')
            and not request.path.startswith('/media/')
            and not request.path.startswith('/health/')
            and any(request.path.startswith(p) for p in self.PRIVATE_PATHS)
        ):
            response['Cache-Control'] = 'private, no-store'
            response['Pragma'] = 'no-cache'
        return response

