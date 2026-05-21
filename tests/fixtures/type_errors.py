# Test fixture: intentional type errors that Mypy should flag.
# Used to validate that MypyChecker catches type annotation violations.


def double(x: int) -> int:
    return x * 2


# Passing a string where int is expected.
result: int = double("hello")  # type: ignore[arg-type]  # intentional


def first_element(items: list[int]) -> int:
    return items[0]


# Wrong return annotation — function returns str, declared int.
def get_label() -> int:
    return "label"  # type: ignore[return-value]  # intentional
