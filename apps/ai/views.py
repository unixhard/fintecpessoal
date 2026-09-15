from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services import ask


@login_required
@require_POST
def consult_cfo(request):
    """Endpoint do chat 'Pergunte ao CFO'. Resposta sempre JSON."""
    try:
        payload = request.POST
        message = (payload.get("message") or "").strip()
    except Exception:
        return JsonResponse({"ok": False, "error": "Requisição inválida."}, status=400)
    if not message:
        return JsonResponse({"ok": False, "error": "Digite sua pergunta."}, status=400)

    result = ask.answer(request.user, message)
    return JsonResponse(
        {
            "ok": True,
            "resposta": result["resposta"],
            "via_ia": result["via_ia"],
            "limite": result["limite"],
            "restantes": result["restantes"],
        }
    )