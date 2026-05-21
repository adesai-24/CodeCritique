# Test fixture: deliberately clean code that should produce zero findings.
# Used to verify that checkers don't invent issues on valid, well-structured code.


def add(a: int, b: int) -> int:
    return a + b


def greet(name: str) -> str:
    return f"Hello, {name}!"


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def is_even(n: int) -> bool:
    return n % 2 == 0
