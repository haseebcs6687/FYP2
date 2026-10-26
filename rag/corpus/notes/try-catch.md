---
title: try / catch
concept: try-catch
module: Exception Handling
tags: try-catch, class-definition
---

# try / catch

A `try` block wraps code that might fail. A `catch` block handles a specific exception type. If
nothing is thrown the catch blocks are skipped entirely; if something is thrown, the JVM finds the
first catch whose type matches and runs it, then continues after the whole statement.

Order matters. Catch blocks are tested top to bottom, so more specific types must come before more
general ones. Putting `catch (Exception e)` first makes every later catch unreachable, and the
compiler rejects it.

Since Java 7 one catch can handle several unrelated types with `|`. Never write an empty catch
block - swallowing an exception hides a bug and gives you nothing to debug from.

```java
try {
    int[] numbers = new int[3];
    numbers[5] = 10;
    int result = 10 / 0;

} catch (ArrayIndexOutOfBoundsException e) {        // specific first
    System.out.println("Bad index: " + e.getMessage());

} catch (ArithmeticException | NullPointerException e) {   // multi-catch
    System.out.println("Arithmetic or null problem");

} catch (Exception e) {                             // general last
    System.out.println("Something else: " + e.getMessage());
}
```

## Key points
- try wraps risky code; catch handles a matching exception type.
- Catch blocks are checked in order, so specific types come first.
- Multi-catch with `|` handles several unrelated types in one block.
- An empty catch block hides bugs and should never be written.

## Common mistake
Catching `Exception` first. Every subsequent catch becomes unreachable and the code will not compile.
