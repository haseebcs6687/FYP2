---
title: Static Fields and Methods
concept: static-members
module: Classes & Objects
tags: static-members, class-definition
---

# Static Fields and Methods

A static field or method belongs to the class rather than to any one object. There is exactly one
copy of a static field no matter how many objects exist, and it can be read or written without
creating an object at all.

Use static for things that are genuinely shared: a counter of how many objects have been made, a
constant, or a utility method that needs no instance state. `Math.max` is static because computing
a maximum does not depend on any particular Math object.

A static method cannot use `this` and cannot read instance fields directly, because there is no
object in scope. Calling a static member through an object reference compiles but is misleading -
always qualify it with the class name.

```java
public class Counter {
    private static int created = 0;       // one copy, shared by every Counter
    private int id;                       // one copy per object

    public Counter() {
        created++;
        id = created;
    }

    public static int getCreated() {      // callable without any object
        return created;
    }
}

new Counter();
new Counter();
System.out.println(Counter.getCreated());   // 2
```

## Key points
- A static member belongs to the class; there is one copy for the whole program.
- Static methods run without an object and therefore cannot use `this`.
- Static is right for shared counters, constants and stateless utilities.
- Call static members through the class name, not through an instance.

## Common mistake
Trying to read an instance field from a static method. There is no object, so the compiler rejects it.
