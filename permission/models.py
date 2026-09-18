from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from core.models import BaseModel


class Module(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name="Module Name")
    code = models.CharField(max_length=100, unique=True, verbose_name="Module Code")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return self.name

class Permission(BaseModel):
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name="permissions")
    code = models.CharField(max_length=150, unique=True, verbose_name="Permission Code", help_text="Example: funds.view_fund")
    name = models.CharField(max_length=150, verbose_name="Permission Name")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.code


class Role(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name="Role Name")
    code = models.CharField(max_length=50, unique=True, verbose_name="Role Code")
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True, verbose_name="Permissions")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return self.name


class UserPermission(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="permission_overrides", verbose_name="User")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, related_name="user_overrides", verbose_name="Permission")
    is_allowed = models.BooleanField(
        default=True,
        verbose_name="Is Allowed"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "permission"],
                name="unique_user_permission_override"
            )
        ]

    def __str__(self):
        return (
            f"{self.user.email} - "
            f"{self.permission.code} - "
            f"{self.is_allowed}"
        )