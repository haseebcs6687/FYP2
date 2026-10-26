---
title: Default Field Values
concept: default-values
module: Classes & Objects
tags: default-values, local-vs-instance-variables
---

# Default Field Values

Before any constructor body runs, the JVM zeroes every field of a new object. Numeric types become
0, `char` becomes `'\u0000'`, `boolean` becomes `false`, and every reference type becomes `null`.
Static fields are given the same treatment when the class is loaded.

This is the reason a field can be read safely before you have explicitly set it, and it is also the
reason an untouched object reference field is `null` rather than some usable empty object.

Local variables are excluded from this. They get no default at all, which is covered under
local vs instance variables.

```java
public class Defaults {
    int number;          // 0
    double amount;       // 0.0
    boolean active;      // false
    char letter;         // '\u0000'  (prints as nothing)
    String name;         // null
    int[] values;        // null - the ARRAY reference, not an empty array

    void show() {
        System.out.println(number + " " + active + " " + name);   // 0 false null
        // values[0] = 1;   // NullPointerException - no array was ever created
    }
}
```

## Key points
- Fields are zeroed before the constructor body runs.
- Numbers become 0, boolean becomes false, references become null.
- A default reference field is null, not an empty object or empty array.
- Local variables receive no default and must be assigned explicitly.

## Common mistake
Assuming an uninitialised array field is an empty array. It is `null`, and touching it throws a NullPointerException.
