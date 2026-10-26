---
title: Runtime Polymorphism
concept: runtime-polymorphism
module: Polymorphism
tags: runtime-polymorphism, dynamic-method-dispatch
---

# Runtime Polymorphism

Polymorphism lets one reference type stand for many concrete types. A method that accepts an
`Account` works unchanged with any subclass, including subclasses written after that method was
compiled. This is what makes plug-in style design possible.

Upcasting - assigning a subclass object to a superclass reference - is always safe and implicit.
Downcasting back is explicit and can fail at runtime with a ClassCastException, so guard it with
`instanceof`.

Modern Java offers pattern matching for `instanceof`, which tests and binds in one step and removes
the redundant cast entirely. Needing many `instanceof` checks is usually a sign that the behaviour
belongs on the objects as an overridden method.

```java
List<Account> accounts = List.of(
    new SavingsAccount(), new CheckingAccount(), new Account());

for (Account a : accounts) {
    System.out.println(a.interest());       // each runs its own version
}

Account a = new SavingsAccount();           // upcast - implicit and safe

if (a instanceof SavingsAccount s) {        // test and bind together
    s.applyInterest();
}
```

## Key points
- One superclass reference can hold any subclass object.
- Upcasting is implicit; downcasting is explicit and can throw.
- Guard downcasts with `instanceof`, ideally with pattern matching.
- A pile of `instanceof` branches usually means the logic belongs in an override.

## Common mistake
Downcasting without checking, then getting a ClassCastException as soon as an unexpected subclass appears in the collection.
