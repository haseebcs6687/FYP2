---
title: Design Patterns
concept: design-patterns
module: Abstraction
tags: design-patterns, abstract-class-vs-interface, runtime-polymorphism
---

# Design Patterns

Design patterns are named solutions to problems that keep recurring in object-oriented design. They
are worth knowing mostly because they give a vocabulary: saying "use a Strategy here" carries a lot
of meaning in three words.

Factory hides which concrete class gets created, so calling code depends only on the interface.
Strategy puts each variant of an algorithm in its own class and lets the caller swap them at
runtime. Singleton restricts a class to one instance. Observer lets objects subscribe to events
from another object. Template Method puts the skeleton of an algorithm in an abstract class and
leaves specific steps to subclasses.

Every one of them rests on abstraction and polymorphism. Use a pattern when it removes duplication
or makes change easier - not because it has a name.

```java
// Strategy: the algorithm is an object the caller chooses
public interface DiscountPolicy { double apply(double total); }

public class NoDiscount     implements DiscountPolicy { public double apply(double t) { return t; } }
public class StudentDiscount implements DiscountPolicy { public double apply(double t) { return t * 0.8; } }

public class Checkout {
    private DiscountPolicy policy;
    public void setPolicy(DiscountPolicy p) { this.policy = p; }   // swap at runtime
    public double total(double subtotal) { return policy.apply(subtotal); }
}

// Factory: creation detail hidden behind a method
public class ProcessorFactory {
    public static PaymentProcessor create(String type) {
        return "stripe".equals(type) ? new StripeProcessor() : new PaypalProcessor();
    }
}
```

## Key points
- Patterns are shared names for recurring design solutions.
- Factory hides construction, Strategy makes an algorithm swappable.
- Singleton restricts instances, Observer distributes events.
- They all depend on abstraction and polymorphism underneath.

## Common mistake
Applying patterns everywhere on principle. A Factory that constructs one class, or a Singleton used as a global variable, adds complexity and removes none.
