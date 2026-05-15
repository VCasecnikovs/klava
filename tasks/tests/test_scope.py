from tasks import scope as scope_module


def test_infer_scope_ignores_css_apple_system(monkeypatch):
    monkeypatch.setattr(
        scope_module,
        "load_scope_map",
        lambda: {"entity_to_scope": {"Apple": "Vox Lab/Deals/Apple/"}, "known_scopes": []},
    )
    monkeypatch.setattr(
        scope_module,
        "list_known_scopes",
        lambda: ["Vox Lab/Deals/Apple/"],
    )

    assert scope_module.infer_scope("font-family: -apple-system, BlinkMacSystemFont") is None
    assert scope_module.infer_scope("Apple due diligence prep") == "Vox Lab/Deals/Apple/"


def test_infer_scope_matches_known_scope_on_word_boundary(monkeypatch):
    monkeypatch.setattr(
        scope_module,
        "load_scope_map",
        lambda: {"entity_to_scope": {}, "known_scopes": []},
    )
    monkeypatch.setattr(
        scope_module,
        "list_known_scopes",
        lambda: ["Astrum/", "Vox Lab/Deals/Apple/"],
    )

    assert scope_module.infer_scope("Astrum user analytics") == "Astrum/"
    assert scope_module.infer_scope("font-family: -apple-system") is None


def test_view_scope_uses_visible_text_not_html_chrome(monkeypatch):
    monkeypatch.setattr(scope_module, "load_view_scope_overrides", lambda: {})
    monkeypatch.setattr(
        scope_module,
        "load_scope_map",
        lambda: {"entity_to_scope": {"Apple": "Vox Lab/Deals/Apple/", "META": "Vox Lab/Deals/META/"}, "known_scopes": []},
    )
    monkeypatch.setattr(
        scope_module,
        "list_known_scopes",
        lambda: ["Vox Lab/Deals/Apple/", "Vox Lab/Deals/META/", "Astrum/"],
    )

    html = """
    <html>
      <head>
        <meta charset="utf-8">
        <style>body { font-family: -apple-system, BlinkMacSystemFont; }</style>
        <title>Astrum user analytics</title>
      </head>
      <body>Top traders and referrals</body>
    </html>
    """

    assert scope_module.view_scope_for("report.html", html) == "Astrum/"
