"""Backends de autenticação do FINTECPESSOAL.

Usa o sistema de autenticação nativo do Django. O `User` customizado herda
`AbstractUser` e, portanto, exige `username`. Para que a experiência do usuário
não dependa de detalhes técnicos (cadastro pede apenas nome/email/senha), o
`username` é derivado automaticamente do email no cadastro e o login é feito
pelo **email** (identificador amigável), via este backend.
"""

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model


class EmailBackend(ModelBackend):
    """Autentica pelo email (case-insensitive) em vez do username.

    Mantém os validadores de senha e a verificação de `is_active` do
    `ModelBackend` padrão do Django.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        # A interface envia o campo "email" como identificador de login.
        identifier = username or kwargs.get("email") or ""
        if not identifier:
            return None
        try:
            user = User.objects.get(email__iexact=identifier.strip())
        except User.DoesNotExist:
            # Não revelar se o email existe; roda o hasher para igualar tempo.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
