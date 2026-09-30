"""
Django settings for CBA IMS (Inventory Management System).

Generated for production and development environments.
Follows Django best practices and 12-factor application methodology.
"""

from pathlib import Path
import urllib.parse
from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

SECRET_KEY = config(
    'SECRET_KEY',
    default='django-insecure-cba-ims-key-change-this-in-production-environments-38914'
)

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='localhost,127.0.0.1,[::1]',
    cast=Csv()
)

# Application definition

INSTALLED_APPS = [
    # Django Built-in Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-Party Apps
    'crispy_forms',
    'crispy_bootstrap5',
    'django_filters',
    'axes',

    # CBA IMS Core & Domain Apps
    'apps.accounts',
    'apps.organizations',
    'apps.inventory',
    'apps.supplies',
    'apps.assignments',
    'apps.borrowing',
    'apps.transfers',
    'apps.maintenance',
    'apps.disposals',
    'apps.reports',
    'apps.audit',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.accounts.middleware.NoCachePrivateMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
#
# Defaults to SQLite for local development.
# To connect to PostgreSQL, provide DATABASE_URL or set individual DB_* parameters in .env:
#
# Option A (DATABASE_URL):
#   DATABASE_URL=postgres://postgres:password@localhost:5432/cba_ims
#
# Option B (Individual parameters):
#   DB_ENGINE=django.db.backends.postgresql
#   DB_NAME=cba_ims
#   DB_USER=postgres
#   DB_PASSWORD=your_secure_password
#   DB_HOST=localhost
#   DB_PORT=5432

DATABASE_URL = config('DATABASE_URL', default=None)

if DATABASE_URL:
    parsed_db_url = urllib.parse.urlparse(DATABASE_URL)
    engine = 'django.db.backends.postgresql' if 'postgres' in parsed_db_url.scheme else parsed_db_url.scheme
    DATABASES = {
        'default': {
            'ENGINE': engine,
            'NAME': parsed_db_url.path.lstrip('/'),
            'USER': parsed_db_url.username or '',
            'PASSWORD': parsed_db_url.password or '',
            'HOST': parsed_db_url.hostname or '',
            'PORT': str(parsed_db_url.port or '5432'),
        }
    }
else:
    db_engine = config('DB_ENGINE', default='django.db.backends.sqlite3')
    if db_engine == 'django.db.backends.sqlite3':
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / config('DB_NAME', default='db.sqlite3'),
            }
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': db_engine,
                'NAME': config('DB_NAME', default='cba_ims'),
                'USER': config('DB_USER', default='postgres'),
                'PASSWORD': config('DB_PASSWORD', default=''),
                'HOST': config('DB_HOST', default='localhost'),
                'PORT': config('DB_PORT', default='5432'),
            }
        }

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Authentication Backends
AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.CBAAxesBackend',
    'django.contrib.auth.backends.ModelBackend',
]


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = config('TIME_ZONE', default='UTC')

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# Media files (User uploads, QR codes, attachments)
# https://docs.djangoproject.com/en/4.2/topics/files/

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Crispy Forms Configuration
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# Authentication URLs
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
LOGIN_EXEMPT_URLS = [
    r'^admin/',
    r'^static/',
    r'^media/',
]

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CSRF Trusted Origins (for HTTPS deployments behind reverse proxies)
_csrf_origins = config('DJANGO_CSRF_TRUSTED_ORIGINS', default=None)
if _csrf_origins is None:
    _csrf_origins = config('CSRF_TRUSTED_ORIGINS', default='')

if _csrf_origins:
    CSRF_TRUSTED_ORIGINS = [orig.strip() for orig in str(_csrf_origins).split(',') if orig.strip()]
else:
    CSRF_TRUSTED_ORIGINS = []


# Login throttling (django-axes)
AXES_FAILURE_LIMIT = 5  # Lock after 5 failed attempts
AXES_COOLOFF_TIME = 1  # 1 hour lockout
AXES_LOCKOUT_CALLABLE = None
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = False
AXES_USERNAME_CALLABLE = None

# Production security settings (enabled when DEBUG=False)
if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    # HSTS - start conservative, allow admin to tune
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
    SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# Always set these
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

# Reverse proxy SSL header: only trust X-Forwarded-Proto when explicitly configured
# and deployed behind a trusted reverse proxy (e.g. Nginx) that sanitizes this header.
_use_proxy_ssl_header = config('SECURE_PROXY_SSL_HEADER', default=False, cast=bool)
if _use_proxy_ssl_header:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_PROXY_SSL_HEADER = None


# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
