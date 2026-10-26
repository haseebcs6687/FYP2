---
title: Default and Static Methods
concept: default-methods
module: Interfaces
tags: default-methods, interface-basics
---

# Default and Static Methods

Java 8 added default methods so interfaces could gain new methods without breaking every existing
implementation. A default method has a body, marked with the `default` keyword, and implementing
classes inherit it unless they override it.

This is how `List` gained `sort` and `Iterable` gained `forEach` without breaking the entire
ecosystem overnight.

Interfaces may also declare `static` methods, which belong to the interface itself and are not
inherited by implementors. Since Java 9 they may declare `private` methods too, used only to share
code between the interface's own default methods.

```java
public interface Greeter {
    String name();                                  // abstract - must be implemented

    default String greet() {                        // inherited unless overridden
        return "Hello, " + name();
    }

    static Greeter of(String name) {                // belongs to the interface itself
        return () -> name;
    }
}

public class Formal implements Greeter {
    public String name() { return "Dr Khan"; }
    @Override public String greet() { return "Good evening, " + name(); }   // override
}
```

## Key points
- A default method carries a body so interfaces can evolve safely.
- Implementing classes inherit it and may override it.
- Static interface methods belong to the interface and are not inherited.
- Two conflicting defaults force the implementor to override and choose.

## Common mistake
Treating default methods as a way to add state. An interface still cannot hold instance fields - only constants.
