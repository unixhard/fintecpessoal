"""Formulários de autenticação do FINTECPESSOAL.

O cadastro pede apenas nome, email, senha e confirmação. O `username` (exigido
pelo `AbstractUser`) é derivado automaticamente do email — o usuário não
precisa entender esse detalhe técnico.
"""

import unicodedata

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm

User = get_user_model()


def _make_username_from_email(email):
    """Deriva um `username` único a partir do email.

    Usa a parte local do email, normalizando acentos e espaços. Se já existir,
    acrescenta um sufixo numérico para garantir unicidade.
    """
    local = (email or "").split("@")[0].strip().lower()
    local = unicodedata.normalize("NFKD", local).encode("ascii", "ignore").decode()
    # Substitui caracteres inválidos para username por underscore.
    base = "".join(c if (c.isalnum() or c in "._+-") else "_" for c in local) or "user"

    candidate = base
    counter = 1
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


class SignUpForm(forms.Form):
    """Cadastro de novo usuário (nome, email, senha, confirmação)."""

    name = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "Seu nome", "autocomplete": "name"}
        ),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={"placeholder": "voce@exemplo.com", "autocomplete": "email"}
        ),
    )
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(
            attrs={"placeholder": "Crie uma senha", "autocomplete": "new-password"}
        ),
    )
    password_confirmation = forms.CharField(
        label="Confirmação de senha",
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Repita a senha",
                "autocomplete": "new-password",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe uma conta com este email.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        # Não revelar regras internas em excesso — mensagem amigável e genérica.
        password_validation.validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error(
                "password_confirmation",
                "A confirmação de senha não confere com a senha.",
            )
        return cleaned

    def save(self, commit=True):
        cleaned = self.cleaned_data
        name = (cleaned["name"] or "").strip()
        first, _, last = name.partition(" ")
        user = User(
            username=_make_username_from_email(cleaned["email"]),
            email=cleaned["email"],
            first_name=first,
            last_name=last.strip(),
        )
        user.set_password(cleaned["password"])
        if commit:
            user.save()
        return user


class FintroLoginForm(AuthenticationForm):
    """Login por email/identificador.

    Reutiliza o `AuthenticationForm` do Django (que chama os backends,
    incluindo o `EmailBackend` deste app). Rotula o campo como "Email".
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": "seu@email.com",
                "autocomplete": "email",
            }
        )
        self.fields["password"].widget.attrs.update(
            {"placeholder": "Sua senha", "autocomplete": "current-password"}
        )
