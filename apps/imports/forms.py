"""Formulários da camada de importação.

Upload: aceita CSV, OFX ou XLSX (valida extensão e tamanho) e permite escolher
a conta padrão para onde os lançamentos vão (revisável depois). Ownership das
contas é garantida filtrando por ``for_user(user)``.

Suporta também importação DE CARTÃO DE CRÉDITO: nesse caso o usuário escolhe
"Cartão de crédito" como tipo e seleciona o cartão; os lançamentos são criados
como compras parceladas em vez de despesas de consumo.
"""

from django import forms

from apps.cards.models import CreditCard
from apps.finance.models import Account

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

_ALLOWED_EXT = {
    ".csv": "csv",
    ".ofx": "ofx",
    ".qfx": "ofx",
    ".xlsx": "xlsx",
}


class ImportUploadForm(forms.Form):
    IMPORT_TYPE_ACCOUNT = "account"
    IMPORT_TYPE_CARD = "card"
    IMPORT_TYPES = (
        (IMPORT_TYPE_ACCOUNT, "Conta (extrato bancário)"),
        (IMPORT_TYPE_CARD, "Cartão (fatura/extrato do cartão)"),
    )

    file = forms.FileField(
        label="Arquivo",
        help_text="CSV, OFX/QFX ou XLSX (máx. 5 MB).",
    )
    import_type = forms.ChoiceField(
        label="Tipo de importação",
        choices=IMPORT_TYPES,
        initial=IMPORT_TYPE_ACCOUNT,
        widget=forms.RadioSelect,
    )
    account = forms.ModelChoiceField(
        label="Conta padrão",
        queryset=Account.objects.none(),
        required=False,
        help_text="Opcional — os lançamentos vão para esta conta (pode ajustar na revisão).",
    )
    card = forms.ModelChoiceField(
        label="Cartão",
        queryset=CreditCard.objects.none(),
        required=False,
        help_text="Obrigatório para fatura de cartão — as compras parceladas vão para este cartão.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = (
                Account.objects.for_user(user).filter(status=Account.Status.ACTIVE)
            )
            self.fields["card"].queryset = (
                CreditCard.objects.for_user(user).filter(status=CreditCard.Status.ACTIVE)
            )

    def clean(self):
        cleaned = super().clean()
        import_type = cleaned.get("import_type")
        if import_type == self.IMPORT_TYPE_CARD and not cleaned.get("card"):
            self.add_error("card", "Selecione o cartão para importar a fatura.")
        return cleaned

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("O arquivo excede 5 MB.")
        name = (f.name or "").lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in _ALLOWED_EXT:
            raise forms.ValidationError(
                "Tipo de arquivo não suportado. Use CSV, OFX/QFX ou XLSX."
            )
        return f

    def file_type(self):
        f = self.cleaned_data.get("file")
        if not f:
            return None
        name = (f.name or "").lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        return _ALLOWED_EXT.get(ext)
