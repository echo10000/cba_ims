from axes.backends import AxesStandaloneBackend


class CBAAxesBackend(AxesStandaloneBackend):
    """
    Subclass of AxesStandaloneBackend that gracefully handles calls to
    authenticate() where request is None (e.g. Django test client.login()
    and management commands). In real HTTP requests, the request object is
    always passed, and Axes enforces lockout policies as configured.
    """
    def authenticate(self, request=None, username=None, password=None, **kwargs):
        if request is None:
            return None
        return super().authenticate(request=request, username=username, password=password, **kwargs)
