---
title: Local vs Instance Variables
concept: local-vs-instance-variables
module: Classes & Objects
tags: local-vs-instance-variables, class-definition
---

# Local vs Instance Variables

A local variable is declared inside a method and lives on the stack for the duration of that one
call. An instance variable is declared in the class body and lives on the heap alongside the
object, for as long as the object lives.

The rule that catches people out is initialisation. Instance variables are given default values
automatically. Local variables are not: the compiler refuses to read a local variable that it
cannot prove has been assigned. This is called definite assignment analysis, and it is a compile
error, not a runtime one.

Scope follows the same split. A local variable is visible only inside the block that declares it;
an instance variable is visible to every non-static method of the class.

```java
public class Example {
    private int instanceCount;        // automatically 0

    public void demo() {
        int localCount;               // NOT automatically 0
        // System.out.println(localCount);  // compile error: might not be initialised

        localCount = 5;               // now it is definitely assigned
        System.out.println(localCount + instanceCount);   // 5
    }
}
```

## Key points
- Locals live on the stack for one call; instance variables live with the object.
- Instance variables get default values; locals must be assigned before use.
- Reading an unassigned local is a compile error, caught before the program runs.
- Scope: locals belong to their block, instance variables to the whole object.

## Common mistake
Expecting a local `int` to start at 0 the way a field does, and being confused by the compiler error.
