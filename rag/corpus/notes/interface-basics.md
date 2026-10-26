---
title: Interface Basics
concept: interface-basics
module: Interfaces
tags: interface-basics, abstraction-basics
---

# Interface Basics

An interface declares a contract: a set of method signatures that any implementing class must
provide. A class states its intent with `implements` and must supply a body for every abstract
method in the interface.

Interface methods are implicitly `public abstract`, and fields are implicitly `public static final`
constants. Writing those modifiers out is legal but redundant.

An interface is a type, so it can be used as a variable type, a parameter type or a return type.
That is the entire point: code written against the interface works with any implementation,
including ones written later.

```java
public interface Comparable<T> {
    int compareTo(T other);               // implicitly public abstract
}

public class Money implements Comparable<Money> {
    private final int cents;
    public Money(int cents) { this.cents = cents; }

    @Override
    public int compareTo(Money other) {
        return Integer.compare(this.cents, other.cents);
    }
}

Comparable<Money> value = new Money(500);       // the interface is the type
List<Money> prices = new ArrayList<>();
Collections.sort(prices);                       // works because Money honours the contract
```

## Key points
- An interface is a contract of method signatures.
- Methods are implicitly public abstract; fields are public static final constants.
- A class may implement any number of interfaces.
- Interfaces are types, usable anywhere a type is expected.

## Common mistake
Trying to declare an interface method `private` or to give an interface instance fields. Neither is allowed.
