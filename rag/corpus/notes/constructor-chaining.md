---
title: Constructor Chaining
concept: constructor-chaining
module: Constructors
tags: constructor-chaining, constructor-overloading, super-keyword
---

# Constructor Chaining

Chaining means one constructor calls another so the initialisation logic lives in a single place.
There are two forms. `this(...)` calls another constructor of the same class. `super(...)` calls a
constructor of the parent class.

Either call must be the very first statement of the constructor, and you cannot use both in the
same constructor. If you write neither, the compiler silently inserts a call to the parent's
no-argument constructor - which is a compile error if the parent has no such constructor.

Construction always runs parent-first. The whole super chain completes before the subclass body
executes, which is why a field set in a subclass constructor is not yet available to a method
called from the parent constructor.

```java
public class Account {
    protected String owner;
    public Account(String owner) { this.owner = owner; }
}

public class SavingsAccount extends Account {
    private double rate;

    public SavingsAccount(String owner) {
        this(owner, 0.05);            // -> the two-arg constructor below
    }

    public SavingsAccount(String owner, double rate) {
        super(owner);                 // MUST be first; runs Account's constructor
        this.rate = rate;
    }
}
```

## Key points
- `this(...)` chains within the class; `super(...)` chains to the parent.
- Either one must be the first statement, and you cannot use both.
- Omitting both inserts an implicit `super()` call.
- Parent constructors always finish before the subclass body starts.

## Common mistake
Calling an overridable method from a constructor. The subclass override runs before the subclass fields are initialised, so it sees nulls and zeros.
