<!-- IMPORTANT FOR LLM GENERATION: The misconception IDs listed below are the ONLY allowed values for 'misconception_id'. Every distractor option must strictly map to a valid misconception ID from this catalog for the target concept (or null for at most one careless distractor). Never invent or modify IDs. -->

# Misconception Catalog - Classes & Objects
How a class describes state and behaviour, and how objects come to life.

## class-definition - Defining a Class
summary: A class is the blueprint that declares the fields and methods every object of that type will have.
- class-definition/class-stores-instance-data | blueprint instantiation | Declaring a class allocates storage for instance variables in the class itself rather than in individual instances.
- class-definition/multiple-public-classes | compilation unit | A single Java source file can contain definitions for multiple top-level public classes.
- class-definition/filename-independent | file naming | A public class name does not need to match the name of the containing .java file.
- class-definition/executable-without-main | program entry | Any class definition can be run directly as a standalone application without declaring a public static void main method.

## object-instantiation - Creating Objects
summary: The new keyword allocates an object on the heap, runs a constructor, and returns a reference to it.
- object-instantiation/declaration-creates-object | reference vs object | Declaring an object reference variable automatically creates and initializes the object in memory without calling new.
- object-instantiation/two-new-same-object | instance uniqueness | Two new Foo() expressions called with identical arguments yield the same object and evaluate to true with the == operator.
- object-instantiation/assignment-clones-object | assignment semantics | Assigning one reference variable to another copies all instance fields into a separate, duplicate object.
- object-instantiation/stack-allocated-objects | memory layout | Objects instantiated inside a method body with new are allocated on the method call stack.

## static-members - Static Fields and Methods
summary: Static members belong to the class itself, are shared by every instance, and can be used without an object.
- static-members/instance-copy-of-static | static memory | Each instantiated object maintains its own independent copy of a static class field.
- static-members/static-accesses-this | static context | Static methods possess an implicit this reference and can directly read or write instance fields.
- static-members/static-methods-overridable | method dispatch | Declaring a static method with the same signature in a subclass overrides the superclass static method polymorphically.
- static-members/static-requires-instance | static invocation | Static fields and methods cannot be accessed unless at least one instance of the declaring class has been instantiated.
- static-members/static-variable-reinitialized-on-new | static lifecycle | Static fields are reinitialized back to their initial declaration values every time a new object of that class is created.

## this-keyword - The this Reference
summary: Inside an instance method, this refers to the object the method was invoked on.
- this-keyword/this-refers-to-class | reference target | The this keyword refers to the class definition itself rather than the current instance invoking the method.
- this-keyword/this-in-static-methods | context validity | The this keyword can be legally referenced inside static methods to refer to current state.
- this-keyword/this-call-anywhere-in-constructor | constructor delegation | A this(...) constructor delegation call can appear on any line inside a constructor body.
- this-keyword/this-creates-new-instance | instance identity | Passing or returning this creates a new cloned copy of the current object.

## reference-semantics - References vs Values
summary: Object variables hold references, so assignment copies the reference and two variables can alias one object.
- reference-semantics/pass-by-reference | argument passing | Java passes object arguments using true pass-by-reference parameter passing.
- reference-semantics/reassignment-mutates-caller | parameter reassignment | Reassigning a method parameter variable to point to a new object changes the caller's reference variable.
- reference-semantics/double-equals-compares-content | equality comparison | The == operator on reference variables compares the internal values of the two objects.
- reference-semantics/aliases-are-independent | aliasing mutation | Modifying an object's fields through one reference does not affect the data seen when reading through another alias reference.
- reference-semantics/string-equals-is-double-equals | string equality | The == operator and the .equals() method always produce the exact same result when comparing two String variables.

## object-composition - Composition (has-a)
summary: One object can hold other objects as fields, building bigger behaviour out of smaller parts.
- object-composition/composition-requires-inheritance | has-a vs is-a | A class cannot hold references to other classes unless it explicitly extends them using inheritance.
- object-composition/cascade-deletion | lifecycle dependency | Setting the outer composite object reference to null immediately destroys all member objects it pointed to.
- object-composition/direct-private-access | member visibility | An enclosing composite class can directly read and write private fields of its composed member instances.
- object-composition/composite-automatic-delegation | method delegation | A composite class automatically inherits and exposes all public methods of its inner member objects.

## garbage-collection - Garbage Collection
summary: The JVM reclaims objects that are no longer reachable from any live reference.
- garbage-collection/system-gc-forces-immediate-collection | gc invocation | Calling System.gc() guarantees that the JVM immediately runs garbage collection and cleans all eligible heap memory.
- garbage-collection/nulling-destroys-object | deallocation timing | Setting a reference variable to null immediately deletes the referenced object from memory.
- garbage-collection/stack-variables-garbage-collected | memory reclamation | Local primitive variables and stack frames are cleaned up by the garbage collector.
- garbage-collection/circular-references-leak | reachability analysis | Two unreferenced objects pointing to each other can never be collected by the Java garbage collector.

## local-vs-instance-variables - Local vs Instance Variables
summary: Local variables live on the stack for one method call and must be initialised; instance variables live with the object.
- local-vs-instance-variables/local-variables-default-initialized | variable initialization | Uninitialized local variables declared inside a method automatically receive default values like 0 or null.
- local-vs-instance-variables/local-shadows-permanently | variable shadowing | Declaring a local variable with the same name as an instance field destroys access to the field throughout the method.
- local-vs-instance-variables/locals-retain-state-across-calls | variable lifetime | Local variables retain their assigned values from one invocation of a method to the next.
- local-vs-instance-variables/access-modifiers-on-locals | variable declaration | Local variables can be declared with access modifiers such as public, protected, or private.

## default-values - Default Field Values
summary: Instance and static fields are zero-initialised (0, false, null) before any constructor code runs.
- default-values/boolean-defaults-to-true | primitive defaults | Uninitialized boolean instance fields default to true in Java.
- default-values/strings-default-to-empty | reference defaults | Uninitialized String instance fields default to an empty string ("") instead of null.
- default-values/numeric-defaults-undefined | field initialization | Uninitialized numeric instance fields hold unpredictable garbage memory values like in C/C++.
- default-values/local-primitives-zeroed | scope initialization | Local primitive variables declared in method bodies default to zero if left unassigned.
