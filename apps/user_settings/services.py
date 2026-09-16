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

import copy
import json
from datetime import datetime, timezone
from typing import Any

from django.apps import apps
from django.db import transaction
from django.db import models
from django.db.models import ForeignKey


# --------------------------------------------------------------------------- #
# Inventário de modelos exportáveis
# --------------------------------------------------------------------------- #

# (app_label, model_name). A ordem respeita dependências FK (pais antes dos
# filhos), inclusive dependências "para trás" (ex.: transaction referencia
# recurringrule, transfer e installmentpurchase — que devem vir antes).
# ``owner`` é o nome típico do campo de propriedade; alguns modelos usam
# ``user`` ou são híbridos (merchant/alias — owner pode ser null=global).
# O campo de propriedade é detectado dinamicamente: preferimos ``owner``,
# depois ``user``; Merchant/MerchantAlias usam ``owner`` (null = global).
EXPORT_MODEL_ORDER = [
    # Conta e perfil primeiro (bases)
    ("accounts", "profile"),
    # Finance — bases
    ("finance", "account"),
    ("finance", "category"),
    ("finance", "merchant"),
    ("finance", "merchantalias"),
    ("finance", "userpreference"),
    # Cards — antes de transaction (transaction referencia card_purchase)
    ("cards", "creditcard"),
    ("cards", "creditcardinvoice"),
    ("cards", "installmentpurchase"),
    ("cards", "installment"),
    # Finance — referências cruzadas (transfer/rule antes de transaction)
    ("finance", "transfer"),
    ("finance", "recurringrule"),
    ("finance", "transaction"),
    ("finance", "classificationrule"),
    ("finance", "transactionanalysis"),
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

    FKs internas são remapeadas conforme a ordem de restauração. O restore é
    idempotente: registros idênticos aos já existentes do usuário são
    ignorados (contados como ``skipped``), nunca duplicados.
    """
    report: dict[str, int] = {"restored": 0, "skipped": 0, "errors": 0}

    if not isinstance(data, dict):
        raise ValueError("Formato de arquivo inválido. Esperado JSON.")

    # Nunca mutamos o dict original (o backup pode ser reutilizado em novos
    # restores após o primeiro — os FKs são reescritos no processo).
    data = copy.deepcopy(data)

    pk_map: dict[str, dict[int, int]] = {}
    # FKs que apontam para um modelo que só será restaurado depois (ex.:
    # transfer.out_transaction → transaction) são deferidas e preenchidas no fim.
    deferred: list[tuple] = []

    order_index = {
        f"{app_label}.{model_name}": idx
        for idx, (app_label, model_name) in enumerate(EXPORT_MODEL_ORDER)
    }

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

            for row in _order_rows(model, rows):
                old_pk = row.get("_pk")
                try:
                    defer = _defer_forward_fks(model, row, order_index)
                    _remap_fks(model, row, pk_map)
                    _cleanup_orphan_fks(model, row, pk_map)
                    obj = _create_row(user, model, row, owner_field, pk_map, key)
                except Exception:
                    report["errors"] += 1
                    continue
                if obj is None:
                    report["skipped"] += 1
                    continue
                if old_pk is not None:
                    pk_map.setdefault(key, {})[old_pk] = obj.pk
                for attname, target_key, old_target_id in defer:
                    deferred.append(
                        (model._meta.label_lower, obj.pk, attname, target_key, old_target_id)
                    )
                report["restored"] += 1

        # Preenche referências adiadas (pernas de transfer, pagamento de fatura).
        for source_key, obj_pk, attname, target_key, old_target_id in deferred:
            new_id = pk_map.get(target_key, {}).get(old_target_id)
            if new_id is None:
                continue
            try:
                source_model = apps.get_model(*source_key.split("."))
                source_model.objects.filter(pk=obj_pk).update(**{attname: new_id})
            except Exception:
                report["errors"] += 1

    return report


def _order_rows(model, rows: list) -> list:
    """Ordena linhas de um mesmo modelo para que FKs internas (self) existam
    antes dos registros que as referenciam (pais antes dos filhos)."""
    self_refs = [
        f.name
        for f in model._meta.get_fields()
        if isinstance(f, ForeignKey) and f.related_model is model
    ]
    if not self_refs:
        return list(rows)

    keyed = {r["_pk"]: r for r in rows if r.get("_pk") is not None}
    placed: set[int] = set()
    ordered: list = []
    remaining = list(rows)

    while remaining:
        progress = False
        for row in remaining:
            if any(
                row.get(ref) in keyed and row.get(ref) not in placed
                for ref in self_refs
            ):
                continue
            ordered.append(row)
            pk = row.get("_pk")
            if pk is not None:
                placed.add(pk)
            remaining.remove(row)
            progress = True
            break
        if not progress:  # ciclo ou referência órfã — não bloqueia o restore
            ordered.extend(remaining)
            break
    return ordered


def _defer_forward_fks(model, row: dict, order_index: dict) -> list:
    """Adia FKs para modelos que ainda não foram restaurados.

    Exemplo: ``transfer.out_transaction``/``in_transaction`` apontam para
    transactions (model restaurado depois) — o valor é zerado agora e
    preenchido no fim do restore, após o mapeamento das transactions.
    Retorna tuplas ``(attname, target_key, old_target_id)``.
    """
    deferred = []
    for field in model._meta.get_fields():
        if not isinstance(field, ForeignKey):
            continue
        if field.name not in row or row[field.name] is None:
            continue
        related = field.related_model
        if related is None or related is model:
            continue
        target_key = f"{related._meta.app_label}.{related._meta.model_name}"
        if order_index.get(target_key, -1) <= order_index.get(
            model._meta.label_lower, -1
        ):
            continue
        deferred.append((field.attname, target_key, row[field.name]))
        row[field.name] = None
    return deferred


def _remap_fks(model, row: dict, pk_map: dict):
    unchanged = True
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
            unchanged = False
    return unchanged


def _cleanup_orphan_fks(model, row: dict, pk_map: dict):
    """Zera FKs opcionais que referenciam registros inexistentes nesta base
    (ex.: categoria apontada por uma rule não veio no dump). Evita colisão com
    IDs órfãos de outros usuários e validações "do mesmo usuário" falsas."""
    for field in model._meta.get_fields():
        if not isinstance(field, ForeignKey):
            continue
        if field.null is False:
            continue
        if field.name not in row or row[field.name] is None:
            continue
        related = field.related_model
        if related is None:
            continue
        target_key = f"{related._meta.app_label}.{related._meta.model_name}"
        mapping = pk_map.get(target_key, {})
        if row[field.name] not in mapping.values():
            row[field.name] = None


def _create_row(user, model, row: dict, owner_field: str, pk_map: dict, key: str):
    """Cria um objeto, garantindo ownership correto e campos válidos.

    Retorna o objeto criado, ou ``None`` quando o registro já existe
    idêntico para o mesmo dono (duplicado — não sobrescreve).
    """
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

    # Idempotência: registros com a mesma chave única já existentes são
    # ignorados (e referências a eles passam a apontar para a cópia existente).
    old_pk = row.get("_pk")
    existing = _find_existing(model, user, clean)
    if existing is not None:
        if old_pk is not None:
            pk_map.setdefault(key, {})[old_pk] = existing.pk
        return None

    obj = model(**clean)
    obj.save()
    return obj


def _unique_keys_for(model):
    """Chaves de unicidade (sem o campo owner, aplicado implicitamente)."""
    keys = []
    keys.extend(list(ut) for ut in model._meta.unique_together)
    for const in getattr(model._meta, "constraints", []):
        if isinstance(const, models.UniqueConstraint):
            fields = list(const.expressions) if const.expressions else list(const.fields)
            if fields:
                keys.append([f for f in fields if isinstance(f, str)])
    return keys


def _find_existing(model, user, clean: dict):
    """Localiza registro idêntico do mesmo dono (pelas chaves únicas)."""
    keys = [k for k in _unique_keys_for(model) if k]
    if not keys:
        return None
    for key in keys:
        if "owner" in key:
            key = [f for f in key if f != "owner"]
        kwargs = {"owner": user}
        for field_name in key:
            field = model._meta.get_field(field_name)
            attname = field.attname if isinstance(field, ForeignKey) else field_name
            value = clean.get(attname)
            if value is None and field.null:
                kwargs[field_name] = None
            elif value is None:
                kwargs = None
                break
            else:
                kwargs[field_name] = value
        if kwargs is None:
            continue
        hit = model.objects.filter(**kwargs).first()
        if hit is not None:
            return hit
    return None


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
