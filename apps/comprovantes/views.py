"""Views do app comprovantes (organizador de comprovantes e garantias)."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, reverse
from django.views import View
from django.views.generic import FormView, TemplateView
from django.views.generic.detail import SingleObjectMixin

from apps.core.services.ai import AIServiceError

from .forms import ComprovanteCreateForm, ComprovanteEditForm
from .models import Comprovante
from .services import (
    UploadError,
    create_comprovante,
    delete_comprovante,
    get_comprovantes,
    parse_comprovante_with_ai,
    update_details,
    warranty_alert_count,
)


class _OwnedComprovanteMixin(SingleObjectMixin):
    model = Comprovante
    permission_denied_message = "Recurso não encontrado."

    def get_object(self, queryset=None):
        return get_object_or_404(
            Comprovante.objects.for_user(self.request.user),
            pk=self.kwargs.get("pk"),
        )


class ComprovanteListView(LoginRequiredMixin, TemplateView):
    template_name = "comprovantes/comprovante_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        kind = self.request.GET.get("kind") or None
        warranty = self.request.GET.get("warranty") or None
        ctx["items"] = get_comprovantes(user=user, kind=kind, warranty=warranty)
        ctx["kinds"] = Comprovante.Kind.choices
        ctx["selected_kind"] = kind
        ctx["selected_warranty"] = warranty
        ctx["warranty_alert_count"] = warranty_alert_count(user=user)
        return ctx


class ComprovanteCreateView(LoginRequiredMixin, FormView):
    template_name = "comprovantes/comprovante_form.html"
    form_class = ComprovanteCreateForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["is_edit"] = False
        return ctx

    def form_valid(self, form):
        create_comprovante(
            user=self.request.user,
            title=form.cleaned_data["title"],
            kind=form.cleaned_data["kind"],
            uploaded=form.cleaned_data["file"],
            warranty_expiry=form.cleaned_data.get("warranty_expiry"),
            notes=form.cleaned_data.get("notes", ""),
        )
        messages.success(self.request, "Comprovante adicionado.")
        return redirect(reverse("comprovantes:list"))


class ComprovanteEditView(LoginRequiredMixin, _OwnedComprovanteMixin, FormView):
    template_name = "comprovantes/comprovante_form.html"
    form_class = ComprovanteEditForm

    def get_context_data(self, **kwargs):
        comprovante = self.get_object()
        ctx = super().get_context_data(**kwargs)
        ctx["is_edit"] = True
        ctx["comprovante"] = comprovante
        return ctx

    def get_initial(self):
        c = self.get_object()
        return {
            "title": c.title,
            "kind": c.kind,
            "warranty_expiry": c.warranty_expiry,
            "notes": c.notes,
        }

    def form_valid(self, form):
        comprovante = self.get_object()
        uploaded = form.cleaned_data.get("file")
        if uploaded:
            if comprovante.file:
                comprovante.file.delete(save=False)
            comprovante.file = uploaded
            comprovante.save()
        update_details(
            user=self.request.user,
            comprovante=comprovante,
            title=form.cleaned_data["title"],
            kind=form.cleaned_data["kind"],
            warranty_expiry=form.cleaned_data.get("warranty_expiry"),
            notes=form.cleaned_data.get("notes", ""),
        )
        messages.success(self.request, "Comprovante atualizado.")
        return redirect(reverse("comprovantes:list"))


class ComprovanteDeleteView(LoginRequiredMixin, _OwnedComprovanteMixin, View):
    def post(self, request, *args, **kwargs):
        comprovante = self.get_object()
        delete_comprovante(user=request.user, comprovante=comprovante)
        messages.success(request, "Comprovante removido.")
        return redirect(reverse("comprovantes:list"))


class ComprovanteDownloadView(LoginRequiredMixin, _OwnedComprovanteMixin, View):
    def get(self, request, *args, **kwargs):
        comprovante = self.get_object()
        if not comprovante.file:
            raise Http404
        return FileResponse(comprovante.file.open("rb"), as_attachment=True)


class ComprovanteParseAIView(LoginRequiredMixin, View):
    """Pré-preenche o formulário com dados lidos por IA (sem salvar nada).

    Endpoint JSON usado pelo botão "Preencher com IA". Em caso de IA
    indisponível, devolve ``ok: False`` com mensagem amigável — o usuário
    preenche manualmente (fallback gracioso, nunca quebra o fluxo).
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return JsonResponse(
                {"ok": False, "message": "Selecione um arquivo para analisar."},
                status=400,
            )
        try:
            data = parse_comprovante_with_ai(
                user=request.user, comprovante_id_or_file=uploaded
            )
        except UploadError as exc:
            return JsonResponse(
                {"ok": False, "message": str(exc)}, status=400
            )
        except AIServiceError:
            return JsonResponse(
                {
                    "ok": False,
                    "message": (
                        "IA de leitura indisponível agora (sem chave configurada "
                        "ou sem conexão). Preencha manualmente."
                    ),
                },
                status=200,
            )
        return JsonResponse(data)
