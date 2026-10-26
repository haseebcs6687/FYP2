---
title: Functional Interfaces
concept: functional-interface
module: Interfaces
tags: functional-interface, interface-basics
---

# Functional Interfaces

A functional interface has exactly one abstract method. Because there is only one, the compiler can
match a lambda expression or a method reference to it without ambiguity - which is what makes lambda
syntax possible.

Default and static methods do not count towards the one-abstract-method rule, so an interface can
have any number of them and still be functional.

`@FunctionalInterface` is optional but worth adding: it makes the compiler reject the interface if
someone later adds a second abstract method. `java.util.function` supplies the common shapes -
`Predicate<T>`, `Function<T,R>`, `Consumer<T>`, `Supplier<T>` - so you rarely need to write your
own.

```java
@FunctionalInterface
public interface Validator {
    boolean test(String value);                    // exactly one abstract method
    default Validator and(Validator other) {       // defaults do not break it
        return v -> this.test(v) && other.test(v);
    }
}

Validator notEmpty = v -> v != null && !v.isBlank();      // lambda
Validator hasAt    = v -> v.contains("@");
Validator email    = notEmpty.and(hasAt);

Function<String, Integer> length = String::length;        // method reference
```

## Key points
- Exactly one abstract method makes an interface functional.
- Default and static methods do not count towards that one.
- Lambdas and method references are implementations of functional interfaces.
- `@FunctionalInterface` makes the compiler enforce the rule.

## Common mistake
Adding a second abstract method later and breaking every lambda that used the interface, with a confusing error at each call site.
