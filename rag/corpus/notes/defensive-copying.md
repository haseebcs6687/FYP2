---
title: Defensive Copying
concept: defensive-copying
module: Encapsulation
tags: defensive-copying, getters-setters, reference-semantics
---

# Defensive Copying

Returning a mutable object from a getter hands the caller a live reference to internal state. They
can then modify it and bypass every check the class has. Accepting a mutable object in a constructor
has the same problem in reverse: the caller keeps their reference and can mutate it afterwards.

The fix is to copy on the way in and on the way out. Copy in the constructor so later changes to the
caller's object do not affect you; copy in the getter so changes to what you return do not affect
you either.

`Collections.unmodifiableList` or `List.copyOf` is a lighter alternative for the outward direction:
the caller gets a view that throws if they try to modify it.

```java
public class Order {
    private final List<String> items;

    public Order(List<String> items) {
        this.items = new ArrayList<>(items);      // copy IN
    }

    public List<String> getItems() {
        return List.copyOf(items);                // unmodifiable copy OUT
    }

    // Without both copies:
    //   List<String> mine = new ArrayList<>(List.of("a"));
    //   Order o = new Order(mine);
    //   mine.add("b");          // would silently change the order
    //   o.getItems().add("c");  // would silently change the order
}
```

## Key points
- Copy mutable arguments in the constructor and mutable returns in the getter.
- `final` on the field protects the reference, not the object it points at.
- `List.copyOf` and `Collections.unmodifiable*` guard the outward direction cheaply.
- Immutable types such as String need no copying.

## Common mistake
Marking a collection field `final` and assuming it is now safe. `final` stops reassignment, not mutation of the contents.
