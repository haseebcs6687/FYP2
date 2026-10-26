---
title: Multiple Inheritance
concept: multiple-inheritance
module: Inheritance
tags: multiple-inheritance, inheritance-hierarchy, interface-basics
---

# Multiple Inheritance

Java forbids a class extending more than one class. The reason is the diamond problem: if two
parents both provide an implementation of the same method, there is no principled way to decide
which one the child inherits.

Interfaces sidestep this because a class implementing several interfaces inherits contracts, not
state, and historically inherited no implementation at all. A class may implement any number of
interfaces.

Java 8's default methods reintroduced a narrow version of the problem: if two interfaces provide a
default method with the same signature, the compiler forces the implementing class to override it
and choose explicitly using `Interface.super.method()`.

```java
interface Swimmer { default void move() { System.out.println("swim"); } }
interface Runner  { default void move() { System.out.println("run");  } }

public class Triathlete implements Swimmer, Runner {
    @Override
    public void move() {                  // required - the compiler forces a choice
        Swimmer.super.move();
        Runner.super.move();
    }
}
```

## Key points
- A class extends one class but may implement many interfaces.
- The diamond problem is why multiple class inheritance is banned.
- Interfaces carry contracts and, since Java 8, optional default bodies.
- Conflicting defaults must be resolved explicitly with `Interface.super.method()`.

## Common mistake
Expecting `implements A, B` to silently pick one of two conflicting default methods. It is a compile error until you override.
