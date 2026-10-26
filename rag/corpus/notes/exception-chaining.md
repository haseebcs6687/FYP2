---
title: Exception Chaining
concept: exception-chaining
module: Exception Handling
tags: exception-chaining, exception-throwing
---

# Exception Chaining

Chaining wraps a low-level exception inside one that makes sense at the current layer, while keeping
the original as the cause. The caller sees a meaningful type, and the full stack trace of what
actually went wrong is still there.

Every standard exception has a constructor taking a cause, and `getCause()` retrieves it. A printed
stack trace shows the whole chain under "Caused by:".

Wrapping without passing the cause is the mistake to avoid. `throw new DataAccessException("failed")`
discards every piece of diagnostic information the original exception carried, and the resulting
stack trace points at your wrapper instead of the real problem.

```java
public class UserRepository {
    public User findById(int id) {
        try {
            return database.query(id);

        } catch (SQLException e) {
            // wrap with a meaningful type, KEEP the cause
            throw new DataAccessException("Could not load user " + id, e);
        }
    }
}

public class DataAccessException extends RuntimeException {
    public DataAccessException(String message, Throwable cause) {
        super(message, cause);            // pass it up
    }
}
```

## Key points
- Wrapping translates a low-level failure into a meaningful one.
- Always pass the original exception as the cause.
- `getCause()` retrieves it; stack traces show it under 'Caused by:'.
- Dropping the cause destroys the diagnostic trail.

## Common mistake
Catching an exception and throwing a new one without the cause, leaving a stack trace that points nowhere useful.
