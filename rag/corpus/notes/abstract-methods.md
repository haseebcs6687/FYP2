---
title: Abstract Methods
concept: abstract-methods
module: Abstraction
tags: abstract-methods, abstract-classes, method-overriding
---

# Abstract Methods

An abstract method declares a signature and ends with a semicolon instead of a body. It is a
promise that every concrete subclass will provide an implementation, enforced by the compiler.

Any subclass that does not implement every inherited abstract method must itself be declared
abstract. That is how a partial implementation can sit between the abstract base and the concrete
leaf.

`abstract` cannot be combined with `private`, `static` or `final`. Each combination is a
contradiction: a private method cannot be overridden, a static method is not dispatched
dynamically, and a final method cannot be overridden at all.

```java
public abstract class Shape {
    public abstract double area();               // no body, ends with ;
    public abstract double perimeter();
}

public abstract class Polygon extends Shape {
    @Override public double perimeter() { return 0; }   // implements one
    // area() is still abstract, so Polygon must stay abstract
}

public class Square extends Polygon {
    private final double side;
    public Square(double side) { this.side = side; }
    @Override public double area() { return side * side; }       // now concrete
}
```

## Key points
- An abstract method has a signature and no body.
- Every concrete subclass must implement all inherited abstract methods.
- A subclass that implements only some of them must itself be abstract.
- abstract cannot combine with private, static or final.

## Common mistake
Forgetting one abstract method in a subclass. The compiler then demands the subclass be abstract, which often looks like an unrelated error.
