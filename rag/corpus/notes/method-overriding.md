---
title: Method Overriding
concept: method-overriding
module: Inheritance
tags: method-overriding, inheritance-basics
---

# Method Overriding

A subclass overrides a method by declaring one with the same name and parameter list as an
inherited method. From then on, calling that method on an object of the subclass runs the
subclass's version, whatever type the reference has.

The rules are strict. The parameter list must match exactly - a different list is an overload, not
an override, and that mistake is very easy to make silently. The return type must be the same or a
subtype (covariant return). The override may not reduce visibility: a public method cannot become
protected. A checked exception list may be narrowed but not widened.

`@Override` costs nothing and turns a silent mistake into a compile error. Use it every time.

```java
public class Account {
    public double interest() { return 0.0; }
}

public class SavingsAccount extends Account {
    @Override
    public double interest() { return 0.05; }     // real override

    // @Override
    public double interest(int years) { return 0.05 * years; }
    // different parameter list -> this is an OVERLOAD, not an override.
    // Adding @Override here would make the compiler reject it, which is the point.
}
```

## Key points
- Same name and identical parameter list, or it is an overload instead.
- Return type must match or be a subtype; visibility may not be reduced.
- Checked exceptions may be narrowed, never widened.
- `@Override` turns a silent near-miss into a compile error.

## Common mistake
Changing a parameter type slightly and creating an overload that never runs, while the inherited version keeps being called.
