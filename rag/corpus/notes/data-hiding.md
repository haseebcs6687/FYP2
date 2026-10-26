---
title: Data Hiding
concept: data-hiding
module: Encapsulation
tags: data-hiding, access-modifiers
---

# Data Hiding

Data hiding means the internal state of an object is not directly reachable from outside. Fields
are private and every change goes through a method the class controls. That control is the whole
point: it is the only place an invariant can be enforced.

If `balance` is public, any code anywhere can set it to a negative number and the class can do
nothing about it. If it is private and only `withdraw` can reduce it, the rule "balance never goes
below zero" can actually be guaranteed.

Hiding also buys freedom to change. As long as the public methods keep their behaviour, the
internal representation can be replaced entirely without breaking any caller.

```java
public class Account {
    private double balance;          // nobody outside can reach this

    public void withdraw(double amount) {
        if (amount <= 0) throw new IllegalArgumentException("Amount must be positive");
        if (amount > balance) throw new IllegalStateException("Insufficient funds");
        balance -= amount;           // the invariant holds because this is the only path
    }

    public double getBalance() { return balance; }
}
```

## Key points
- Private fields plus controlled methods are what enforce an invariant.
- A public field cannot be validated, so its rules cannot be guaranteed.
- Hiding the representation lets it change without breaking callers.
- Expose behaviour, not storage.

## Common mistake
Making a field private and then adding a setter that assigns it with no checks. That is the same exposure with extra steps.
