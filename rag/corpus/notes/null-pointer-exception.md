---
title: NullPointerException
concept: null-pointer-exception
module: Exception Handling
tags: null-pointer-exception, reference-semantics, try-catch
---

# NullPointerException

A NullPointerException is thrown whenever you dereference a null reference: calling a method on it,
reading a field, indexing it as an array, or unboxing it into a primitive. It is unchecked, so
nothing warns you at compile time.

Since Java 14, helpful NullPointerException messages name the exact expression that was null, which
removes most of the guesswork from a chained call.

Prevention beats catching. Validate arguments at the boundary and fail with a clear
IllegalArgumentException. Return an empty collection rather than null. Use `Optional` for a return
value that genuinely may be absent - but not for fields or parameters. And put the constant first in
a comparison: `"admin".equals(role)` is null-safe, `role.equals("admin")` is not.

```java
String role = null;

// role.equals("admin");          // NullPointerException
"admin".equals(role);             // false - safe

Objects.requireNonNull(role, "role must not be null");   // fail fast, clear message

Optional<User> user = repository.findById(5);
String name = user.map(User::getName).orElse("unknown");

public List<String> getTags() {
    return tags == null ? List.of() : tags;   // empty, never null
}
```

## Key points
- Thrown on any dereference of null: method call, field access, unboxing.
- Java 14+ messages name the exact expression that was null.
- Validate at the boundary with Objects.requireNonNull.
- Return empty collections, use Optional for absent return values, and compare constant-first.

## Common mistake
Catching NullPointerException to keep the program running. It is a bug, not a condition - fix the null instead of hiding it.
