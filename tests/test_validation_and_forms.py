import pytest

from bingo import BingoValidationError
from bingo.forms import Form
from bingo.validation import Validator, rules


class SignupValidator(Validator):
    name = rules.String(required=True, min_length=3, max_length=20)
    age = rules.Integer(required=True, min=18, max=120)
    score = rules.Float(min=0, max=10)
    active = rules.Boolean(required=True)
    email = rules.Email(required=True)


def test_validator_raises_with_field_errors():
    validator = SignupValidator(
        {
            "name": "Al",
            "age": "17",
            "score": "eleven",
            "active": "maybe",
            "email": "bad",
        }
    )

    with pytest.raises(BingoValidationError) as raised:
        validator.validate()

    assert raised.value.validator is validator
    assert validator.cleaned_data == {}
    assert validator.errors == {
        "name": ["must be at least 3 characters"],
        "age": ["must be at least 18"],
        "score": ["must be a number"],
        "active": ["must be true or false"],
        "email": ["must be a valid email address"],
    }


def test_validator_returns_cleaned_data_and_supports_index_access():
    validator = SignupValidator(
        {
            "name": "Ada",
            "age": "37",
            "score": "9.5",
            "active": "on",
            "email": "ada@example.com",
        }
    )

    cleaned_data = validator.validate()

    assert cleaned_data["age"] == 37
    assert validator["age"] == 37
    assert validator.cleaned_data["active"] is True


def test_form_preserves_values_escapes_html_and_renders_errors():
    validator = SignupValidator({"name": '<script>alert("x")</script>'})
    with pytest.raises(BingoValidationError):
        validator.validate()
    form = Form(validator)

    rendered = str(form.input("name", class_="input"))
    assert 'class="input"' in rendered
    assert "&lt;script&gt;" in rendered
    assert form.value("name") == '<script>alert("x")</script>'
    assert "at most 20 characters" in str(form.error("name"))
    assert str(form.textarea("name")).startswith("<textarea")


class ArticleValidator(Validator):
    title = rules.String(required=True)
    body = rules.Text(required=True)
    published = rules.Boolean(required=True)
    published_on = rules.Date()


def test_form_is_iterable_and_selects_controls_from_rules():
    fields = list(Form(ArticleValidator({"published": False})))

    assert [field.name for field in fields] == [
        "title",
        "body",
        "published",
        "published_on",
    ]
    assert [field.type for field in fields] == [
        "text",
        "textarea",
        "checkbox",
        "date",
    ]
    assert fields[0].label == "Title"
    assert 'name="title"' in str(fields[0])
    assert str(fields[1]).startswith("<textarea")
    assert 'type="hidden" name="published" value="false"' in str(fields[2])
    assert "checked" not in str(fields[2])
