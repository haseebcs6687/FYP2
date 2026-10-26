---
title: Access Modifiers
concept: access-modifiers
module: Encapsulation
tags: access-modifiers, class-definition
---

# Access Modifiers

Java has four levels of access. `private` restricts a member to its own class. Package-private -
written by leaving the modifier off entirely - allows access from any class in the same package.
`protected` adds subclasses, including subclasses in other packages. `public` allows everything.

The default should be `private`. Start there and widen only when something outside genuinely needs
access. Every member you make public becomes part of a contract you have to keep.

Top-level classes can only be public or package-private. `protected` and `private` are not legal on
a top-level class, though they are legal on nested ones.

```java
public class Account {
    private double balance;          // this class only
    double internalRate;             // package-private: same package
    protected String owner;          // package + subclasses anywhere
    public String accountNumber;     // everyone

    private void audit() { }         // helper nobody else should call
    public double getBalance() { return balance; }   // the deliberate surface
}
```

## Key points
- private < package-private < protected < public, in widening order.
- Leaving the modifier off means package-private, not public.
- protected includes subclasses in other packages; package-private does not.
- Default to private and widen only when there is a real need.

## Common mistake
Assuming no modifier means public. It means package-private, which is why code compiles inside the package and fails outside it.
