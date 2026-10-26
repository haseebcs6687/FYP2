---
title: The this Reference
concept: this-keyword
module: Classes & Objects
tags: this-keyword, object-instantiation
---

# The this Reference

Inside an instance method or constructor, `this` is a reference to the object the method was
invoked on. It is an implicit parameter the JVM supplies.

The most common use is to disambiguate when a parameter shadows a field of the same name. If a
constructor takes a parameter called `owner` and the class also has a field called `owner`, plain
`owner` refers to the parameter, and `this.owner` refers to the field.

`this` also lets an object pass itself to another object, and `this(...)` as the first statement
of a constructor delegates to a different constructor in the same class.

```java
public class BankAccount {
    private String owner;
    private double balance;

    public BankAccount(String owner, double balance) {
        this.owner = owner;       // field = parameter
        this.balance = balance;
    }

    public void transferTo(BankAccount other, double amount) {
        this.balance -= amount;
        other.receive(amount, this);   // hand this object to another object
    }
}
```

## Key points
- `this` refers to the object the current instance method is running on.
- It resolves shadowing between a parameter and a field of the same name.
- An object can pass itself to other objects using `this`.
- `this(...)` as the first statement delegates to another constructor.

## Common mistake
Writing `owner = owner;` in a constructor. That assigns the parameter to itself and silently leaves the field null.
