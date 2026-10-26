---
title: Throwing Exceptions
concept: exception-throwing
module: Exception Handling
tags: exception-throwing, checked-vs-unchecked
---

# Throwing Exceptions

`throw` raises an exception object at the point where the problem is detected. `throws` in a method
signature declares that the method may propagate one to its caller. They are different keywords with
different jobs.

When an exception is thrown, execution of the current method stops immediately and the JVM unwinds
the stack looking for a matching catch. If none is found anywhere, the thread terminates and the
stack trace is printed.

Throw early, at the point the problem is detectable, and include a message that says what was wrong
and what was expected. `throw new IllegalArgumentException("Age was -5, must be 0 or more")` is far
more useful than a bare exception.

```java
public class Account {
    private double balance;

    public void withdraw(double amount) {            // unchecked - caller need not declare
        if (amount <= 0) {
            throw new IllegalArgumentException("Amount must be positive, got " + amount);
        }
        if (amount > balance) {
            throw new IllegalStateException("Balance is " + balance + ", requested " + amount);
        }
        balance -= amount;
    }

    public void save(String path) throws IOException {   // checked - must be declared
        Files.writeString(Path.of(path), String.valueOf(balance));
    }
}
```

## Key points
- `throw` raises an exception; `throws` declares that one may escape.
- Throwing stops the method immediately and unwinds the stack.
- Detect and throw as early as the problem is visible.
- Messages should state what was wrong and what was expected.

## Common mistake
Confusing the two keywords. `throws` in a method body, or `throw` in a signature, will not compile.
