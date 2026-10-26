---
title: Copy Constructors
concept: copy-constructor
module: Constructors
tags: copy-constructor, constructor-overloading, reference-semantics
---

# Copy Constructors

A copy constructor takes another instance of the same class and builds a duplicate from it. Java
has no built-in copy syntax, so this is the idiomatic way to duplicate an object - clearer and
safer than `Cloneable` and `clone()`.

The important decision is shallow versus deep. A shallow copy copies each field as-is, so a
reference field ends up pointing at the same underlying object in both copies, and mutating it
through one is visible through the other. A deep copy duplicates the referenced objects too.

For any mutable field, copy deeply. For immutable fields such as String or Integer, sharing the
reference is perfectly safe because nothing can change it.

```java
public class Order {
    private final String id;                 // immutable - share it
    private final List<String> items;        // mutable - copy it

    public Order(String id, List<String> items) {
        this.id = id;
        this.items = new ArrayList<>(items);
    }

    // copy constructor
    public Order(Order other) {
        this.id = other.id;
        this.items = new ArrayList<>(other.items);   // deep copy
    }
}
```

## Key points
- A copy constructor takes the same type and duplicates its state.
- Shallow copies share referenced objects; deep copies duplicate them.
- Copy mutable fields deeply, share immutable ones freely.
- Preferred over `Cloneable`, which has a famously awkward contract.

## Common mistake
Copying a List field by simple assignment. Both objects then share one list, and adding to one adds to the other.
