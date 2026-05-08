from pathlib import Path

import environ
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    TIME_ZONE=(str, "Europe/Berlin"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-change-me-before-production",
)
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

INSTALLED_APPS = [
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "shop",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sewing_shop.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "sewing_shop.wsgi.application"

_force_sqlite = env.bool(
    "USE_SQLITE",
    default=env.bool("CI", default=False),
)

# Supabase uses PostgreSQL via DATABASE_URL. For offline tests/CI tooling, set USE_SQLITE=1 to pin SQLite.
_sqlite_url = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
if _force_sqlite:
    DATABASES = {"default": env.db_url_config(_sqlite_url)}
else:
    DATABASES = {"default": env.db_url("DATABASE_URL", default=_sqlite_url)}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
# Match this to your locale so the admin “hours ahead/behind server time” notice goes away.
# Override in .env, e.g. TIME_ZONE=Asia/Jerusalem
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

UNFOLD = {
    "SITE_TITLE": "Sewing Shop",
    "SITE_HEADER": "Sewing Shop",
    "SITE_SUBHEADER": "Operations Management",
    "SITE_SYMBOL": "content_cut",
    "THEME": "dark",
    "SITE_URL": None,
    "SITE_DROPDOWN": [
        {
            "icon": "dashboard",
            "title": _("Operations dashboard"),
            "link": reverse_lazy("shop:dashboard"),
        },
    ],
    "STYLES": [
        lambda request: "/static/shop/admin_override.css",
    ],
    "COLORS": {
        "primary": {
            "50":  "240 253 244",
            "100": "220 252 231",
            "200": "187 247 208",
            "300": "134 239 172",
            "400": "74 222 128",
            "500": "34 197 94",
            "600": "22 163 74",
            "700": "15 118 55",
            "800": "6 95 70",
            "900": "6 78 59",
            "950": "2 44 34",
        },
    },
    "NAVIGATION": [
        {
            "title": _("Operations"),
            "separator": False,
            "items": [
                {
                    "title": _("Dashboard"),
                    "icon": "dashboard",
                    "link": reverse_lazy("shop:dashboard"),
                },
                {
                    "title": _("Orders"),
                    "icon": "receipt_long",
                    "link": reverse_lazy("admin:shop_order_changelist"),
                },
                {
                    "title": _("Customers"),
                    "icon": "people",
                    "link": reverse_lazy("admin:shop_customer_changelist"),
                },
                {
                    "title": _("Customer lookup"),
                    "icon": "search",
                    "link": reverse_lazy("shop:customer_search"),
                },
            ],
        },
        {
            "title": _("Production"),
            "separator": True,
            "items": [
                {
                    "title": _("Work Tickets"),
                    "icon": "task_alt",
                    "link": reverse_lazy("admin:shop_workticket_changelist"),
                },
                {
                    "title": _("Deliveries"),
                    "icon": "local_shipping",
                    "link": reverse_lazy("admin:shop_delivery_changelist"),
                },
            ],
        },
        {
            "title": _("Catalogue"),
            "separator": True,
            "collapsible": True,
            "items": [
                {
                    "title": _("Garment Types"),
                    "icon": "checkroom",
                    "link": reverse_lazy("admin:shop_garmenttype_changelist"),
                },
                {
                    "title": _("Materials"),
                    "icon": "inventory_2",
                    "link": reverse_lazy("admin:shop_material_changelist"),
                },
                {
                    "title": _("Employees"),
                    "icon": "badge",
                    "link": reverse_lazy("admin:shop_employee_changelist"),
                },
            ],
        },
        {
            "title": _("System"),
            "separator": True,
            "collapsible": True,
            "items": [
                {
                    "title": _("Measurements"),
                    "icon": "straighten",
                    "link": reverse_lazy("admin:shop_measurement_changelist"),
                },
                {
                    "title": _("Garments"),
                    "icon": "content_cut",
                    "link": reverse_lazy("admin:shop_garment_changelist"),
                },
                {
                    "title": _("Status History"),
                    "icon": "history",
                    "link": reverse_lazy("admin:shop_statushistory_changelist"),
                },
            ],
        },
    ],
}
