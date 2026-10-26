---
title: Abstract Classes
concept: abstract-classes
module: Abstraction
tags: abstract-classes, inheritance-basics, abstraction-basics
---

# Abstract Classes

An abstract class is declared with the `abstract` keyword and cannot be instantiated. It exists to
be extended. Its purpose is to hold state and partial implementation that all its subclasses share,
while leaving the parts that differ for them to supply.

It may contain anything a normal class contains - fields, constructors, concrete methods - plus
abstract methods with no body. The constructor is not useless: it runs via `super(...)` when a
concrete subclass is created.

A class must be declared abstract if it has even one abstract method. A class with no abstract
methods may still be declared abstract to say "this is not a complete thing on its own".

```java
public abstract class Shape {
    private final String name;                    // shared state

    protected Shape(String name) {                // runs from subclass constructors
        this.name = name;
    }

    public abstract double area();                // every subclass must supply this

    public String describe() {                    // shared behaviour, written once
        return name + " with area " + area();
    }
}

public class Circle extends Shape {
    private final double radius;
    public Circle(double radius) { super("Circle"); this.radius = radius; }
    @Override public double area() { return Math.PI * radius * radius; }
}

// new Shape("x");   // compile error - abstract classes cannot be instantiated
```

## Key points
- Abstract classes cannot be instantiated; they are extended.
- They may hold fields, constructors and concrete methods.
- One abstract method forces the whole class to be abstract.
- Their constructor runs through `super(...)` when a subclass is created.

## Common mistake
Trying to `new` an abstract class. Instantiate a concrete subclass, or use an anonymous subclass if you really need a one-off.
