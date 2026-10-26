---
title: Defining a Class
concept: class-definition
module: Classes & Objects
tags: class-definition
---

# Defining a Class

A class is a blueprint. It declares what data every object of that type will hold and what
operations that object can perform. Writing a class does not create anything at runtime - it
describes a shape that objects will later be stamped from.

A class body holds two kinds of member. Fields (also called instance variables) hold state.
Methods hold behaviour. Both are declared inside the braces of the class, and both can be given
an access modifier that controls who may touch them. A well-designed class keeps its fields
private and exposes only the methods that make sense to the outside world.

The file name must match the public class name exactly, including capitalisation. A file called
BankAccount.java must contain `public class BankAccount`. Java allows other, non-public classes
in the same file, but only one public class per file.

```java
public class BankAccount {
    // fields - the state every BankAccount carries
    private String owner;
    private double balance;

    // method - the behaviour every BankAccount offers
    public void deposit(double amount) {
        if (amount > 0) {
            balance += amount;
        }
    }

    public double getBalance() {
        return balance;
    }
}
```

## Key points
- A class describes structure; it does not occupy memory until an object is created from it.
- Fields hold state, methods hold behaviour, and both live inside the class body.
- A public class must live in a file with exactly the same name.
- Keeping fields private is the starting point of encapsulation.

## Common mistake
Treating the class itself as the thing that stores data. The class is the mould; each object made from it has its own separate copy of the fields.
