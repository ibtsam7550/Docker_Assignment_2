import math


def solve(a, b, c):
    if a == 0:
        raise ValueError('a must be nonzero')
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return discriminant, 'No real solutions', []
    if discriminant == 0:
        return discriminant, 'One real solution', [-b / (2 * a)]
    root = math.sqrt(discriminant)
    return discriminant, 'Two real solutions', [(-b + root) / (2 * a), (-b - root) / (2 * a)]
