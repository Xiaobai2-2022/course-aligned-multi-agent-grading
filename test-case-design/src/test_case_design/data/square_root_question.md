# Square Root Function

Write a C++ function that uses **Newton’s method** to approximate the square root of a nonnegative number.

Your function must have the following signature:

```cpp
double square_root(double n, double s, double e);
```

The parameters are:

- `n`: the number whose square root is required, where $n \ge 0$.
- `s`: the starting guess, where $s > 0$.
- `e`: the stopping tolerance, where $e > 0$.

## Parameter validation

All three parameters must be finite numeric values satisfying their stated constraints. NaN and positive or negative infinity are invalid.

If any parameter is invalid, display an error message and return `-1.0` without performing any Newton updates. The wording of the error message is not prescribed.

Validate **all three parameters before handling $n = 0$**.

## Calculation

- If the parameters are valid and $n = 0$, return `0.0` without performing any Newton updates.
- Otherwise, initialize $x_0 = s$ and repeatedly calculate:

$$x_{k+1} = \frac{1}{2}\left(x_k + \frac{n}{x_k}\right).$$

Stop at the **first update** satisfying:

$$|x_{k+1} - x_k| \le e.$$

Return the **new approximation**, $x_{k+1}$, rather than the previous value, $x_k$.

The tolerance $e$ applies to the difference between consecutive approximations. Do not replace this condition with a different stopping criterion.

## Restrictions

1. You may include only `<iostream>`, `<iomanip>`, `<cmath>`, and `<cassert>`.
2. You must implement Newton’s method yourself.
3. You must not use `std::sqrt` or another library operation to compute the square root in place of Newton’s method.
4. The function must not read input or display successful results. Values are supplied through its parameters, and the approximation is returned to the caller.
5. Submit only the function and any permitted include directives; do not submit a `main` function, any main function will be removed.
