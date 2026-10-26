---
title: Getters and Setters
concept: getters-setters
module: Encapsulation
tags: getters-setters, data-hiding
---

# Getters and Setters

Getters and setters are the controlled doorway to private state. A getter returns a value; a setter
changes one. Their real value is that they give the class a place to validate, convert, log or
compute.

They are not automatic. A field that nothing outside needs should have neither. A field that should
never change after construction should have a getter and no setter. Generating a getter and setter
for every field reproduces public fields with more typing.

A setter that validates is doing useful work. A setter that only assigns is usually a design smell -
ask whether the caller should instead be asking the object to do something.

```java
public class Account {
    private double balance;
    private String email;

    public double getBalance() { return balance; }     // read-only by design

    public void setEmail(String email) {               // validated on the way in
        if (email == null || !email.contains("@")) {
            throw new IllegalArgumentException("Invalid email");
        }
        this.email = email;
    }

    public String getEmail() { return email; }
    // deliberately NO setBalance - balance changes only through deposit and withdraw
}
```

## Key points
- Accessors exist so the class can validate and control access.
- Omit the setter when a field should not change after construction.
- A pass-through setter with no checks adds nothing over a public field.
- Prefer asking the object to perform an operation over setting its fields.

## Common mistake
Auto-generating getters and setters for every field, which breaks encapsulation while appearing to follow it.
