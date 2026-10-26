---
title: The super Keyword
concept: super-keyword
module: Constructors
tags: super-keyword, inheritance-basics
---

# The super Keyword

`super` gives a subclass access to the parent part of itself. It has two distinct uses.

`super(...)` in a constructor invokes a parent constructor and must be the first statement.
`super.method()` in an ordinary method invokes the parent's version of a method the subclass has
overridden, which is how an override extends behaviour rather than replacing it outright.

`super.method()` is also the escape hatch from infinite recursion: inside an override, a plain call
to `method()` calls the override again.

```java
public class Account {
    protected double balance;
    public void withdraw(double amount) { balance -= amount; }
    public String describe() { return "Account with " + balance; }
}

public class CheckingAccount extends Account {
    @Override
    public void withdraw(double amount) {
        super.withdraw(amount);          // do the parent's work
        super.withdraw(1.50);            // then add an overdraft fee
    }

    @Override
    public String describe() {
        return "Checking - " + super.describe();   // extend, do not replace
    }
}
```

## Key points
- `super(...)` calls a parent constructor and must come first.
- `super.method()` calls the parent's version of an overridden method.
- It lets an override extend the inherited behaviour instead of discarding it.
- Calling the method without `super.` inside its own override recurses forever.

## Common mistake
Forgetting `super.` inside an override and causing a StackOverflowError as the method calls itself.
