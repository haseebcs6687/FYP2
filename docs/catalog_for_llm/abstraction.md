<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Abstraction
Modelling what something does before deciding how it does it.

## abstraction-basics - What Abstraction Is
summary: Abstraction keeps the essential behaviour of a type visible and hides the incidental detail.
- abstraction-basics/abstraction-equals-information-hiding | concept definition | Abstraction and encapsulation are identical concepts that describe the same programming mechanism.
- abstraction-basics/cannot-use-abstract-types-as-variables | abstract reference types | Because an abstract type cannot be instantiated, you cannot declare reference variables or method parameters of that abstract type.
- abstraction-basics/more-abstraction-always-better | design trade-offs | Adding additional layers of abstract classes and interfaces always improves code quality regardless of problem scale.
- abstraction-basics/abstraction-requires-abstract-keyword | language mechanism | Abstraction in Java can only be achieved by explicitly using the abstract keyword.

## abstract-classes - Abstract Classes
summary: An abstract class cannot be instantiated and exists to be extended by concrete subclasses.
- abstract-classes/can-be-instantiated-with-new | instantiation rules | An abstract class can be directly instantiated by invoking new AbstractClass().
- abstract-classes/cannot-have-constructors | constructor existence | Because abstract classes cannot be directly instantiated, they cannot declare constructors.
- abstract-classes/must-have-abstract-methods | method requirements | A class declared with the abstract modifier must contain at least one abstract method.
- abstract-classes/cannot-have-concrete-methods | member implementation | Abstract classes are like old interfaces and cannot provide any fully implemented concrete methods.
- abstract-classes/abstract-class-without-abstract-methods-instantiable | abstract class instantiation | An abstract class that contains only concrete methods and no abstract methods can be instantiated directly with new.

## abstract-methods - Abstract Methods
summary: An abstract method declares a signature with no body and forces every concrete subclass to supply one.
- abstract-methods/can-have-empty-body | method syntax | An abstract method declaration can have a body consisting of empty curly braces ({}).
- abstract-methods/can-be-private-or-final | modifier compatibility | An abstract method can be declared private or final to restrict how subclasses access it.
- abstract-methods/subclass-can-ignore-implementation | subclass obligations | A concrete subclass does not have to implement inherited abstract methods if it chooses not to use them.
- abstract-methods/can-be-declared-in-normal-class | class declaration context | A concrete regular class can declare an abstract method without making the class itself abstract.

## abstract-class-vs-interface - Abstract Class vs Interface
summary: Abstract classes share state and partial implementation; interfaces declare a contract many unrelated types can honour.
- abstract-class-vs-interface/interfaces-can-hold-state | state storage | Interfaces can declare mutable instance variables to hold object state like abstract classes do.
- abstract-class-vs-interface/default-methods-make-interfaces-abstract-classes | type differences | Default methods make interfaces completely identical to abstract classes in modern Java.
- abstract-class-vs-interface/classes-can-extend-multiple-abstract-classes | inheritance capability | A class can extend multiple abstract classes just like it can implement multiple interfaces.
- abstract-class-vs-interface/abstract-must-implement-all-interface-methods | interface implementation | An abstract class that implements an interface must provide concrete implementations for all interface methods.

## design-patterns - Design Patterns
summary: Recurring OOP solutions such as Factory, Strategy, Singleton and Observer built on abstraction and polymorphism.
- design-patterns/lazy-singleton-thread-safe | singleton concurrency | A simple lazily-initialized singleton using an unchecked null check is automatically thread-safe.
- design-patterns/factory-requires-inheritance | factory pattern | The Factory design pattern cannot be used without building an extensive subclass inheritance tree.
- design-patterns/patterns-are-reusable-code-libraries | pattern nature | Design patterns are off-the-shelf code libraries that can be directly imported with an import statement.
- design-patterns/strategy-requires-inheritance | strategy composition | Implementing the Strategy pattern requires the context class to inherit from the strategy algorithm rather than using composition.
