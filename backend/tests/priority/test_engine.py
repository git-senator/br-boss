from decimal import Decimal

from app.ai.triage import TriageResult
from app.models import Message, Rule
from app.priority.engine import apply_rules


def triage(priority: int = 40, category: str = "business", amount=None) -> TriageResult:
    return TriageResult(category=category, priority=priority, summary="resumo", amount=amount)


def letter(sender="joao@uol.com.br", subject="Assunto", body="Texto", name="") -> Message:
    return Message(sender=sender, sender_name=name, subject=subject, body_text=body)


def rule(condition_kind, condition_value, action_kind, action_value, is_active=True) -> Rule:
    return Rule(
        condition_kind=condition_kind,
        condition_value=condition_value,
        action_kind=action_kind,
        action_value=action_value,
        is_active=is_active,
    )


# --- exemplos tirados direto da especificação ---


def test_everything_from_lawyers_is_important():
    rules = [rule("sender_contains", "advogado", "set_min_priority", "85")]
    result = apply_rules(triage(), letter(sender="silva@advogado.com.br"), rules)
    assert result.priority == 85


def test_invoice_over_50k_gets_priority_90():
    rules = [rule("amount_over", "50000", "set_min_priority", "90")]
    result = apply_rules(triage(amount=Decimal("56315")), letter(), rules)
    assert result.priority == 90


def test_invoice_under_the_threshold_is_untouched():
    rules = [rule("amount_over", "50000", "set_min_priority", "90")]
    result = apply_rules(triage(amount=Decimal("1200")), letter(), rules)
    assert result.priority == 40


def test_real_estate_ads_are_pushed_down():
    rules = [rule("subject_contains", "imóveis", "set_max_priority", "10")]
    result = apply_rules(triage(priority=55), letter(subject="Imóveis de alto padrão"), rules)
    assert result.priority == 10


def test_project_mentions_change_category():
    rules = [rule("body_contains", "TitanYield", "set_category", "business")]
    result = apply_rules(
        triage(category="low"), letter(body="sobre o projeto TitanYield, preciso de resposta"), rules
    )
    assert result.category == "business"


def test_court_letters_are_never_hidden():
    rules = [
        rule("subject_contains", "newsletter", "set_max_priority", "5"),
        rule("body_contains", "tribunal", "set_min_priority", "95"),
    ]
    result = apply_rules(
        triage(priority=30), letter(subject="newsletter", body="decisão do tribunal"), rules
    )
    assert result.priority == 95, "subir vale mais que esconder"


# --- comportamento do motor ---


def test_rule_never_lowers_what_ai_rated_higher():
    rules = [rule("sender_contains", "advogado", "set_min_priority", "60")]
    result = apply_rules(triage(priority=95), letter(sender="a@advogado.com"), rules)
    assert result.priority == 95


def test_strongest_floor_wins():
    rules = [
        rule("sender_contains", "banco", "set_min_priority", "70"),
        rule("sender_contains", "inter", "set_min_priority", "90"),
    ]
    result = apply_rules(triage(), letter(sender="aviso@bancointer.com.br"), rules)
    assert result.priority == 90


def test_inactive_rule_is_ignored():
    rules = [rule("sender_contains", "advogado", "set_min_priority", "90", is_active=False)]
    assert apply_rules(triage(), letter(sender="a@advogado.com"), rules).priority == 40


def test_no_rules_changes_nothing():
    before = triage(priority=63, category="banks")
    after = apply_rules(before, letter(), [])
    assert after.priority == 63
    assert after.category == "banks"


def test_sender_name_is_searched_too():
    rules = [rule("sender_contains", "advogada", "set_min_priority", "90")]
    result = apply_rules(
        triage(), letter(sender="s@escritorio.com.br", name="Advogada Silva"), rules
    )
    assert result.priority == 90


def test_search_ignores_case():
    rules = [rule("subject_contains", "BOLETO", "set_min_priority", "80")]
    assert apply_rules(triage(), letter(subject="Segue boleto"), rules).priority == 80


def test_unknown_condition_does_not_break_processing():
    rules = [rule("phase_of_the_moon", "lua cheia", "set_min_priority", "99")]
    assert apply_rules(triage(), letter(), rules).priority == 40


def test_broken_amount_in_rule_does_not_break_processing():
    rules = [rule("amount_over", "cinquenta mil", "set_min_priority", "90")]
    assert apply_rules(triage(amount=Decimal("60000")), letter(), rules).priority == 40


def test_original_result_is_not_mutated():
    before = triage(priority=40)
    apply_rules(
        before,
        letter(sender="a@advogado.com"),
        [rule("sender_contains", "advogado", "set_min_priority", "90")],
    )
    assert before.priority == 40
