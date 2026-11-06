from django.contrib.auth.password_validation import MinimumLengthValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class VietnameseMinimumLengthValidator(MinimumLengthValidator):
    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                _("Mật khẩu cần có ít nhất %(min_length)d ký tự."),
                code="password_too_short",
                params={"min_length": self.min_length},
            )

    def get_help_text(self):
        return _("Mật khẩu cần có ít nhất %(min_length)d ký tự.") % {
            "min_length": self.min_length,
        }
