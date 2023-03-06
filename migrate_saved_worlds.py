import models
import asyncio
import settings
from tortoise import Tortoise
import urllib.parse
import json
import tortoise.exceptions

async def migrate():
    with open("data/saved_worlds.json", mode="r", encoding="utf8") as f:
        saved_worlds = json.load(f)

    for token, data in saved_worlds.items():
        try:
            await models.Multiworlds.create(
                token=token,
                port=data["port"],
                noexpiry=data["noexpiry"],
                admin=data["admin"],
                race=data.get('racemode', False),
                meta=data["meta"],
                multidata_url=data.get("multidata_url", None),
                active=True,
            )
        except tortoise.exceptions.IntegrityError:
            print(f"Failed to migrate {token} because it already exists.")

async def database():
    await Tortoise.init(
        db_url=f'mysql://{settings.DB_USER}:{urllib.parse.quote_plus(settings.DB_PASS)}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}',
        modules={'models': ['models']}
    )

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    dbtask = loop.create_task(database())
    loop.run_until_complete(dbtask)
    migrate = loop.create_task(migrate())
    loop.run_until_complete(migrate)