---
title: Custom Exceptions
concept: custom-exceptions
module: Exception Handling
tags: custom-exceptions, exception-throwing, inheritance-basics
---

# Custom Exceptions

A custom exception is a class extending `Exception` (checked) or `RuntimeException` (unchecked). It
exists to give a failure a name that means something in your domain.

`catch (InsufficientFundsException e)` is self-documenting and can be handled differently from every
other failure. `catch (Exception e)` followed by inspecting the message string is not.

Provide the standard constructors - message, and message plus cause - so callers can chain. Name the
class after the condition, ending in `Exception`. Make it unchecked unless the caller can genuinely
do something about it. Do not create one per method; create one per genuinely distinct condition.

```java
public class InsufficientFundsException extends RuntimeException {
    private final double shortfall;

    public InsufficientFundsException(double shortfall) {
        super("Short by " + shortfall);
        this.shortfall = shortfall;
    }

    public InsufficientFundsException(String message, Throwable cause) {
        super(message, cause);                  // supports chaining
    }

    public double getShortfall() { return shortfall; }   // structured detail
}

try {
    account.withdraw(500);
} catch (InsufficientFundsException e) {
    System.out.println("Top up " + e.getShortfall());    // handled precisely
}
```

## Key points
- Extend Exception for checked, RuntimeException for unchecked.
- Name it after the condition and end it in Exception.
- Provide message and message-plus-cause constructors.
- Carry structured detail as fields rather than only in the message text.

## Common mistake
Creating a separate exception class for every method. A handful of meaningful domain conditions is far more useful than fifty near-identical classes.
