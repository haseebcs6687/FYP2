---
title: Composition (has-a)
concept: object-composition
module: Classes & Objects
tags: object-composition, class-definition, reference-semantics
---

# Composition (has-a)

Composition means one object holds other objects as fields, building larger behaviour out of
smaller pieces. It expresses a has-a relationship: a Car has an Engine, an Order has a list of
LineItems.

Composition is usually preferable to inheritance. Inheritance couples a subclass to the internals
of its parent and cannot be changed at runtime; composition keeps the pieces independent and lets
you swap a collaborator whenever you like. The standard advice is to favour composition over
inheritance and reach for `extends` only when there is a genuine is-a relationship.

Delegation is the natural partner of composition: the outer object forwards a call to the inner
object it holds, adding whatever it needs to on the way.

```java
public class Engine {
    public void start() { System.out.println("Engine running"); }
}

public class Car {
    private final Engine engine;      // Car HAS-A Engine

    public Car(Engine engine) {
        this.engine = engine;         // injected, so it can be swapped or mocked
    }

    public void start() {
        engine.start();               // delegation
        System.out.println("Car ready");
    }
}
```

## Key points
- Composition models has-a; inheritance models is-a.
- Held objects can be swapped at runtime, which subclassing cannot do.
- Delegation forwards work to a held object, optionally adding behaviour.
- Prefer composition unless the is-a relationship is genuine and stable.

## Common mistake
Extending a class just to reuse one method. That drags in the entire parent contract and locks the design.
