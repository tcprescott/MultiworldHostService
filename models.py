from tortoise.models import Model
from tortoise import fields

class Multiworlds(Model):
    id = fields.IntField(pk=True)
    token = fields.CharField(max_length=255, unique=True) # derive this using "hashlib.md5(bytes(2)).hexdigest()[0:8]" if needed
    port = fields.IntField()
    noexpiry = fields.BooleanField(default=False)
    admin = fields.BigIntField(null=True)
    race = fields.BooleanField(default=False)
    meta = fields.JSONField(null=True)
    multidata_url = fields.CharField(max_length=2000, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    active = fields.BooleanField(default=False)