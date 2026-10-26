---
title: try-with-resources
concept: try-with-resources
module: Exception Handling
tags: try-with-resources, finally-block
---

# try-with-resources

Any object whose class implements `AutoCloseable` can be declared in the parentheses of a `try`
statement. Java then closes it automatically when the block ends, whether it ended normally or
through an exception.

This replaces the old pattern of closing in a `finally` block, and it fixes two bugs that pattern
was prone to: forgetting the null check, and losing the original exception when `close()` itself
threw.

Several resources can be declared, separated by semicolons; they are closed in reverse order of
declaration. If both the body and `close()` throw, the body's exception is the one that propagates
and the close exception is attached to it as a suppressed exception, reachable via
`getSuppressed()`.

```java
try (BufferedReader reader = Files.newBufferedReader(Path.of("data.txt"));
     PrintWriter writer = new PrintWriter("out.txt")) {

    writer.println(reader.readLine());

} catch (IOException e) {
    System.out.println("I/O failed: " + e.getMessage());
}
// both closed automatically, writer first, even if an exception was thrown

public class Connection implements AutoCloseable {
    @Override public void close() { System.out.println("closed"); }
}
```

## Key points
- Resources declared in the try header are closed automatically.
- The class must implement AutoCloseable.
- Multiple resources close in reverse order of declaration.
- A close() failure is suppressed rather than hiding the real exception.

## Common mistake
Still writing the manual finally-and-close pattern, which loses the original exception when close() also fails.
