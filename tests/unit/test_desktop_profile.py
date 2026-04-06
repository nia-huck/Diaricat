from __future__ import annotations

from diaricat.desktop import _make_splash_html


def test_make_splash_html_without_logo_uses_fallback() -> None:
    html = _make_splash_html(None)

    assert "Diaricat" in html
    assert "logo-fallback" in html


def test_make_splash_html_with_logo_embeds_data_uri() -> None:
    html = _make_splash_html("data:image/png;base64,AAAA")

    assert "data:image/png;base64,AAAA" in html
    assert 'alt="Diaricat"' in html
