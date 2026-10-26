---
title: Immutable Objects
concept: immutability
module: Encapsulation
tags: immutability, defensive-copying
---

# Immutable Objects

An immutable object cannot change after construction. Building one takes four things: make the class
`final` so nobody can subclass and add mutable state, make every field `private final`, provide no
setters, and defensively copy any mutable field both in the constructor and in any getter.

The payoff is large. An immutable object is automatically thread-safe, can be shared freely without
defensive copies, is safe as a HashMap key, and can never be observed in a half-updated state.

`String`, all the primitive wrapper types, `LocalDate` and `BigDecimal` all work this way. Operations
that look like mutations return a new object instead - which is why `s.toUpperCase();` on its own
does nothing.

```java
public final class Money {                       // final: no subclass can add state
    private final String currency;               // private final: set once
    private final List<String> tags;

    public Money(String currency, List<String> tags) {
        this.currency = currency;
        this.tags = List.copyOf(tags);           // copy in
    }

    public List<String> getTags() { return tags; }   // already unmodifiable

    public Money withCurrency(String other) {    // return a new object
        return new Money(other, tags);
    }
}
```

## Key points
- final class, private final fields, no setters, defensive copies.
- Immutable objects are thread-safe and safe to share without copying.
- Operations return a new instance rather than mutating the existing one.
- String and the wrapper types follow exactly this pattern.

## Common mistake
Calling `s.trim()` or `s.toUpperCase()` and expecting `s` to change. Strings are immutable - you must assign the result.
