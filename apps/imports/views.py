"""Views da camada de importação.

Fluxo: upload -> ingest (staging) -> revisão -> confirmação.
Nenhuma regra financeira vive aqui: upload chama ``ingest`` (cria staging) e a
confirmação chama ``commit_batch`` (cria os registros reais via services).
Ownership é garantido filtrando tudo por ``for_user(request.user)``.
"""

from collections import Counter

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.finance.models import Account, Category

from .forms import ImportUploadForm
from .models import ImportBatch, StagedTransaction
from .services import importer as importer_svc
from .services.commit import commit_batch


class ImportUploadView(LoginRequiredMixin, FormView):
    template_name = "imports/upload.html"
    form_class = ImportUploadForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Importar dados"
        return ctx

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        f = form.cleaned_data["file"]
        account = form.cleaned_data.get("account")
        card = form.cleaned_data.get("card")
        import_type = form.cleaned_data.get("import_type") or "account"
        file_type = form.file_type()
        try:
            raw = f.read()
            batch = importer_svc.ingest(
                user=user,
                file_type=file_type,
                file_name=f.name,
                content=raw,
                default_account=account,
                card=card,
                import_type=import_type,
            )
        except ValueError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        except Exception as exc:  # pragma: no cover
            messages.error(self.request, f"Não foi possível processar o arquivo: {exc}")
            return self.form_invalid(form)

        if import_type == ImportUploadForm.IMPORT_TYPE_CARD and card is not None:
            messages.success(
                self.request,
                "Fatura importada e compras criadas no cartão. "
                "O pagamento é lançado quando você pagar a fatura no extrato da conta.",
            )
            return redirect(reverse("imports:result", args=[batch.pk]))

        messages.success(self.request, "Arquivo importado. Revise antes de confirmar.")
        return redirect(reverse("imports:review", args=[batch.pk]))


class ImportReviewView(LoginRequiredMixin, View):
    """Tela de revisão + confirmação do lote."""

    template_name = "imports/review.html"

    def _get_batch(self, request, pk) -> ImportBatch:
        return get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)

    def get(self, request, pk):
        batch = self._get_batch(request, pk)
        context = self._build_context(request, batch)
        return _render(request, self.template_name, context)

    def post(self, request, pk):
        batch = self._get_batch(request, pk)
        if batch.status not in (ImportBatch.Status.READY, ImportBatch.Status.COMMITTED):
            messages.warning(request, "Este lote não está mais disponível para confirmação.")
            return redirect(reverse("imports:review", args=[pk]))

        action = request.POST.get("action")
        if action == "discard":
            batch.status = ImportBatch.Status.DISCARDED
            batch.save(update_fields=["status"])
            messages.success(request, "Importação descartada. Nada foi criado.")
            return redirect(reverse("dashboard:index"))

        if action == "confirm":
            return self._do_confirm(request, batch)

        messages.warning(request, "Ação inválida.")
        return redirect(reverse("imports:review", args=[pk]))

    def _do_confirm(self, request, batch):
        user = request.user
        account_pk = request.POST.get("account") or ""
        account = None
        if account_pk:
            account = Account.objects.for_user(user).filter(pk=account_pk).first()

        # lê decisões por linha: categoria e incluir/excluir
        categories = {}
        excluded = set()
        for staged in batch.staged_rows.all():
            cat_pk = request.POST.get(f"cat_{staged.pk}")
            if cat_pk:
                cat = Category.objects.for_user(user).filter(pk=cat_pk).first()
                if cat:
                    categories[str(staged.pk)] = cat.name
            # linha duplicada vem com 'excl_'; linha normal vem com 'incl_'.
            # Fica EXCLUÍDA se marcado excl_ OU se não marcado incl_.
            if request.POST.get(f"excl_{staged.pk}"):
                excluded.add(staged.pk)
            elif not request.POST.get(f"incl_{staged.pk}"):
                excluded.add(staged.pk)

        # marca linhas excluídas como ignoradas (decisão do usuário)
        if excluded:
            StagedTransaction.objects.filter(pk__in=excluded).update(
                row_status=StagedTransaction.RowStatus.IGNORED,
                skip_reason="Excluída pelo usuário na revisão.",
            )

        result = commit_batch(user=user, batch=batch, account=account, categories=categories)
        messages.success(
            request,
            f"Importação concluída: {result.imported} importadas, "
            f"{result.pending} pendentes, {result.ignored} ignoradas, {result.errors} com erro.",
        )
        return redirect(reverse("imports:result", args=[batch.pk]))

    def _build_context(self, request, batch):
        user = request.user
        rows = list(batch.staged_rows.select_related("category", "default_account", "merchant"))
        counts = Counter(
            StagedTransaction.Confidence(r.confidence) for r in rows
        )
        accounts = Account.objects.for_user(user).filter(status=Account.Status.ACTIVE)
        categories = Category.objects.for_user(user).filter(status=Category.Status.ACTIVE)

        # formatação para o template (sem depender do centavos tag default)
        for r in rows:
            r.display_value = _reais(r.amount_cents)

        return {
            "batch": batch,
            "rows": rows,
            "accounts": accounts,
            "categories": categories,
            "n_high": counts.get("high", 0),
            "n_review": counts.get("review", 0),
            "n_dup": counts.get("duplicate", 0),
            "default_account": request.POST.get("account") or "",
            "reais": _reais,
        }


class ImportResultView(LoginRequiredMixin, TemplateView):
    template_name = "imports/result.html"

    def get(self, request, pk):
        batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
        return _render(request, self.template_name, {"batch": batch, "reais": _reais})


def _render(request, template, context):
    from django.shortcuts import render
    return render(request, template, context)


def _reais(cents: int) -> str:
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}R$ {cents // 100:,}.{cents % 100:02d}".replace(",", ".")
