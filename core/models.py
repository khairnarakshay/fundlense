from django.conf import settings
from django.db import models

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At", help_text="Date and time when record was created.")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At", help_text="Date and time when record was last updated.")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)s_created", verbose_name="Created By", help_text="User who created this record.")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)s_updated", verbose_name="Updated By", help_text="User who last updated this record.")
    class Meta:
        abstract = True
