"""Formulários do app comprovantes.

Padrão do projeto: forms.Form puro que delega escrita às services. A validação
de tamanho/tipo do arquivo acontece aqui (cai no form) e de novo no service
(defesa em profundidade, mesma regra).
"""

from django import forms

from .models import Comprovante
from .services import UploadError, _validate_upload


class ComprovanteCreateForm(forms.Form):
    title = forms.CharField(
        label="Título", max_length=160,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Nota fiscal geladeira"}),
    )
    kind = forms.ChoiceField(label="Tipo", choices=Comprovante.Kind.choices)
    file = forms.FileField(label="Arquivo (máx. 2 MB)", required=True)
    warranty_expiry = forms.DateField(
        label="Expiração da garantia",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    notes = forms.CharField(
        label="Observações", required=False, max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Opcional"}),
    )

    def clean_file(self):
        data = self.cleaned_data["file"]
        try:
            _validate_upload(data)
        except UploadError as exc:
            raise forms.ValidationError(str(exc))
        return data


class ComprovanteEditForm(forms.Form):
    title = forms.CharField(label="Título", max_length=160)
    kind = forms.ChoiceField(label="Tipo", choices=Comprovante.Kind.choices)
    file = forms.FileField(
        label="Substituir arquivo (opcional — máx. 2 MB)", required=False
    )
    warranty_expiry = forms.DateField(
        label="Expiração da garantia",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    notes = forms.CharField(
        label="Observações", required=False, max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean_file(self):
        data = self.cleaned_data.get("file")
        if data is None:
            return data
        try:
            _validate_upload(data)
        except UploadError as exc:
            raise forms.ValidationError(str(exc))
        return data
