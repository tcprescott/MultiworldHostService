from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `multiworlds` ADD `multidata_url` VARCHAR(2000);
        ALTER TABLE `multiworlds` ALTER COLUMN `active` SET DEFAULT 0;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `multiworlds` DROP COLUMN `multidata_url`;
        ALTER TABLE `multiworlds` ALTER COLUMN `active` SET DEFAULT 1;"""
