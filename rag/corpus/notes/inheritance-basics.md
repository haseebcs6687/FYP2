---
title: Inheritance Basics
concept: inheritance-basics
module: Inheritance
tags: inheritance-basics, class-definition
---

# Inheritance Basics

`extends` declares that one class is a specialised kind of another. The subclass inherits every
accessible member of the superclass and can add its own or replace inherited behaviour.

The relationship must genuinely be is-a. A SavingsAccount is an Account, so inheritance fits. A
Car is not an Engine, so composition fits there instead. Getting this wrong produces hierarchies
that are painful to change.

Private members are not inherited in any useful sense - they exist in the object but the subclass
cannot name them. `protected` exists exactly for members a subclass needs but outside code should
not have. Constructors are never inherited.

```java
public class Account {
    protected double balance;             // subclasses may touch this
    private String internalId;            // subclasses cannot name this

    public void deposit(double amount) { balance += amount; }
}

public class SavingsAccount extends Account {
    private double rate;

    public void applyInterest() {
        balance += balance * rate;        // inherited protected field
        deposit(0);                       // inherited public method
    }
}
```

## Key points
- `extends` creates an is-a relationship and inherits accessible members.
- Private members are not accessible to the subclass; protected ones are.
- Constructors are not inherited, which is why `super(...)` exists.
- Use inheritance only when the is-a relationship is real.

## Common mistake
Using inheritance for code reuse when there is no is-a relationship, producing a subclass that inherits methods that make no sense for it.
