---
title: The finally Block
concept: finally-block
module: Exception Handling
tags: finally-block, try-catch
---

# The finally Block

A `finally` block runs whether or not an exception was thrown, and whether or not one was caught. It
runs even when the try block executes `return`. That makes it the right place for cleanup.

The order is precise: when a try block returns, the return value is computed, then finally runs,
then the method actually returns.

A `return` inside `finally` discards any exception in flight and overrides any return value from the
try block. It silently swallows failures and should be avoided. For closing resources,
try-with-resources is cleaner than a finally block and handles the edge cases correctly.

```java
public static int demo() {
    try {
        return 1;                 // value 1 is computed and held
    } finally {
        System.out.println("finally always runs");   // then this runs
    }
    // method returns 1
}

public static int bad() {
    try {
        throw new RuntimeException("lost");
    } finally {
        return 2;                 // the exception vanishes - never do this
    }
}
```

## Key points
- finally runs after try and catch, including when try returns.
- It is the classic place for cleanup that must always happen.
- A return inside finally swallows exceptions and overrides return values.
- try-with-resources is the modern replacement for cleanup in finally.

## Common mistake
Returning from a finally block and silently destroying an exception that was on its way up the stack.
