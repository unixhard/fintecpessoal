"""Serviço de backup/export e restore/import de dados do usuário.

Serializa toda a base de dados do usuário como JSON estruturado.
Permite:
  - Export: dump completo em JSON para download
  - Restore: importa JSON (criando objetos novos, NÃO sobrescreve existentes)
  - Wipe: apaga todos os dados financeiros do usuário (mantém conta)

Cada registro é serializado como dict com ``_app``, ``_model`` e os valores
dos campos. Relações FK são mantidas como IDs inteiros (remapeados no restore,
baseado na ordem de exportação).

Restrições do Render free tier:
  - Sem background workers — tudo é síncrono na request.
  - Arquivos (comprovantes) NÃO são serializados (apenas metadata).
"""

import json
from datetime import datetime, timezone
from typing import Any

from django.apps import apps
from django.db import transaction
from django.db.models import ForeignKey


# --------------------------------------------------------------------------- #
# Inventário de modelos exportáveis
# --------------------------------------------------------------------------- #

# (app_label, model_name). A ordem respeita dependências FK (pais antes dos
# filhos). ``owner`` é o nome típico do campo de propriedade; alguns modelos
# usam ``user`` ou são híbridos (merchant/alias — owner pode ser null=global).
# O campo de propriedade é detectado dinamicamente: preferimos ``owner``,
# depois ``user``; Merchant/MerchantAlias usam ``owner`` (null = global).
EXPORT_MODEL_ORDER = [
    # Conta e perfil primeiro (bases)
    ("accounts", "profile"),
    # Finance
    ("finance", "account"),
    ("finance", "category"),
    ("finance", "merchant"),
    ("finance", "merchantalias"),
    ("finance", "transfer"),
    ("finance", "transaction"),
    ("finance", "recurringrule"),
    ("finance", "classificationrule"),
    ("finance", "userpreference"),
    ("finance", "transactionanalysis"),
    # Cards
    ("cards", "creditcard"),
    ("cards", "creditcardinvoice"),
    ("cards", "installmentpurchase"),
    ("cards", "installment"),
    # Budgets / Goals / Debts
    ("budgets", "budget"),
    ("goals", "goal"),
    ("debts", "debt"),
    # Net worth / Reports
    ("networth", "networthsnapshot"),
    ("reports", "aireport"),
    # Imports
    ("imports", "importbatch"),
    ("imports", "stagedtransaction"),
    # Comprovantes (metadata apenas)
    ("comprovantes", "comprovante"),
]

# Campos a IGNORAR na serialização (autos, segredos, arquivos)
SKIP_FIELDS = {
    "_state", "id", "created_at", "updated_at",
    "password", "last_login", "is_superuser", "is_staff",
    "user_permissions", "groups", "date_joined",
    "file", "doc_file", "attachment",  # arquivos — só metadata
}


def _owner_field(model):
    """Nome do campo que identifica o dono do registro.

    Prefere ``owner``; se não existir, usa ``user``; senão ``None``.
    """
    for name in ("owner", "user"):
        try:
            model._meta.get_field(name)
            return name
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #

def export_user_data(user) -> dict:
    """Serializa todos os dados do usuário como JSON estruturado."""
    data: dict[str, Any] = {
        "_meta": {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "username": user.username,
            "email": user.email,
        }
    }
    data["_user"] = {
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
    }

    for app_label, model_name in EXPORT_MODEL_ORDER:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        owner_field = _owner_field(model)
        if owner_field is None:
            continue
        qs = model.objects.filter(**{f"{owner_field}": user})
        rows = [_serialize_object(obj) for obj in qs]
        # Re-inclui o owner_field para contexto (será re-mapeado no restore)
        if rows:
            data[f"{app_label}.{model_name}"] = rows
    return data


def _serialize_object(obj) -> dict:
    row = {}
    seen = set()
    for field in obj._meta.get_fields():
        name = field.name
        if name in SKIP_FIELDS or name in seen:
            continue

        # Para FK, usamos o valor da coluna (attname: '<campo>_id') que é um int.
        if isinstance(field, ForeignKey):
            value = getattr(obj, field.attname, None)
            row[name] = value
            seen.add(name)
            continue

        try:
            value = getattr(obj, name)
        except Exception:
            continue

        if value is None:
            row[name] = None
        elif isinstance(value, (int, float, bool)):
            row[name] = value
        elif hasattr(value, "isoformat"):
            row[name] = value.isoformat()
        else:
            row[name] = str(value)
        seen.add(name)

    row["_pk"] = obj.pk
    return row


