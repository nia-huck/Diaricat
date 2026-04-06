from __future__ import annotations

from diaricat.services.postprocess_service import LocalPostprocessService


def test_correction_guardrail_blocks_aggressive_rewrite(temp_settings) -> None:
    service = LocalPostprocessService(temp_settings)
    service._generate = lambda prompt, max_tokens=300: "invented story with unrelated claims"  # type: ignore[method-assign]

    original = "Hola esto es una transcripcion de prueba"
    corrected = service.correct(original)

    assert corrected == original


def test_fallback_summary_shape(temp_settings) -> None:
    service = LocalPostprocessService(temp_settings)
    service._generate = lambda prompt, max_tokens=300: None  # type: ignore[method-assign]

    summary = service.summarize("Se decidio avanzar con el plan. Accion siguiente: enviar propuesta.")

    assert isinstance(summary.overview, str)
    assert isinstance(summary.key_points, list)
    assert isinstance(summary.decisions, list)
    assert isinstance(summary.topics, list)


def test_rule_based_correction_fixes_known_asr_spanish_patterns(temp_settings) -> None:
    service = LocalPostprocessService(temp_settings)
    service._generate = lambda prompt, max_tokens=300: None  # type: ignore[method-assign]

    first = service.correct("porque yo por aca ya tenia tu todo.")
    second = service.correct(
        "pero vos queres tener las cartas documentos enviadas antes de la reunion del viernes o que te separar."
    )

    assert first == "porque yo por aca ya tenia todo."
    assert "o queres esperar" in second.lower()
    assert "cartas documento" in second.lower()


def test_fallback_summary_filters_low_value_phatic_sentences(temp_settings) -> None:
    service = LocalPostprocessService(temp_settings)
    service._generate = lambda prompt, max_tokens=300: None  # type: ignore[method-assign]

    text = (
        "Se escucha? Ahi esta. Como estas? "
        "Vos queres tener las cartas documentos enviadas antes de la reunion del viernes o queres esperar. "
        "La empresa puede despedirte el viernes."
    )
    summary = service.summarize(text)

    joined_points = " ".join(summary.key_points).lower()
    assert "se escucha" not in joined_points
    assert any("reunion del viernes" in topic.lower() for topic in summary.topics)
    assert len(summary.decisions) >= 1
