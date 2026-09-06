"""Formulários da tela de Configurações."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import Profile
from apps.finance.models import Account

User = get_user_model()


class ProfileForm(forms.ModelForm):
    """Edição do perfil do usuário (nome de exibição, conta padrão)."""

    class Meta:
        model = Profile
        fields = ["display_name", "default_account"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["default_account"].queryset = (
                Account.objects.for_user(user).filter(status=Account.Status.ACTIVE)
            )


class UserForm(forms.ModelForm):
    """Edição básica do usuário (nome, sobrenome, email)."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]


class PasswordChangeForm(forms.Form):
    """Troca de senha (requer senha atual + nova senha)."""

    current_password = forms.CharField(
        label="Senha atual",
        widget=forms.PasswordInput,
    )
    new_password = forms.CharField(
        label="Nova senha",
        widget=forms.PasswordInput,
        validators=[validate_password],
    )
    new_password_confirm = forms.CharField(
        label="Confirmar nova senha",
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        pwd = self.cleaned_data.get("current_password")
        if pwd and not self.user.check_password(pwd):
            raise forms.ValidationError("Senha atual incorreta.")
        return pwd

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password") and cleaned.get("new_password_confirm"):
            if cleaned["new_password"] != cleaned["new_password_confirm"]:
                self.add_error("new_password_confirm", "As senhas não conferem.")
        return cleaned


class WipeConfirmForm(forms.Form):
    """Confirmação para apagar dados financeiros."""

    confirm_text = forms.CharField(
        label='Digite "APAGAR" para confirmar',
        widget=forms.TextInput,
    )

    def clean_confirm_text(self):
        val = self.cleaned_data.get("confirm_text", "")
        if val.strip().upper() != "APAGAR":
            raise forms.ValidationError('Digite exatamente "APAGAR" para confirmar.')
        return val


class DeleteAccountForm(forms.Form):
    """Confirmação para deletar conta."""

    confirm_text = forms.CharField(
        label='Digite "DELETAR CONTA" para confirmar',
        widget=forms.TextInput,
    )
    password = forms.CharField(
        label="Senha atual",
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean_password(self):
        pwd = self.cleaned_data.get("password")
        if pwd and not self.user.check_password(pwd):
            raise forms.ValidationError("Senha incorreta.")
        return pwd

    def clean_confirm_text(self):
        val = self.cleaned_data.get("confirm_text", "")
        if val.strip().upper() != "DELETAR CONTA":
            raise forms.ValidationError('Digite exatamente "DELETAR CONTA" para confirmar.')
        return val
