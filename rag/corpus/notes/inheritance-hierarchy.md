---
title: Class Hierarchies
concept: inheritance-hierarchy
module: Inheritance
tags: inheritance-hierarchy, inheritance-basics
---

# Class Hierarchies

Java has single inheritance for classes: every class has exactly one direct superclass. A class
with no `extends` clause implicitly extends `Object`, so every class in the language sits in one
tree rooted at `Object`.

That is why every object has `toString()`, `equals()`, `hashCode()` and `getClass()` - they are
inherited from `Object`. Overriding `toString()` is usually the first useful thing a new class
does.

`final` on a class prevents anyone extending it, and `final` on a method prevents anyone
overriding it. `String` is final, which is part of why it is safe to share String references
freely.

```java
// implicit: class Account extends Object
public class Account {
    private double balance;

    @Override
    public String toString() {            // inherited from Object, now replaced
        return "Account[balance=" + balance + "]";
    }
}

public final class Money { }              // nobody can extend this

public class Base {
    public final void audit() { }         // nobody can override this
}
```

## Key points
- One direct superclass per class; every class descends from Object.
- toString, equals, hashCode and getClass come from Object.
- `final` on a class blocks extension; on a method it blocks overriding.
- The single-rooted tree is what makes `Object` usable as a universal type.

## Common mistake
Extending two classes. Java does not allow it - use interfaces when a type needs to honour several contracts.
