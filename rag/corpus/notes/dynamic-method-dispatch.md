---
title: Dynamic Method Dispatch
concept: dynamic-method-dispatch
module: Polymorphism
tags: dynamic-method-dispatch, method-overriding
---

# Dynamic Method Dispatch

When you call an overridden method through a superclass reference, the JVM uses the object's actual
runtime type to decide which implementation runs - not the type of the reference. This is dynamic
dispatch, also called late binding, and it is the mechanism that makes polymorphism work.

Each object carries a pointer to its class's method table, and the call is resolved through that
table at runtime.

Fields are the exception. Field access is resolved at compile time from the reference type, so a
field "hidden" by a subclass does not behave polymorphically. Static methods are also resolved
statically. Only instance methods dispatch dynamically.

```java
public class Account {
    public double interest() { return 0.0; }
}
public class SavingsAccount extends Account {
    @Override public double interest() { return 0.05; }
}

Account ref = new SavingsAccount();   // reference type Account, runtime type SavingsAccount
System.out.println(ref.interest());   // 0.05 - the runtime type wins

// compile error: the compiler only knows `ref` as an Account
// ref.applyInterest();
```

## Key points
- The runtime type of the object decides which override runs.
- The reference type decides which methods you are allowed to call.
- Fields and static methods are bound at compile time, not dynamically.
- This is the mechanism behind every polymorphic design in Java.

## Common mistake
Expecting a hidden field to behave like an overridden method. Field access follows the reference type, so it will not.
