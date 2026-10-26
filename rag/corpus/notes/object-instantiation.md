---
title: Creating Objects
concept: object-instantiation
module: Classes & Objects
tags: object-instantiation, class-definition
---

# Creating Objects

An object is created with the `new` keyword. Three things happen in order: memory is allocated on
the heap, the fields are set to their default values, and then a constructor runs to put the
object into a valid starting state. The expression returns a reference to that memory, which you
normally store in a variable.

The variable does not contain the object. It contains a reference that points at the object. This
distinction matters the moment you assign one variable to another or pass an object into a method.

Many objects can be created from one class, and each has its own independent copy of the instance
fields. Changing `a.balance` has no effect whatsoever on `b.balance`.

```java
BankAccount a = new BankAccount();   // allocate, zero the fields, run the constructor
BankAccount b = new BankAccount();   // a completely separate object

a.deposit(500);

System.out.println(a.getBalance());  // 500.0
System.out.println(b.getBalance());  // 0.0  - b was never touched
```

## Key points
- `new` allocates memory, applies default values, then runs a constructor.
- The variable holds a reference, not the object itself.
- Every object gets its own copy of the instance fields.
- One class can produce any number of objects.

## Common mistake
Assuming `BankAccount a;` creates an object. That declares a reference and leaves it `null`; nothing exists until `new` runs.