# --------------------------------------------------------------------------- #
# Restore
# --------------------------------------------------------------------------- #

def restore_user_data(user, data: dict) -> dict:
    """Restaura dados a partir de um dump JSON (cria objetos novos).

    FKs internas são remapeadas conforme a ordem de restauração.
    """
    report: dict[str, int] = {"restored": 0, "skipped": 0, "errors": 0}

    if not isinstance(data, dict):
        raise ValueError("Formato de arquivo inválido. Esperado JSON.")

    pk_map: dict[str, dict[int, int]] = {}

    with transaction.atomic():
        for app_label, model_name in EXPORT_MODEL_ORDER:
            key = f"{app_label}.{model_name}"
            rows = data.get(key, [])
            if not rows:
                continue

            try:
                model = apps.get_model(app_label, model_name)
            except LookupError:
                report["skipped"] += len(rows)
                continue

            owner_field = _owner_field(model)
            if owner_field is None:
                report["skipped"] += len(rows)
                continue

            for row in rows:
                try:
                    old_pk = row.get("_pk")
                    _remap_fks(model, row, pk_map)
                    obj = _create_row(user, model, row, owner_field)
                    if obj is not None:
                        if old_pk is not None:
                            pk_map.setdefault(key, {})[old_pk] = obj.pk
                        report["restored"] += 1
                    else:
                        report["skipped"] += 1
                except Exception:
                    report["errors"] += 1

    return report


def _create_row(user, model, row: dict, owner_field: str):
    """Cria um objeto, garantindo ownership correto e campos válidos."""
    valid = {f.name for f in model._meta.get_fields() if hasattr(f, "attname")}
    clean = {}
    for k, v in row.items():
        if k == "_pk":
            continue
        if k == owner_field:
            continue  # será definido abaixo
        if hasattr(model, k) and isinstance(model._meta.get_field(k), ForeignKey):
            # FKs são serializadas como int; atribuir via '<campo>_id'.
            attname = model._meta.get_field(k).attname
            clean[attname] = v
            continue
        if k not in valid:
            continue
        clean[k] = v

    app_label = model._meta.app_label
    model_name = model._meta.model_name

    # Profile é 1:1 com o usuário (já existe, criado por signal) — atualiza.
    if app_label == "accounts" and model_name == "profile":
        defaults = {k: v for k, v in clean.items() if k != "user"}
        # Conta padrão referencia FKs de outra base — não é restaurada.
        defaults.pop("default_account", None)
        defaults.pop("default_account_id", None)
        obj, _ = model.objects.update_or_create(user=user, defaults=defaults)
        return obj

    clean[owner_field] = user
    obj = model(**clean)
    obj.save()
    return obj


def _remap_fks(model, row: dict, pk_map: dict):
    for field in model._meta.get_fields():
        if not isinstance(field, ForeignKey):
            continue
        if field.name not in row or row[field.name] is None:
            continue
        related = field.related_model
        if related is None:
            continue
        target_key = f"{related._meta.app_label}.{related._meta.model_name}"
        old_id = row[field.name]
        new_id = pk_map.get(target_key, {}).get(old_id)
        if new_id is not None:
            row[field.name] = new_id


# --------------------------------------------------------------------------- #
# Wipe (apaga dados financeiros, mantém conta)
# --------------------------------------------------------------------------- #

def wipe_user_data(user) -> dict:
    report: dict[str, int] = {}
    with transaction.atomic():
        for app_label, model_name in reversed(EXPORT_MODEL_ORDER):
            try:
                model = apps.get_model(app_label, model_name)
            except LookupError:
                continue
            owner_field = _owner_field(model)
            if owner_field is None:
                continue
            count, _ = model.objects.filter(**{f"{owner_field}": user}).delete()
            if count:
                report[f"{app_label}.{model_name}"] = count
    return report


def delete_account(user) -> None:
    user.delete()
