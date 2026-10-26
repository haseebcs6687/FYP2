<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Inheritance
Reusing and extending behaviour through class hierarchies.

## inheritance-basics - Inheritance Basics
summary: extends creates an is-a relationship so a subclass inherits the accessible members of its superclass.
- inheritance-basics/private-members-inherited | member inheritance | Private fields and methods of a parent class are directly accessible by name in the subclass body.
- inheritance-basics/inheritance-copies-parent-code | inheritance mechanism | Inheritance functions by textually copying the superclass code into the child class bytecode.
- inheritance-basics/subclass-smaller-than-superclass | instance footprint | A subclass object occupies less memory than a superclass object because it is more specialized.
- inheritance-basics/is-a-interchangeable-with-has-a | design semantics | Inheritance should be chosen over composition whenever a class needs utility functionality from another class.
- inheritance-basics/private-fields-not-in-subclass-instance | subclass memory layout | A subclass object does not contain the parent class's private instance variables in memory because it cannot access them directly.

## inheritance-hierarchy - Class Hierarchies
summary: Every class ultimately extends Object, forming a single-rooted tree of types.
- inheritance-hierarchy/object-class-optional | root class | A Java class that does not declare an extends clause has no superclass and does not inherit from Object.
- inheritance-hierarchy/downcasting-always-safe | type casting | Casting a superclass reference variable to a subclass type always succeeds if it compiles.
- inheritance-hierarchy/parent-constructor-not-called | construction sequence | Instantiating a subclass does not execute superclass constructors unless super() is explicitly written.
- inheritance-hierarchy/sibling-classes-interchangeable | type compatibility | Two distinct subclasses that share the same direct parent class can be assigned to each other's references.

## multiple-inheritance - Multiple Inheritance
summary: Java forbids extending two classes (the diamond problem) but allows implementing many interfaces.
- multiple-inheritance/java-supports-multiple-class-inheritance | class extension | A Java class can extend multiple classes simultaneously using a comma-separated extends clause.
- multiple-inheritance/interfaces-solve-diamond-without-rules | default method conflict | Implementing two interfaces with identical default method signatures causes no conflict in Java.
- multiple-inheritance/interface-fields-multiply-inherited | interface constant conflict | A class implementing two interfaces containing fields with the same name inherits both transparently.
- multiple-inheritance/extends-interfaces-syntax | class declaration syntax | Classes use the extends keyword to implement interfaces in Java.

## method-overriding - Method Overriding
summary: A subclass replaces an inherited method by declaring the same signature; @Override makes the intent explicit.
- method-overriding/static-methods-override | static dispatch | Declaring an identical static method in a subclass overrides the superclass static method polymorphically.
- method-overriding/can-reduce-visibility | visibility rules | An overriding method in a subclass can have a more restrictive access modifier than the superclass method.
- method-overriding/override-annotation-required | compiler annotation | Method overriding does not take effect at runtime unless the method is annotated with @Override.
- method-overriding/overriding-by-return-type-only | method signature | Changing only the return type to an unrelated type without altering parameter types produces a valid override.
- method-overriding/overload-override-same | overload vs override | Method overloading and method overriding are synonyms describing the exact same object-oriented mechanism.
- method-overriding/final-methods-overridable | final method inheritance | A method declared with the final keyword can be overridden by a subclass as long as the signature matches.
