<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Interfaces
Contracts that let unrelated classes be used interchangeably.

## interface-basics - Interface Basics
summary: An interface is a contract of method signatures that implementing classes must fulfil.
- interface-basics/interface-methods-default-to-package | member visibility | Methods declared in an interface without an access modifier have package-private visibility.
- interface-basics/interface-fields-can-be-mutable | interface fields | Fields declared in an interface can be mutable instance variables modified by implementing classes.
- interface-basics/interface-can-have-constructors | interface lifecycle | Interfaces can define constructor methods to initialize their constant fields.
- interface-basics/interfaces-cannot-extend-other-interfaces | interface inheritance | An interface cannot inherit from another interface using the extends keyword.
- interface-basics/interface-fields-are-instance-variables | interface field modifiers | Fields declared inside an interface without explicit keywords are normal instance variables belonging to implementing objects.

## default-methods - Default and Static Methods
summary: Since Java 8 an interface may ship a default body so it can evolve without breaking implementors.
- default-methods/default-methods-can-modify-instance-state | state access | Default methods can declare and mutate interface-level instance fields.
- default-methods/default-methods-override-object-methods | object method rules | An interface can provide default implementations for equals(), hashCode(), or toString().
- default-methods/implementing-class-must-override-default | override necessity | A class implementing an interface is forced to override all default methods provided by the interface.
- default-methods/default-keyword-optional | method syntax | An interface method with a code body is automatically a default method without writing the default keyword.

## functional-interface - Functional Interfaces
summary: An interface with exactly one abstract method can be implemented by a lambda expression.
- functional-interface/can-have-multiple-abstract-methods | single abstract method | A functional interface can declare two or more abstract methods if it has default methods.
- functional-interface/cannot-have-default-or-static-methods | non-abstract members | Functional interfaces cannot contain any default or static methods.
- functional-interface/annotation-mandatory | annotation role | An interface cannot be used with lambda expressions unless explicitly annotated with @FunctionalInterface.
- functional-interface/lambdas-create-new-classes-at-compile-time | lambda implementation | Every lambda expression generates an anonymous inner class .class file on disk during compilation.
