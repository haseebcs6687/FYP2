---
title: Checked vs Unchecked
concept: checked-vs-unchecked
module: Exception Handling
tags: checked-vs-unchecked, try-catch
---

# Checked vs Unchecked

Checked exceptions extend `Exception` but not `RuntimeException`. The compiler insists that you
either catch them or declare them with `throws`. They model conditions a correct program should
anticipate: a missing file, a dropped connection.

Unchecked exceptions extend `RuntimeException`. The compiler says nothing about them. They model
programming errors: a null dereference, a bad index, an illegal argument. `Error` and its subclasses
such as `OutOfMemoryError` are also unchecked and should not be caught.

The practical rule: use a checked exception when the caller can realistically recover, and an
unchecked one when the failure means the code itself is wrong.

```java
// Checked - the compiler forces a decision
public void read(String path) throws IOException {
    Files.readString(Path.of(path));
}

// Unchecked - no declaration needed
public void setAge(int age) {
    if (age < 0) throw new IllegalArgumentException("Age cannot be negative");
}

try {
    read("missing.txt");
} catch (IOException e) {            // required by the compiler
    System.out.println("Could not read: " + e.getMessage());
}
```

## Key points
- Checked: extends Exception, must be caught or declared.
- Unchecked: extends RuntimeException, no compiler requirement.
- Errors are unchecked and are not meant to be caught.
- Checked for recoverable conditions, unchecked for programming mistakes.

## Common mistake
Wrapping everything in `catch (Exception e)` to make the compiler quiet, which also catches the unchecked bugs you needed to see.
