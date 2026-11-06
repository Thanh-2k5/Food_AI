from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from .models import UserProfile

User = get_user_model()


class RegistrationForm(UserCreationForm):
    username = forms.CharField(
        label=_("Tên người dùng hoặc email"),
        max_length=150,
        widget=forms.TextInput(attrs={
            "placeholder": "Tên người dùng (hoặc Email)",
            "autocomplete": "username",
        }),
    )
    password1 = forms.CharField(
        label=_("Mật khẩu"),
        help_text=_("Mật khẩu cần có ít nhất 8 ký tự."),
        strip=False,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Mật khẩu",
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label=_("Xác nhận mật khẩu"),
        strip=False,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Xác nhận mật khẩu",
            "autocomplete": "new-password",
        }),
    )
    food_preference = forms.CharField(
        label=_("Sở thích ẩm thực"),
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Sở thích ẩm thực (VD: Chay, Châu Á)",
        }),
    )
    first_name = forms.CharField(
        label=_("Tên hiển thị"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Tên của bạn",
            "autocomplete": "given-name",
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "password1", "password2")

    def clean_username(self):
        identifier = self.cleaned_data["username"].strip()
        if "@" in identifier:
            try:
                validate_email(identifier)
            except ValidationError:
                raise ValidationError(
                    _("Vui lòng nhập email hợp lệ hoặc tên người dùng.")
                ) from None
            if User.objects.filter(email__iexact=identifier).exists():
                raise ValidationError(_("Email này đã được đăng ký."))
        if User.objects.filter(username__iexact=identifier).exists():
            raise ValidationError(_("Tên người dùng này đã được sử dụng."))
        return identifier

    def save(self, commit=True):
        user = super().save(commit=False)
        identifier = self.cleaned_data["username"]
        if "@" in identifier:
            user.email = identifier
        user.first_name = self.cleaned_data["first_name"].strip()
        if commit:
            user.save()
            UserProfile.objects.create(
                user=user,
                food_preference=self.cleaned_data["food_preference"].strip(),
            )
        return user


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label=_("Tên người dùng hoặc email"),
        max_length=254,
        widget=forms.TextInput(attrs={
            "placeholder": "Tên người dùng hoặc email",
            "autocomplete": "username",
            "autofocus": True,
        }),
    )
    password = forms.CharField(
        label=_("Mật khẩu"),
        strip=False,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Mật khẩu",
            "autocomplete": "current-password",
        }),
    )

    def clean(self):
        identifier = self.cleaned_data.get("username", "").strip()
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
            if user is not None:
                self.cleaned_data["username"] = user.get_username()
        return super().clean()
