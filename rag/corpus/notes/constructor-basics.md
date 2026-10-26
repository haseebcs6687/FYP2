---
title: Constructor Basics
concept: constructor-basics
module: Constructors
tags: constructor-basics, object-instantiation
---

# Constructor Basics

A constructor is the code that runs when an object is created. It has exactly the same name as the
class and declares no return type, not even `void`. Adding a return type silently turns it into an
ordinary method that will never be called by `new`.

Its job is to leave the object in a valid state. Every field that must have a sensible value should
be set here, and any argument that cannot be accepted should be rejected here, before the object
escapes into the rest of the program. Validating in the constructor is much cheaper than hunting
down a half-built object later.

A constructor cannot be called directly on an existing object. It runs once, as part of `new`.

```java
public class BankAccount {
    private final String owner;
    private double balance;

    public BankAccount(String owner, double opening) {
        if (owner == null || owner.isBlank()) {
            throw new IllegalArgumentException("Owner is required");
        }
        if (opening < 0) {
            throw new IllegalArgumentException("Opening balance cannot be negative");
        }
        this.owner = owner;
        this.balance = opening;
    }
}
```

## Key points
- Same name as the class, and no return type at all.
- It runs once, as part of `new`, and cannot be called again later.
- Its purpose is to guarantee the object is valid from the moment it exists.
- Rejecting bad arguments here prevents invalid objects from ever escaping.

## Common mistake
Writing `public void BankAccount(...)`. That is a normal method that merely shares the class name, so `new` will not run it.
