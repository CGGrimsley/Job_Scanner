from job_scanner import ai, places, profile, scoring


def test_old_single_resume_becomes_a_list():
    p = profile.clean({"resume": "Analyst at Acme"})
    assert p["resumes"] == [{"name": "Main résumé", "text": "Analyst at Acme"}]


def test_several_resumes_all_reach_claude():
    p = profile.clean({"resumes": [{"name": "Data", "text": "SQL at Acme"}, {"name": "Data", "text": "Epic at WakeMed"},
                                   {"name": "Blank", "text": "  "}, "junk"]})
    assert [r["name"] for r in p["resumes"]] == ["Data", "Data (2)"]  # empty dropped, names kept apart
    text = profile.for_prompt(p)
    assert "SQL at Acme" in text and "Epic at WakeMed" in text and "same person" in text
    assert not profile.is_empty(p)


def test_place_search():
    assert places.search("Rale")[0] == "Raleigh, NC"
    assert places.search("north car")[0] == "North Carolina"
    assert "Durham, NC" in places.search("dur")
    assert places.search("x") == []


def test_a_state_covers_its_cities():
    assert scoring._place_match("Wilson, NC", ["North Carolina"])
    assert scoring._place_match("Remote in North Carolina", ["North Carolina"])
    assert not scoring._place_match("Austin, TX", ["North Carolina"])
    assert scoring._place_match("Raleigh, NC 27601", ["Raleigh, NC"])


def test_cover_letter_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai, "ask_json", lambda system, prompt, *a, **k: seen.update(prompt=prompt) or {"letter": " Dear [Hiring Manager] "})
    out = ai.cover_letter({"title": "Analyst"}, "Résumé...", resume_name="Data", tone="concise")
    assert out == "Dear [Hiring Manager]"
    assert 'résumé named "Data"' in seen["prompt"] and "under 180 words" in seen["prompt"]
    assert "never claim" in seen["prompt"]


def test_locations_keep_their_commas():
    assert profile.clean({"locations": "Raleigh, NC\nNorth Carolina"})["locations"] == ["Raleigh, NC", "North Carolina"]
    assert profile.clean({"locations": ["Durham, NC"]})["locations"] == ["Durham, NC"]
