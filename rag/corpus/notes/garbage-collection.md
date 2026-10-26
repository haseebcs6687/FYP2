---
title: Garbage Collection
concept: garbage-collection
module: Classes & Objects
tags: garbage-collection, reference-semantics
---

# Garbage Collection

Java reclaims memory automatically. An object becomes eligible for collection when no live
reference can reach it any more - not when you finish using it, and not at a moment you can
predict. The garbage collector then frees it at a time of the JVM's choosing.

Setting a reference to `null` does not delete the object; it only removes one path to it. If any
other reference still points there, the object survives. Conversely, an object with no incoming
references is unreachable even if it holds references to other objects itself.

`finalize()` is deprecated and must not be used for cleanup - it may never run. Resources like
files and sockets need explicit closing, which is what try-with-resources and `AutoCloseable` are
for.

```java
BankAccount a = new BankAccount("Sara", 100);
BankAccount b = a;

a = null;   // the object is still reachable through b - nothing is freed
b = null;   // NOW it is unreachable and eligible for collection

// System.gc() only suggests a collection; it guarantees nothing.
```

## Key points
- Eligibility is about reachability, not about whether you have finished with the object.
- Nulling one reference frees nothing if another reference remains.
- Collection timing is decided by the JVM and cannot be forced.
- Use try-with-resources for files and sockets; never rely on finalize().

## Common mistake
Assuming memory is freed the instant a variable goes out of scope, then being surprised by a leak caused by a forgotten reference in a collection.
