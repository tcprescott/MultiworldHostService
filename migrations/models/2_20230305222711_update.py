from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `multiworlds` MODIFY COLUMN `port` INT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `multiworlds` MODIFY COLUMN `port` INT NOT NULL;"""
