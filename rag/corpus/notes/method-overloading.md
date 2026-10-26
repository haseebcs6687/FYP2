---
title: Method Overloading
concept: method-overloading
module: Polymorphism
tags: method-overloading, class-definition
---

# Method Overloading

Overloading means several methods in the same class share a name but differ in their parameter
lists. The compiler decides which one to call by looking at the argument types at the call site.
The decision is made entirely at compile time, which is why it is called static or early binding.

Only the parameter list is part of the signature for this purpose. Return type and parameter names
are not, so two methods that differ only in return type will not compile.

When arguments do not match exactly, the compiler prefers widening a primitive over autoboxing,
and autoboxing over varargs. That order explains most surprising overload choices.

```java
public class Printer {
    public void print(int value)    { System.out.println("int: " + value); }
    public void print(double value) { System.out.println("double: " + value); }
    public void print(String value) { System.out.println("String: " + value); }
    public void print(Object value) { System.out.println("Object: " + value); }
}

Printer p = new Printer();
p.print(5);         // int
p.print(5.0);       // double
p.print("5");       // String
p.print('a');       // int  - char widens to int before boxing to Character
```

## Key points
- Overloads differ in the number, type or order of parameters.
- Resolution happens at compile time from the static argument types.
- Return type and parameter names are not part of the signature.
- Widening is preferred over boxing, and boxing over varargs.

## Common mistake
Expecting overload resolution to consider the runtime type of an argument. It uses the declared type only - that is overriding's job, not overloading's.
