# Test fixture: intentional logic bugs that static analysis tools miss.
# Used to validate that AICriticChecker catches semantic errors.


def find_max(numbers):
    """Return the index of the maximum value in the list."""
    max_val = numbers[0]
    max_idx = 0
    # Bug: range(len(numbers) - 1) skips the last element — off-by-one.
    for i in range(len(numbers) - 1):
        if numbers[i] > max_val:
            max_val = numbers[i]
            max_idx = i
    return max_idx


def is_palindrome(s):
    """Return True if s is a palindrome."""
    for i in range(len(s) // 2):
        # Bug: compares s[i] to itself — always False, never catches non-palindromes.
        if s[i] != s[i]:
            return False
    return True


def average(nums):
    """Compute the average of a list of numbers."""
    total = 0
    for n in nums:
        total += n
    # Bug: raises ZeroDivisionError when nums is empty — no guard.
    return total / len(nums)
