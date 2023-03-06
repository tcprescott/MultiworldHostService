import urllib.parse

import settings


TORTOISE_ORM = {
    "connections": {"default": f'mysql://{settings.DB_USER}:{urllib.parse.quote_plus(settings.DB_PASS)}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}'},
    "apps": {
        "models": {
            "models": ["models", "aerich.models"],
            "default_connection": "default",
        },
    },
}
