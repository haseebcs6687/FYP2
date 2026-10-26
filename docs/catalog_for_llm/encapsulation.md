<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Encapsulation
Protecting internal state and exposing a deliberate public surface.

## access-modifiers - Access Modifiers
summary: public, protected, package-private and private control which code can touch a member.
- access-modifiers/default-means-public | package-private access | Omitting an access modifier on a class member makes it public and accessible to classes across all packages.
- access-modifiers/protected-means-subclass-anywhere-unrestricted | protected scope | A protected member is accessible by any class anywhere in the application without restriction.
- access-modifiers/private-visible-to-subclasses | private inheritance | Private members of a class can be accessed directly by its subclasses.
- access-modifiers/classes-can-be-protected | top-level visibility | Top-level classes can be declared with private or protected access modifiers.
- access-modifiers/package-private-accessible-to-subclasses-everywhere | package-private inheritance | Package-private (default access) members of a parent class can be accessed by subclasses located in any package.

## data-hiding - Data Hiding
summary: Fields are kept private so the class controls every change to its own state.
- data-hiding/getters-make-fields-public | encapsulation purpose | Providing getter and setter methods provides no encapsulation benefit over making fields public.
- data-hiding/data-hiding-is-security-encryption | data protection | Data hiding is a cryptographic security feature designed to encrypt variables in computer memory against attackers.
- data-hiding/final-fields-dont-need-private | immutability vs visibility | Making a mutable object reference public and final provides complete data hiding because the reference cannot be reassigned.
- data-hiding/private-is-per-object | class vs instance scope | A private field cannot be read by another object of the same class (e.g. other.x inside equals).

## getters-setters - Getters and Setters
summary: Accessor and mutator methods expose state deliberately and give the class a place to validate.
- getters-setters/every-field-needs-both | accessor necessity | Proper object-oriented design mandates writing a getter and a setter for every private field in a class.
- getters-setters/setters-cannot-validate | mutator logic | Setters must only perform trivial assignment (this.x = x) and should not validate inputs or throw exceptions.
- getters-setters/getter-returns-clone-automatically | reference leakage | Returning a mutable reference field from a getter automatically creates a safe independent copy.
- getters-setters/boolean-getter-prefixed-with-get | naming convention | Java conventions require boolean accessor methods to be prefixed with 'get' rather than 'is'.

## defensive-copying - Defensive Copying
summary: Copy mutable objects on the way in and on the way out so callers cannot mutate private state.
- defensive-copying/immutable-objects-need-copying | immutable types | Defensive copying is necessary when accepting or returning immutable objects such as String or Integer.
- defensive-copying/clone-is-always-safe | clone method | Calling .clone() on constructor arguments is always safe for creating defensive copies of non-final classes.
- defensive-copying/copying-reference-is-defensive | copy depth | Assigning an incoming array parameter to an instance variable constitutes a defensive copy.
- defensive-copying/only-needed-on-output | input vs output | Defensive copies are only required when returning data in getters, not when accepting parameters in constructors.

## immutability - Immutable Objects
summary: An immutable class has final fields, no setters, and never exposes internal mutable state.
- immutability/final-class-makes-all-fields-immutable | final class | Declaring a class final automatically makes all of its instance fields final and immutable.
- immutability/final-reference-means-immutable-object | reference immutability | Declaring a reference variable final prevents the fields of the referenced object from being altered.
- immutability/immutable-classes-cannot-have-methods | immutable operations | Immutable classes cannot provide operations that transform or compute new values from their data.
- immutability/no-setters-equals-immutable | class immutability | A class is guaranteed to be immutable as long as it declares no setter methods.

## javabeans - The JavaBeans Convention
summary: A bean is a class with a public no-arg constructor, private fields and getX/setX accessors.
- javabeans/requires-special-interface | javabean contract | A class must implement a specific interface called JavaBean to be recognized as a valid JavaBean.
- javabeans/must-not-have-logic | bean methods | JavaBeans are restricted to being pure data holders and cannot contain domain business methods.
- javabeans/constructor-arguments-mandatory | bean instantiation | A JavaBean must have a constructor that initializes all properties at creation time.
- javabeans/property-name-capitalization | property naming | In JavaBeans convention, a getter getAge() corresponds to a property whose logical name is capitalized as 'Age'.
