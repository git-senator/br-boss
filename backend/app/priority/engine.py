"""Prioridade final do e-mail: a nota da IA mais as regras do usuário.

As regras mandam mais que a IA. A pessoa sabe sobre os próprios negócios o que
não está escrito no e-mail: que esse remetente é o advogado dela, que esse
projeto está pegando fogo agora. O sistema não deve brigar com ela.

Quando as regras se contradizem, «subir» vence «baixar». Mostrar um e-mail
a mais é um incômodo; esconder um importante é dinheiro perdido.
"""

from dataclasses import replace
from decimal import Decimal, InvalidOperation

from app.ai.triage import TriageResult
from app.models import Message, Rule

SENDER_CONTAINS = "sender_contains"
SUBJECT_CONTAINS = "subject_contains"
BODY_CONTAINS = "body_contains"
AMOUNT_OVER = "amount_over"
CATEGORY_IS = "category_is"

SET_MIN_PRIORITY = "set_min_priority"
SET_MAX_PRIORITY = "set_max_priority"
SET_CATEGORY = "set_category"

CONDITION_KINDS = (SENDER_CONTAINS, SUBJECT_CONTAINS, BODY_CONTAINS, AMOUNT_OVER, CATEGORY_IS)
ACTION_KINDS = (SET_MIN_PRIORITY, SET_MAX_PRIORITY, SET_CATEGORY)


def _contains(needle: str, haystack: str) -> bool:
    return needle.strip().lower() in (haystack or "").lower()


def matches(rule: Rule, triage: TriageResult, message: Message) -> bool:
    if rule.condition_kind == SENDER_CONTAINS:
        return _contains(rule.condition_value, f"{message.sender} {message.sender_name}")
    if rule.condition_kind == SUBJECT_CONTAINS:
        return _contains(rule.condition_value, message.subject)
    if rule.condition_kind == BODY_CONTAINS:
        return _contains(rule.condition_value, f"{message.subject}\n{message.body_text}")
    if rule.condition_kind == AMOUNT_OVER:
        if triage.amount is None:
            return False
        try:
            return triage.amount > Decimal(rule.condition_value)
        except InvalidOperation:
            return False
    if rule.condition_kind == CATEGORY_IS:
        return triage.category == rule.condition_value
    # condição desconhecida: a regra simplesmente não dispara, em vez de derrubar a triagem
    return False


def apply_rules(triage: TriageResult, message: Message, rules: list[Rule]) -> TriageResult:
    floor: int | None = None
    ceiling: int | None = None
    category = triage.category

    for rule in rules:
        if not rule.is_active or not matches(rule, triage, message):
            continue
        if rule.action_kind == SET_MIN_PRIORITY:
            value = int(rule.action_value)
            floor = value if floor is None else max(floor, value)
        elif rule.action_kind == SET_MAX_PRIORITY:
            value = int(rule.action_value)
            ceiling = value if ceiling is None else min(ceiling, value)
        elif rule.action_kind == SET_CATEGORY:
            category = rule.action_value

    priority = triage.priority
    if ceiling is not None:
        priority = min(priority, ceiling)
    if floor is not None:
        # de propósito depois do teto: «nunca esconder» vence «esconder»
        priority = max(priority, floor)

    return replace(triage, priority=priority, category=category)
