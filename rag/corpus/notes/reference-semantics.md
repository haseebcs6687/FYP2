---
title: References vs Values
concept: reference-semantics
module: Classes & Objects
tags: reference-semantics, object-instantiation
---

# References vs Values

Object variables hold references. Assigning one object variable to another copies the reference,
not the object, so both variables then point at the same object and a change made through one is
visible through the other. This is called aliasing.

Java passes everything by value, but for objects the value being passed is the reference. A method
can therefore mutate the object it was handed, but reassigning the parameter inside the method has
no effect on the caller's variable.

`==` on object references compares the references themselves - are these two variables pointing at
the same object? `equals` compares contents, if the class has overridden it. For Strings and other
value-like types you almost always want `equals`.

```java
BankAccount a = new BankAccount("Sara", 100);
BankAccount b = a;            // b now aliases the SAME object

b.deposit(50);
System.out.println(a.getBalance());   // 150.0 - a sees the change

String x = new String("hi");
String y = new String("hi");
System.out.println(x == y);        // false - different objects
System.out.println(x.equals(y));   // true  - same contents
```

## Key points
- Assignment copies the reference, so two variables can alias one object.
- Java is pass-by-value, but for objects the value is the reference.
- Reassigning a parameter inside a method does not affect the caller.
- `==` compares references; `equals` compares contents.

## Common mistake
Comparing Strings with `==` and getting `true` in small tests because of the string pool, then getting `false` in real code.
