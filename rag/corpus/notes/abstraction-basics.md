---
title: What Abstraction Is
concept: abstraction-basics
module: Abstraction
tags: abstraction-basics, class-definition
---

# What Abstraction Is

Abstraction is deciding what to expose and what to leave out. The user of a type should see what it
does; how it does it is none of their business and should be free to change.

It is closely related to encapsulation but not the same. Encapsulation is the mechanism - private
fields, controlled access. Abstraction is the design decision about which concepts are worth naming
and what their surface should be.

The practical test is whether a caller can do their job knowing only the method names and their
contracts. A `PaymentProcessor` with `process(Payment)` is a good abstraction. One that forces the
caller to know whether it uses HTTP or a database is a leaky one.

```java
public interface PaymentProcessor {
    Receipt process(Payment payment);     // WHAT, with no hint of HOW
}

public class StripeProcessor implements PaymentProcessor {
    public Receipt process(Payment payment) {
        // HTTP calls, retries, signing - all invisible to the caller
        return new Receipt();
    }
}

public class CheckoutService {
    private final PaymentProcessor processor;     // depends on the abstraction

    public CheckoutService(PaymentProcessor processor) {
        this.processor = processor;               // any implementation fits
    }
}
```

## Key points
- Abstraction chooses what to expose; encapsulation enforces it.
- A good abstraction lets the caller work from names and contracts alone.
- Depending on an abstraction lets implementations be swapped freely.
- A leaky abstraction forces the caller to know the implementation.

## Common mistake
Putting implementation detail in the interface, such as a method named `getHttpClient()`, which locks every implementation into one approach.
