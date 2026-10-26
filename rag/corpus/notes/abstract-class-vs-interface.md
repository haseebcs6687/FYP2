---
title: Abstract Class vs Interface
concept: abstract-class-vs-interface
module: Abstraction
tags: abstract-class-vs-interface, abstract-classes, interface-basics
---

# Abstract Class vs Interface

Both let you program against a type rather than an implementation, but they answer different
questions.

Use an abstract class when the implementations are genuinely a family that shares state and code.
It can hold fields and constructors, its members can have any visibility, and a class may extend
only one.

Use an interface when unrelated classes need to honour the same contract. It cannot hold instance
state, its methods are public, and a class may implement as many as it likes. Since Java 8 it can
carry default and static methods, so "interfaces have no implementation" is no longer true.

A common pattern uses both: an interface defines the contract, and an abstract class implements the
tedious parts for implementations that want the help.

```java
public interface Drawable {                       // contract - anything can honour it
    void draw();
    default void redraw() { draw(); }             // optional shared convenience
}

public abstract class Shape implements Drawable { // family - shares state and code
    protected String colour;                      // interfaces cannot hold this
    protected Shape(String colour) { this.colour = colour; }
    public abstract double area();
}

public class Circle extends Shape implements Serializable {
    public Circle(String colour) { super(colour); }
    @Override public double area() { return 0; }
    @Override public void draw() { }
}
```

## Key points
- Abstract class: shared state and code, single inheritance, any visibility.
- Interface: contract only, multiple implementation, members implicitly public.
- Interfaces gained default and static methods in Java 8 but still hold no state.
- Interface for the contract plus an abstract class for shared plumbing is a common pairing.

## Common mistake
Choosing an abstract class for a capability that unrelated types need. It burns the single inheritance slot for no reason.
