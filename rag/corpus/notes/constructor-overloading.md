---
title: Overloading Constructors
concept: constructor-overloading
module: Constructors
tags: constructor-overloading, constructor-basics, method-overloading
---

# Overloading Constructors

A class may declare several constructors as long as their parameter lists differ in number, type or
order. The compiler picks the right one from the arguments at the call site - exactly the same
resolution rule as method overloading.

Overloading lets callers build the object with whatever information they actually have. A short
constructor can supply sensible defaults for the rest.

Parameter names do not participate in overload resolution. Two constructors that take one String
each are a duplicate no matter what you call the parameters.

```java
public class BankAccount {
    private final String owner;
    private double balance;

    public BankAccount(String owner) {
        this(owner, 0.0);              // delegate, do not duplicate
    }

    public BankAccount(String owner, double opening) {
        this.owner = owner;
        this.balance = opening;
    }
}

new BankAccount("Sara");          // picks the one-argument version
new BankAccount("Sara", 500.0);   // picks the two-argument version
```

## Key points
- Overloads must differ in the number, type or order of parameters.
- The compiler chooses at compile time from the argument list.
- Parameter names are irrelevant to overload resolution.
- Delegate from the short constructor to the full one instead of copying code.

## Common mistake
Trying to overload on return type or on parameter names alone. Neither is part of the signature, so it will not compile.
