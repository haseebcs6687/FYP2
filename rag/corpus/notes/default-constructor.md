---
title: The Default Constructor
concept: default-constructor
module: Constructors
tags: default-constructor, constructor-basics
---

# The Default Constructor

If a class declares no constructor at all, the compiler generates a no-argument constructor for it.
That generated constructor is public if the class is public, has an empty body, and calls
`super()`.

The moment you declare any constructor yourself, the compiler stops generating it. This is the
usual cause of "constructor BankAccount in class BankAccount cannot be applied to given types":
someone added a two-argument constructor and existing `new BankAccount()` calls stopped compiling.

If you need both, declare the no-argument one explicitly. Frameworks that instantiate objects
reflectively - JavaBeans, JPA, many serialisation libraries - require a no-argument constructor to
be present.

```java
public class Plain { }                 // compiler supplies Plain()
new Plain();                           // fine

public class Configured {
    private int size;
    public Configured(int size) { this.size = size; }
}
// new Configured();   // compile error - the default constructor is gone

public class Both {
    private int size;
    public Both() { this(10); }        // declared explicitly, so it exists
    public Both(int size) { this.size = size; }
}
```

## Key points
- A default constructor appears only when the class declares no constructor.
- Declaring any constructor removes the generated one.
- The generated constructor is empty and calls `super()`.
- Many frameworks need an explicit no-argument constructor to exist.

## Common mistake
Adding a parameterised constructor to an existing class and breaking every `new ClassName()` call elsewhere in the codebase.
