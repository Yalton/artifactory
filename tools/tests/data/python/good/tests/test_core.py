from app.core import greeting


def test_greeting():
    assert greeting() == "hello, world"
